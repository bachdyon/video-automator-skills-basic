#!/usr/bin/env python3
"""Manage reusable local voice profiles and dispatch synthesis by name."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = REPO_ROOT / "voice_profiles"
OMNIVOICE_SCRIPT = REPO_ROOT / "skills" / "omnivoice-tts" / "scripts" / "omnivoice_tts.py"
OMNIVOICE_PYTHON = REPO_ROOT / ".cache" / "omnivoice-tts" / "venv" / "bin" / "python"
REQUIRED_FIELDS = {
    "schema_version",
    "id",
    "name",
    "engine",
    "model",
    "language",
    "reference_audio",
    "reference_text",
    "reference_sha256",
    "authorization_confirmed",
    "authorization_note",
    "source_url",
}


def read_profile(metadata_path: Path) -> dict[str, Any]:
    with metadata_path.open("rb") as handle:
        data = tomllib.load(handle)
    data["_profile_dir"] = metadata_path.parent.resolve()
    data["_metadata_path"] = metadata_path.resolve()
    return data


def scan_profiles(registry: Path) -> list[dict[str, Any]]:
    root = registry.expanduser().resolve()
    profiles: list[dict[str, Any]] = []
    if not root.exists():
        return profiles
    for metadata_path in sorted(root.glob("*/*/profile.toml")):
        try:
            profiles.append(read_profile(metadata_path))
        except (OSError, tomllib.TOMLDecodeError):
            profiles.append(
                {
                    "id": metadata_path.parent.name,
                    "name": metadata_path.parent.name,
                    "engine": metadata_path.parent.parent.name,
                    "_profile_dir": metadata_path.parent.resolve(),
                    "_metadata_path": metadata_path.resolve(),
                    "_parse_error": True,
                }
            )
    return profiles


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in profile.items()
        if not key.startswith("_") and key not in {"authorization_note"}
    } | {"path": str(profile["_profile_dir"])}


def resolve_profile(registry: Path, name: str, engine: str | None) -> dict[str, Any]:
    needle = name.casefold()
    matches = [
        profile
        for profile in scan_profiles(registry)
        if str(profile.get("id", "")).casefold() == needle
        or str(profile.get("name", "")).casefold() == needle
    ]
    if engine:
        matches = [
            profile
            for profile in matches
            if str(profile.get("engine", "")).casefold() == engine.casefold()
        ]
    if not matches:
        raise SystemExit(f"Voice profile `{name}` was not found.")
    if len(matches) > 1:
        engines = ", ".join(sorted(str(item.get("engine")) for item in matches))
        raise SystemExit(
            f"Voice name `{name}` exists in multiple engines ({engines}); pass --engine."
        )
    return matches[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_local_file(profile_dir: Path, value: Any) -> Path:
    candidate = (profile_dir / str(value)).resolve()
    if profile_dir != candidate and profile_dir not in candidate.parents:
        raise ValueError(f"Profile file escapes its directory: {value}")
    return candidate


def audio_metadata(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"warning": "ffprobe not found"}
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def verify_audio_decode(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        check=True,
        capture_output=True,
        text=True,
    )


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    missing = sorted(REQUIRED_FIELDS - profile.keys())
    if missing:
        errors.append(f"Missing fields: {', '.join(missing)}")
    if profile.get("_parse_error"):
        errors.append("profile.toml could not be parsed")
    if profile.get("authorization_confirmed") is not True:
        errors.append("authorization_confirmed must be true")
    if not str(profile.get("authorization_note", "")).strip():
        errors.append("authorization_note must record the confirmation context")

    reference_audio = None
    reference_text = None
    try:
        reference_audio = resolve_local_file(
            profile["_profile_dir"], profile.get("reference_audio", "")
        )
        reference_text = resolve_local_file(
            profile["_profile_dir"], profile.get("reference_text", "")
        )
    except ValueError as exc:
        errors.append(str(exc))

    if reference_audio and not reference_audio.is_file():
        errors.append(f"Missing reference audio: {reference_audio}")
    if reference_text and not reference_text.is_file():
        errors.append(f"Missing reference transcript: {reference_text}")
    if reference_text and reference_text.is_file() and not reference_text.read_text(
        encoding="utf-8"
    ).strip():
        errors.append("Reference transcript is empty")
    if reference_audio and reference_audio.is_file():
        expected = str(profile.get("reference_sha256", ""))
        actual = sha256(reference_audio)
        if expected and expected != actual:
            errors.append("Reference audio SHA-256 does not match profile metadata")
        if not expected:
            warnings.append("Reference audio SHA-256 is missing")

    inspected_audio = None
    if reference_audio and reference_audio.is_file():
        try:
            inspected_audio = audio_metadata(reference_audio)
            verify_audio_decode(reference_audio)
            streams = inspected_audio.get("streams", [])
            stream = streams[0] if streams else {}
            duration = float(inspected_audio.get("format", {}).get("duration", 0))
            if not streams or duration <= 0:
                errors.append("Reference audio has no readable positive-duration stream")
            if profile.get("engine") == "omnivoice":
                if stream.get("codec_name") != "pcm_s16le":
                    errors.append("OmniVoice reference audio must be PCM signed 16-bit WAV")
                if int(stream.get("sample_rate", 0)) != 24000:
                    errors.append("OmniVoice reference audio must use a 24 kHz sample rate")
                if int(stream.get("channels", 0)) != 1:
                    errors.append("OmniVoice reference audio must be mono")
                if duration and not 3 <= duration <= 10:
                    warnings.append(
                        "OmniVoice references work best at 3–10 seconds; review this sample"
                    )
        except (
            OSError,
            RuntimeError,
            ValueError,
            subprocess.CalledProcessError,
            json.JSONDecodeError,
        ) as exc:
            errors.append(f"Could not inspect reference audio: {exc}")

    result: dict[str, Any] = {
        "id": profile.get("id"),
        "name": profile.get("name"),
        "engine": profile.get("engine"),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "path": str(profile["_profile_dir"]),
    }
    if inspected_audio is not None:
        result["audio"] = inspected_audio
    return result


def list_command(args: argparse.Namespace) -> int:
    profiles = scan_profiles(args.registry)
    if args.engine:
        profiles = [
            item
            for item in profiles
            if str(item.get("engine", "")).casefold() == args.engine.casefold()
        ]
    print(json.dumps([public_profile(item) for item in profiles], ensure_ascii=False, indent=2))
    return 0


def show_command(args: argparse.Namespace) -> int:
    profile = resolve_profile(args.registry, args.voice, args.engine)
    result = public_profile(profile)
    result["authorization_note_recorded"] = bool(profile.get("authorization_note"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def validate_command(args: argparse.Namespace) -> int:
    profiles = (
        [resolve_profile(args.registry, args.voice, args.engine)]
        if args.voice
        else scan_profiles(args.registry)
    )
    results = [validate_profile(profile) for profile in profiles]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["valid"] for item in results) else 1


def require_omnivoice_runtime() -> None:
    if not OMNIVOICE_PYTHON.is_file() or not OMNIVOICE_SCRIPT.is_file():
        raise SystemExit(
            "OmniVoice runtime is unavailable. Follow $omnivoice-tts setup first."
        )


def add_profile(args: argparse.Namespace) -> int:
    if args.engine != "omnivoice":
        raise SystemExit(f"Unsupported engine adapter: {args.engine}")
    require_omnivoice_runtime()
    command = [
        str(OMNIVOICE_PYTHON),
        str(OMNIVOICE_SCRIPT),
        "profile-create",
        "--name",
        args.name,
        "--ref-audio",
        str(args.ref_audio),
        "--profiles-dir",
        str(args.registry / "omnivoice"),
        "--source-url",
        args.source_url,
        "--authorization-note",
        args.authorization_note,
    ]
    command.extend(["--ref-text", args.ref_text] if args.ref_text else [
        "--ref-text-file",
        str(args.ref_text_file),
    ])
    if args.authorized:
        command.append("--authorized")
    if args.replace:
        command.append("--replace")
    return subprocess.run(command, check=False).returncode


def synthesize(args: argparse.Namespace) -> int:
    profile = resolve_profile(args.registry, args.voice, args.engine)
    engine = str(profile.get("engine", ""))
    if engine != "omnivoice":
        raise SystemExit(f"Unsupported synthesis adapter: {engine}")
    require_omnivoice_runtime()
    command = [
        str(OMNIVOICE_PYTHON),
        str(OMNIVOICE_SCRIPT),
        "synthesize",
        "--voice-name",
        str(profile["name"]),
        "--profiles-dir",
        str(args.registry / engine),
        "--output",
        str(args.output),
        "--device",
        args.device,
    ]
    command.extend(["--text", args.text] if args.text else ["--text-file", str(args.text_file)])
    if args.num_step:
        command.extend(["--num-step", str(args.num_step)])
    if args.speed:
        command.extend(["--speed", str(args.speed)])
    if args.language:
        command.extend(["--language", args.language])
    if args.offline:
        command.append("--offline")
    return subprocess.run(command, check=False).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list")
    listing.add_argument("--engine")
    listing.set_defaults(func=list_command)

    show = subparsers.add_parser("show")
    show.add_argument("voice")
    show.add_argument("--engine")
    show.set_defaults(func=show_command)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--voice")
    validate.add_argument("--engine")
    validate.set_defaults(func=validate_command)

    add = subparsers.add_parser("add")
    add.add_argument("--engine", choices=("omnivoice",), required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--ref-audio", type=Path, required=True)
    add_ref = add.add_mutually_exclusive_group(required=True)
    add_ref.add_argument("--ref-text")
    add_ref.add_argument("--ref-text-file", type=Path)
    add.add_argument("--source-url", default="")
    add.add_argument("--authorization-note", default="")
    add.add_argument("--authorized", action="store_true")
    add.add_argument("--replace", action="store_true")
    add.set_defaults(func=add_profile)

    generate = subparsers.add_parser("synthesize")
    generate.add_argument("--voice", required=True)
    generate.add_argument("--engine")
    generate_text = generate.add_mutually_exclusive_group(required=True)
    generate_text.add_argument("--text")
    generate_text.add_argument("--text-file", type=Path)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument(
        "--device", choices=("auto", "cpu", "mps", "cuda", "xpu"), default="auto"
    )
    generate.add_argument("--num-step", type=int)
    generate.add_argument("--speed", type=float)
    generate.add_argument("--language")
    generate.add_argument("--offline", action="store_true")
    generate.set_defaults(func=synthesize)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
