#!/usr/bin/env python3
"""Download media from any yt-dlp-supported site for the video pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from pipeline_utils import die, media_metadata, write_toml_document  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[3]
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".opus", ".webm")


def slugify(value: str, fallback: str = "download") -> str:
    text = re.sub(r"[^\w\s.-]+", "", value.lower(), flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip(".-")
    return (text or fallback)[:70]


def short_hash(value: str, length: int = 8) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def media_id(info: dict[str, Any], source_url: str) -> str:
    value = info.get("id") or info.get("display_id")
    if value:
        return str(value)
    match = re.search(r"/video/(\d+)", source_url)
    if match:
        return match.group(1)
    return short_hash(source_url, 12)


def author_name(info: dict[str, Any]) -> str:
    for key in ("uploader", "channel", "creator"):
        value = info.get(key)
        if value:
            return str(value)
    return ""


def output_defaults(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif args.job:
        output_dir = Path(args.job) / "input" / "raw_assets" / "videos" / "downloaded"
    else:
        output_dir = Path("raw_assets") / "videos" / "downloaded"

    if args.report_toml:
        report = Path(args.report_toml)
    elif args.job:
        report = Path(args.job) / "source" / "download_report.toml"
    else:
        report = output_dir / "download_report.toml"
    return output_dir, report


def output_for_kind(base_output_dir: Path, kind: str) -> Path:
    if kind == "video":
        return base_output_dir
    parts = list(base_output_dir.parts)
    if "videos" in parts:
        parts[parts.index("videos")] = "images" if kind == "image" else "audio"
        return Path(*parts)
    return base_output_dir.parent / ("images" if kind == "image" else "audio") / base_output_dir.name


def read_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    if args.url:
        urls.append(args.url)
    if args.urls_file:
        for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                urls.append(item)
    if not urls:
        die("provide --url or --urls-file")
    return urls


def find_yt_dlp() -> list[str]:
    """Return a command that invokes yt-dlp, preferring the shared project venv."""
    candidates: list[Path] = []
    configured = os.environ.get("YTDLP_BIN")
    if configured:
        candidates.append(Path(configured))
    candidates.append(REPO_ROOT / ".venv" / "bin" / "yt-dlp")
    system_binary = shutil.which("yt-dlp")
    if system_binary:
        candidates.append(Path(system_binary))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return [str(candidate)]

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        pass
    else:
        return [sys.executable, "-m", "yt_dlp"]

    die(
        "yt-dlp was not found. Install it in the shared venv with "
        "python3 -m pip install -U yt-dlp, or set YTDLP_BIN."
    )
    raise AssertionError("unreachable")


def yt_dlp_options(args: argparse.Namespace) -> list[str]:
    options = ["--no-playlist", "--newline", "--no-warnings"]
    if args.cookies_from_browser:
        options.extend(["--cookies-from-browser", args.cookies_from_browser])
    if args.extractor_args:
        options.extend(["--extractor-args", args.extractor_args])
    if args.proxy:
        options.extend(["--proxy", args.proxy])
    return options


def run_yt_dlp(
    command: list[str],
    *,
    source_url: str,
    operation: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
    except FileNotFoundError:
        die("yt-dlp executable could not be started")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if len(detail) > 1800:
            detail = detail[-1800:]
        die(f"yt-dlp failed during {operation} for {source_url}:\n{detail}")
    return result


def extract_info(source_url: str, args: argparse.Namespace, yt_dlp: list[str]) -> dict[str, Any]:
    command = yt_dlp + yt_dlp_options(args) + ["--dump-single-json", "--skip-download", source_url]
    result = run_yt_dlp(command, source_url=source_url, operation="metadata extraction")
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(info, dict):
            return info
    die(f"yt-dlp returned no metadata for {source_url}")
    raise AssertionError("unreachable")


def matching_files(directory: Path, stem: str, extensions: tuple[str, ...]) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path for path in directory.glob(f"{stem}.*")
        if path.is_file() and path.suffix.lower() in extensions
    )


def download_kind(
    source_url: str,
    *,
    info: dict[str, Any],
    args: argparse.Namespace,
    yt_dlp: list[str],
    kind: str,
    output_dir: Path,
    stem: str,
) -> list[Path]:
    del info  # Metadata is used by the caller; yt-dlp reuses the source URL here.
    output_dir.mkdir(parents=True, exist_ok=True)
    extensions = {
        "video": VIDEO_EXTENSIONS,
        "image": IMAGE_EXTENSIONS,
        "audio": AUDIO_EXTENSIONS,
    }[kind]
    existing = matching_files(output_dir, stem, extensions)
    if existing and not args.overwrite:
        return existing

    template = str(output_dir / f"{stem}.%(ext)s")
    command = yt_dlp + yt_dlp_options(args)
    command.extend(["-o", template])

    if kind == "video":
        if args.hd:
            command.extend(["-f", "bv*+ba/b"])
        command.append("--merge-output-format")
        command.append("mp4")
        if shutil.which("ffmpeg"):
            command.extend(["--remux-video", "mp4"])
    elif kind == "audio":
        command.extend(["--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"])
    else:
        # yt-dlp exposes thumbnails consistently; sites do not necessarily
        # expose original gallery or slideshow images through stable fields.
        command.extend(["--write-all-thumbnails", "--skip-download"])
        if shutil.which("ffmpeg"):
            command.extend(["--convert-thumbnails", "jpg"])

    if args.overwrite:
        command.append("--force-overwrites")
    command.append(source_url)
    result = run_yt_dlp(command, source_url=source_url, operation=f"{kind} download")

    files = matching_files(output_dir, stem, extensions)
    if not files:
        for line in reversed(result.stdout.splitlines()):
            candidate = Path(line.strip())
            if candidate.is_file() and candidate.suffix.lower() in extensions:
                files.append(candidate)
                break
    return files


def append_asset_row(
    rows: list[dict[str, Any]],
    *,
    source_url: str,
    info: dict[str, Any],
    kind: str,
    output_path: Path,
) -> None:
    metadata = media_metadata(output_path) if output_path.exists() else {}
    rows.append(
        {
            "provider": "yt-dlp",
            "media_type": kind,
            "source_url": source_url,
            "asset_id": media_id(info, source_url),
            "title": str(info.get("title") or ""),
            "author": author_name(info),
            "output_path": str(output_path),
            "downloaded": True,
            "size_bytes": int(output_path.stat().st_size) if output_path.exists() else 0,
            "duration_seconds": float(metadata.get("duration_seconds") or info.get("duration") or 0.0),
            "width": int(metadata.get("width") or info.get("width") or 0),
            "height": int(metadata.get("height") or info.get("height") or 0),
        }
    )


def process_one(
    source_url: str,
    args: argparse.Namespace,
    base_output_dir: Path,
    rows: list[dict[str, Any]],
    yt_dlp: list[str],
) -> None:
    info = extract_info(source_url, args, yt_dlp)
    item_id = media_id(info, source_url)
    title = str(info.get("title") or author_name(info) or item_id)
    slug = slugify(title, fallback=item_id)
    stem = f"{item_id}_{slug}"

    requested_kinds = ["video", "image", "audio"] if args.mode == "all" else [
        "image" if args.mode == "images" else args.mode,
    ]
    for kind in requested_kinds:
        files = download_kind(
            source_url,
            info=info,
            args=args,
            yt_dlp=yt_dlp,
            kind=kind,
            output_dir=output_for_kind(base_output_dir, kind),
            stem=stem,
        )
        if not files:
            if args.mode != "all":
                detail = "thumbnail" if kind == "image" else kind
                die(f"yt-dlp produced no {detail} asset for {source_url}")
            print(f"warning: yt-dlp produced no {kind} asset for {source_url}", file=sys.stderr)
            continue
        for path in files:
            append_asset_row(rows, source_url=source_url, info=info, kind=kind, output_path=path)


def write_report(path: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    write_toml_document(
        path,
        [
            (
                "metadata",
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "provider": "yt-dlp",
                    "mode": args.mode,
                    "hd": bool(args.hd),
                    "total_assets": len(rows),
                },
            ),
            ("assets", rows),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download media through yt-dlp from a supported URL.")
    parser.add_argument("--url", help="Public URL supported by yt-dlp.")
    parser.add_argument("--urls-file", help="Text file with one yt-dlp-supported URL per line.")
    parser.add_argument("--job", help="Job directory; defaults output/report into the job layout.")
    parser.add_argument("--output-dir", help="Output directory for video assets.")
    parser.add_argument("--report-toml", help="Path to write download report TOML.")
    parser.add_argument("--mode", choices=["video", "images", "audio", "all"], default="video")
    parser.add_argument("--hd", action="store_true", help="Prefer best available video format.")
    parser.add_argument("--cookies-from-browser", help="Browser profile for yt-dlp, e.g. chrome or safari.")
    parser.add_argument("--extractor-args", help="Pass yt-dlp extractor arguments verbatim.")
    parser.add_argument("--proxy", help="Proxy URL passed to yt-dlp.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_output_dir, report_path = output_defaults(args)
    rows: list[dict[str, Any]] = []
    yt_dlp = find_yt_dlp()
    for url in read_urls(args):
        process_one(url, args, base_output_dir, rows, yt_dlp)
    if not rows:
        die("no assets were downloaded")
    write_report(report_path, rows, args)
    print(f"assets={len(rows)} downloaded={len(rows)} report={report_path}")
    for row in rows:
        print(f"{row['media_type']}\t{row['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
