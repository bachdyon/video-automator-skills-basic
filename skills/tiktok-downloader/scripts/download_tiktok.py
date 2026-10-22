#!/usr/bin/env python3
"""Download a public TikTok video using yt-dlp with an optional TikWM fallback."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover - Python's default CA bundle is normally sufficient.
    certifi = None

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "_shared"))
from pipeline_utils import die, media_metadata, write_toml_document  # noqa: E402

GENERIC_DOWNLOADER = REPO_ROOT / "skills" / "video-downloader" / "scripts" / "download_video.py"
TIKWM_SUBMIT_URL = "https://www.tikwm.com/api/video/task/submit"
TIKWM_RESULT_URL = "https://www.tikwm.com/api/video/task/result"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Mobile Safari/537.36"
)
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()


def slugify(value: str, fallback: str) -> str:
    text = re.sub(r"[^\w\s.-]+", "", value.lower(), flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip(".-")
    return (text or fallback)[:70]


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
        report = Path(args.job) / "source" / "tiktok_download_report.toml"
    else:
        report = output_dir / "tiktok_download_report.toml"
    return output_dir, report


def request_json(url: str, *, data: bytes | None = None) -> dict[str, Any]:
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "origin": "https://www.tikwm.com",
        "referer": "https://www.tikwm.com/originalDownloader.html",
        "user-agent": USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
    }
    if data is not None:
        headers["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(f"TikWM request failed: {exc}")
    if not isinstance(payload, dict):
        die("TikWM returned an invalid JSON response")
    if payload.get("code") not in (0, "0", None):
        die(f"TikWM rejected the request: {payload.get('msg') or 'unknown error'}")
    return payload


def submit_tikwm_task(source_url: str) -> tuple[str, dict[str, Any]]:
    body = urllib.parse.urlencode({"url": source_url, "web": "1"}).encode("utf-8")
    payload = request_json(TIKWM_SUBMIT_URL, data=body)
    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("task_id"):
        die("TikWM did not return a task ID")
    return str(data["task_id"]), data


def find_media_url(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("download_url", "play_url", "video_url", "url"):
        candidate = value.get(key)
        if not isinstance(candidate, str) or not candidate.startswith(("https://", "http://")):
            continue
        host = urllib.parse.urlparse(candidate).hostname or ""
        if host.endswith("tiktok.com") and "/@" in candidate:
            continue
        return candidate
    for key in ("data", "detail", "video", "result", "task"):
        nested = value.get(key)
        if isinstance(nested, dict):
            candidate = find_media_url(nested)
            if candidate:
                return candidate
    return None


def wait_for_media_url(task_id: str, timeout_seconds: int) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        query = urllib.parse.urlencode({"task_id": task_id})
        payload = request_json(f"{TIKWM_RESULT_URL}?{query}")
        last_payload = payload
        url = find_media_url(payload.get("data"))
        if url:
            return url, payload
        time.sleep(1)
    message = last_payload.get("msg") if isinstance(last_payload, dict) else ""
    die(f"TikWM did not return a media URL within {timeout_seconds}s: {message or 'task timed out'}")
    raise AssertionError("unreachable")


def detail_from(*payloads: dict[str, Any]) -> dict[str, Any]:
    for payload in payloads:
        data = payload.get("data")
        if isinstance(data, dict):
            detail = data.get("detail")
            if isinstance(detail, dict):
                return detail
            return data
    return {}


def download_media(media_url: str, output_path: Path, overwrite: bool) -> None:
    if output_path.exists() and not overwrite:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(media_url, headers={"user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90, context=SSL_CONTEXT) as response, output_path.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    except OSError as exc:
        if output_path.exists():
            output_path.unlink()
        die(f"TikWM media download failed: {exc}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        die("TikWM returned an empty media file")


def write_tikwm_report(
    report_path: Path,
    *,
    source_url: str,
    detail: dict[str, Any],
    output_path: Path,
) -> None:
    metadata = media_metadata(output_path)
    asset_id = str(detail.get("id") or hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:12])
    author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
    write_toml_document(
        report_path,
        [
            (
                "metadata",
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "provider": "tikwm",
                    "mode": "video",
                    "total_assets": 1,
                },
            ),
            (
                "assets",
                [
                    {
                        "provider": "tikwm",
                        "media_type": "video",
                        "source_url": source_url,
                        "asset_id": asset_id,
                        "title": str(detail.get("title") or ""),
                        "author": str(author.get("unique_id") or author.get("nickname") or ""),
                        "output_path": str(output_path),
                        "downloaded": True,
                        "size_bytes": output_path.stat().st_size,
                        "duration_seconds": float(metadata.get("duration_seconds") or detail.get("duration") or 0.0),
                        "width": int(metadata.get("width") or 0),
                        "height": int(metadata.get("height") or 0),
                    }
                ],
            ),
        ],
    )


def try_yt_dlp(args: argparse.Namespace, report_path: Path) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(GENERIC_DOWNLOADER), "--url", args.url, "--report-toml", str(report_path)]
    if args.job:
        command.extend(["--job", args.job])
    if args.output_dir:
        command.extend(["--output-dir", args.output_dir])
    if args.hd:
        command.append("--hd")
    if args.overwrite:
        command.append("--overwrite")
    return subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download a public TikTok video with yt-dlp and TikWM fallback.")
    parser.add_argument("--url", required=True, help="Public TikTok video URL.")
    parser.add_argument("--job", help="Job directory for standard raw-asset output.")
    parser.add_argument("--output-dir", help="Override video output directory.")
    parser.add_argument("--report-toml", help="Override download report path.")
    parser.add_argument("--hd", action="store_true", help="Prefer best available yt-dlp video format.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing output file.")
    parser.add_argument("--fallback-timeout", type=int, default=90, help="Maximum TikWM polling time in seconds.")
    parser.add_argument("--skip-tikwm-fallback", action="store_true", help="Do not send the URL to TikWM if yt-dlp fails.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not re.match(r"^https?://([^.]+\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/", args.url, flags=re.I):
        die("--url must be a public TikTok URL")
    if args.fallback_timeout < 1:
        die("--fallback-timeout must be at least 1 second")

    output_dir, report_path = output_defaults(args)
    primary = try_yt_dlp(args, report_path)
    if primary.returncode == 0:
        print(primary.stdout, end="")
        return 0
    if args.skip_tikwm_fallback:
        print(primary.stderr or primary.stdout, file=sys.stderr, end="")
        die("yt-dlp failed and TikWM fallback was disabled")

    print("yt-dlp could not extract this TikTok video; trying TikWM fallback.", file=sys.stderr)
    task_id, submitted = submit_tikwm_task(args.url)
    media_url, result = wait_for_media_url(task_id, args.fallback_timeout)
    detail = detail_from(result, submitted)
    asset_id = str(detail.get("id") or hashlib.sha1(args.url.encode("utf-8")).hexdigest()[:12])
    title = str(detail.get("title") or asset_id)
    output_path = output_dir / f"{asset_id}_{slugify(title, asset_id)}.mp4"
    download_media(media_url, output_path, args.overwrite)
    write_tikwm_report(report_path, source_url=args.url, detail=detail, output_path=output_path)
    print(f"assets=1 downloaded=1 report={report_path}")
    print(f"video\t{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
