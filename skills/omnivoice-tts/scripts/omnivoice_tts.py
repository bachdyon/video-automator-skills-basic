#!/usr/bin/env python3
"""Local TTS and zero-shot voice cloning with k2-fsa/OmniVoice."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE = REPO_ROOT / ".cache" / "omnivoice-tts" / "huggingface"
DEFAULT_MODEL = "k2-fsa/OmniVoice"
DEFAULT_PROFILES_DIR = REPO_ROOT / "voice_profiles" / "omnivoice"
FIX_OMNIVOICE_SCRIPT = (
    REPO_ROOT / "skills" / "fix-omnivoice" / "scripts" / "fix_omnivoice.py"
)
PROFILE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def read_text(value: str | None, path: Path | None, label: str) -> str | None:
    if value and path:
        raise ValueError(f"Use either --{label} or --{label}-file, not both.")
    if path:
        return path.expanduser().read_text(encoding="utf-8").strip()
    return value.strip() if value else None


def normalize_linebreaks(text: str) -> str:
    """Canonicalize narration line breaks without guessing semantic beats.

    Blank lines are the contract for paragraph/beat boundaries. This helper
    normalizes platform line endings, removes a leading BOM, trims each line,
    and collapses repeated blank lines to one separator. Non-empty single line
    breaks are preserved so the wrapper never silently merges user-authored
    narration structure.
    """
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    normalized: list[str] = []
    previous_blank = True
    for raw_line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if normalized and not previous_blank:
                normalized.append("")
            previous_blank = True
            continue
        normalized.append(line)
        previous_blank = False
    return "\n".join(normalized).strip()


def best_device(torch: Any, requested: str) -> str:
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def high_quality_device(requested: str) -> str:
    """Select MPS for high-quality synthesis unless explicitly overridden."""
    if requested != "auto":
        return requested
    return "mps"


def resolve_dtype(torch: Any, device: str, requested: str) -> Any:
    if requested == "auto":
        return torch.float32 if device == "cpu" else torch.float16
    return {
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }[requested]


def active_speech_rms(audio: Any, sample_rate: int, threshold_db: float = -42.0) -> float:
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    frame_size = max(1, round(sample_rate * 0.02))
    frame_count = (len(samples) + frame_size - 1) // frame_size
    padded = np.pad(samples, (0, frame_count * frame_size - len(samples)))
    frames = padded.reshape(frame_count, frame_size)
    frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    active = frame_rms >= 10.0 ** (threshold_db / 20.0)
    if not np.any(active):
        return 0.0
    return float(np.sqrt(np.mean(np.square(frames[active], dtype=np.float64))))


def normalize_chunk_levels(
    chunks: list[Any], sample_rate: int, max_gain_db: float
) -> tuple[list[Any], list[float]]:
    import numpy as np

    levels = [active_speech_rms(chunk, sample_rate) for chunk in chunks]
    valid_levels = [level for level in levels if level > 0]
    if not valid_levels:
        return chunks, [0.0 for _ in chunks]
    target = float(np.median(valid_levels))
    normalized = []
    applied_gain_db = []
    for chunk, level in zip(chunks, levels):
        samples = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if level <= 0:
            normalized.append(samples)
            applied_gain_db.append(0.0)
            continue
        desired_gain_db = 20.0 * np.log10(target / level)
        gain_db = float(np.clip(desired_gain_db, -max_gain_db, max_gain_db))
        gain = 10.0 ** (gain_db / 20.0)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if peak * gain > 0.98:
            gain = 0.98 / peak
            gain_db = 20.0 * np.log10(gain)
        normalized.append(samples * gain)
        applied_gain_db.append(round(gain_db, 3))
    return normalized, applied_gain_db


def cache_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def profile_id(name: str) -> str:
    value = name.strip()
    if not PROFILE_NAME_RE.fullmatch(value):
        raise SystemExit(
            f"Invalid voice name `{name}`. Use ASCII letters, digits, hyphens, or "
            "underscores, and start with a letter."
        )
    return value.lower().replace("_", "-")


def profile_path(profiles_dir: Path, name: str) -> Path:
    return profiles_dir.expanduser().resolve() / profile_id(name)


def scan_profiles(profiles_dir: Path) -> list[dict[str, Any]]:
    root = profiles_dir.expanduser().resolve()
    if not root.exists():
        return []
    profiles: list[dict[str, Any]] = []
    for metadata_path in sorted(root.glob("*/profile.toml")):
        try:
            with metadata_path.open("rb") as handle:
                metadata = tomllib.load(handle)
            profiles.append(
                {
                    "id": metadata.get("id", metadata_path.parent.name),
                    "name": metadata.get("name", metadata_path.parent.name),
                    "language": metadata.get("language", "Vietnamese"),
                    "model": metadata.get("model", DEFAULT_MODEL),
                    "path": str(metadata_path.parent),
                }
            )
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            continue
    return profiles


def load_profile(profiles_dir: Path, name: str) -> dict[str, Any]:
    folder = profile_path(profiles_dir, name)
    metadata_path = folder / "profile.toml"
    if not metadata_path.exists():
        available = ", ".join(item["name"] for item in scan_profiles(profiles_dir))
        raise SystemExit(
            f"Voice profile `{name}` was not found in {profiles_dir}. "
            f"Available profiles: {available or 'none'}"
        )
    with metadata_path.open("rb") as handle:
        metadata = tomllib.load(handle)
    if metadata.get("engine") != "omnivoice":
        raise SystemExit(f"Profile `{name}` is not an OmniVoice profile.")
    audio = folder / str(metadata["reference_audio"])
    text = folder / str(metadata["reference_text"])
    if not audio.is_file() or not text.is_file():
        raise SystemExit(f"Profile `{name}` is incomplete: {folder}")
    metadata["_audio"] = audio
    metadata["_text"] = text
    return metadata


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def derived_corrected_output(output: Path) -> Path:
    if output.stem.endswith("_corrected"):
        return output.with_name(f"{output.stem}_fixed.wav")
    return output.with_name(f"{output.stem}_corrected.wav")


def run_fix_omnivoice(
    output: Path,
    corrected_output: Path | None,
    report_path: Path | None,
) -> dict[str, Any]:
    if output.suffix.lower() != ".wav":
        raise SystemExit(
            "Automatic Fix OmniVoice requires WAV output. "
            "Use a .wav path or pass --skip-fix-omnivoice."
        )
    if not FIX_OMNIVOICE_SCRIPT.is_file():
        raise SystemExit(
            f"Fix OmniVoice skill script is missing: {FIX_OMNIVOICE_SCRIPT}"
        )

    corrected = (
        corrected_output.expanduser().resolve()
        if corrected_output
        else derived_corrected_output(output)
    )
    report = (
        report_path.expanduser().resolve()
        if report_path
        else corrected.with_name(f"{corrected.stem}_report.json")
    )
    command = [
        sys.executable,
        str(FIX_OMNIVOICE_SCRIPT),
        "--input",
        str(output),
        "--output",
        str(corrected),
        "--report",
        str(report),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Fix OmniVoice failed: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Fix OmniVoice returned invalid JSON: {completed.stdout!r}"
        ) from exc
    return {
        "corrected_output": str(corrected),
        "report": str(report),
        "summary": result.get("summary", {}),
        "verification": result.get("verification", {}),
    }


def create_profile(args: argparse.Namespace) -> int:
    if not args.authorized:
        raise SystemExit(
            "Refusing to create a reusable cloned-voice profile without --authorized. "
            "Confirm that the user owns or is authorized to clone this voice."
        )
    source_audio = args.ref_audio.expanduser().resolve()
    if not source_audio.is_file():
        raise SystemExit(f"Reference audio does not exist: {source_audio}")
    reference_text = read_text(args.ref_text, args.ref_text_file, "ref-text")
    if not reference_text:
        raise SystemExit("Provide the exact reference transcript.")

    folder = profile_path(args.profiles_dir, args.name)
    if folder.exists() and not args.replace:
        raise SystemExit(
            f"Profile already exists: {folder}. Use --replace to update it intentionally."
        )
    folder.mkdir(parents=True, exist_ok=True)
    output_audio = folder / "reference.wav"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to normalize a voice reference.")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source_audio),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(output_audio),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    output_text = folder / "reference.txt"
    output_text.write_text(reference_text.strip() + "\n", encoding="utf-8")

    identifier = profile_id(args.name)
    metadata = "\n".join(
        [
            "schema_version = 1",
            f"id = {toml_string(identifier)}",
            f"name = {toml_string(args.name.strip())}",
            'engine = "omnivoice"',
            f"model = {toml_string(args.model)}",
            f"language = {toml_string(args.language)}",
            'reference_audio = "reference.wav"',
            'reference_text = "reference.txt"',
            f"reference_sha256 = {toml_string(sha256(output_audio))}",
            f"num_step = {args.num_step}",
            f"speed = {args.speed}",
            f"created_at = {toml_string(datetime.now(timezone.utc).isoformat())}",
            "authorization_confirmed = true",
            f"authorization_note = {toml_string(args.authorization_note.strip())}",
            f"source_url = {toml_string(args.source_url.strip())}",
            "",
        ]
    )
    (folder / "profile.toml").write_text(metadata, encoding="utf-8")
    print(
        json.dumps(
            {
                "id": identifier,
                "name": args.name.strip(),
                "profile_dir": str(folder),
                "reference_audio": str(output_audio),
                "reference_text": str(output_text),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def list_profiles(args: argparse.Namespace) -> int:
    print(json.dumps(scan_profiles(args.profiles_dir), ensure_ascii=False, indent=2))
    return 0


def status(args: argparse.Namespace) -> int:
    packages = {}
    for name in ("omnivoice", "torch", "torchaudio", "transformers"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    import_error = None
    mps_built = None
    mps_available = None
    try:
        import omnivoice  # noqa: F401
        import torch
        import torchaudio

        mps_built = torch.backends.mps.is_built()
        mps_available = torch.backends.mps.is_available()
        if torch.__version__.split("+")[0] != torchaudio.__version__.split("+")[0]:
            raise RuntimeError(
                f"Torch {torch.__version__} and Torchaudio "
                f"{torchaudio.__version__} do not match."
            )
    except Exception as exc:
        import_error = f"{type(exc).__name__}: {exc}"

    result = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "packages": packages,
        "import_error": import_error,
        "mps_built": mps_built,
        "mps_available": mps_available,
        "cache_dir": str(args.cache_dir),
        "cache_bytes": cache_size(args.cache_dir),
        "ffprobe": shutil.which("ffprobe"),
        "ready": all(packages.values()) and import_error is None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


def synthesize(args: argparse.Namespace) -> int:
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(args.cache_dir))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(args.cache_dir / "hub"))
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    try:
        import soundfile as sf
        import torch
        from omnivoice import OmniVoice
    except ImportError as exc:
        raise SystemExit(
            "OmniVoice runtime is missing. Run: "
            "python3.11 skills/omnivoice-tts/scripts/setup_omnivoice.py"
        ) from exc

    text = read_text(args.text, args.text_file, "text")
    if not text:
        raise SystemExit("Provide non-empty --text or --text-file.")
    if args.normalize_linebreaks:
        text = normalize_linebreaks(text)
    if not text:
        raise SystemExit("Narration is empty after line-break normalization.")

    selected_profile = None
    requested_num_step = args.num_step
    if args.voice_name:
        if args.ref_audio or args.ref_text or args.ref_text_file:
            raise SystemExit(
                "Use either --voice-name or direct --ref-audio/--ref-text inputs, not both."
            )
        selected_profile = load_profile(args.profiles_dir, args.voice_name)
        args.ref_audio = selected_profile["_audio"]
        args.ref_text_file = selected_profile["_text"]
        args.model = args.model or selected_profile.get("model")
        args.language = args.language or selected_profile.get("language")
        args.num_step = args.num_step or selected_profile.get("num_step")
        args.speed = args.speed or selected_profile.get("speed")

    args.model = args.model or DEFAULT_MODEL
    args.language = args.language or "Vietnamese"
    if args.quality == "high" and requested_num_step is None:
        args.num_step = 32
    else:
        args.num_step = args.num_step or 16
    args.speed = args.speed or 1.0
    ref_text = read_text(args.ref_text, args.ref_text_file, "ref-text")
    if ref_text and not args.ref_audio:
        raise SystemExit("--ref-text requires --ref-audio.")

    if args.quality == "high":
        device = high_quality_device(args.device)
    else:
        device = best_device(torch, args.device)
    if device == "mps" and not torch.backends.mps.is_available():
        raise SystemExit(
            "MPS was requested but is unavailable in this Python/PyTorch runtime. "
            "Run where Metal GPU access is available or explicitly use --device cpu."
        )
    dtype = resolve_dtype(torch, device, args.dtype)
    print(
        f"Loading {args.model} on {device} with "
        f"{str(dtype).removeprefix('torch.')} ({args.quality} quality)...",
        file=sys.stderr,
    )
    load_args: dict[str, Any] = {
        "device_map": device,
        "dtype": dtype,
        "load_asr": bool(args.ref_audio and not ref_text),
    }
    model = OmniVoice.from_pretrained(args.model, **load_args)

    generate_args: dict[str, Any] = {
        "language": args.language,
        "num_step": args.num_step,
        "speed": args.speed,
    }
    if args.ref_audio:
        generate_args["ref_audio"] = str(args.ref_audio.expanduser().resolve())
        generate_args["ref_text"] = ref_text
    if args.instruct:
        generate_args["instruct"] = args.instruct

    chunks = [text]
    if args.split_paragraphs:
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    rendered_chunks = []
    for index, chunk in enumerate(chunks):
        print(
            f"Generating chunk {index + 1}/{len(chunks)} ({len(chunk)} chars)...",
            file=sys.stderr,
        )
        audio = model.generate(text=chunk, **generate_args)
        if not audio:
            raise RuntimeError(f"OmniVoice returned no audio for chunk {index + 1}.")
        rendered_chunks.append(audio[0])

    chunk_gain_db = [0.0 for _ in rendered_chunks]
    if args.normalize_chunk_levels and len(rendered_chunks) > 1:
        rendered_chunks, chunk_gain_db = normalize_chunk_levels(
            rendered_chunks, model.sampling_rate, args.max_chunk_gain_db
        )

    if len(rendered_chunks) == 1:
        rendered_audio = rendered_chunks[0]
    else:
        import numpy as np

        pause_samples = round(model.sampling_rate * args.pause_ms / 1000)
        silence = np.zeros(pause_samples, dtype=np.float32)
        pieces = []
        for index, chunk_audio in enumerate(rendered_chunks):
            pieces.append(np.asarray(chunk_audio, dtype=np.float32).reshape(-1))
            if index < len(rendered_chunks) - 1:
                pieces.append(silence)
        rendered_audio = np.concatenate(pieces)

    removed_islands = []
    if args.remove_low_volume_islands:
        from remove_low_volume_islands import find_islands

        import numpy as np

        rendered_audio = np.asarray(rendered_audio, dtype=np.float32).reshape(-1)
        removed_islands = find_islands(
            rendered_audio,
            model.sampling_rate,
            threshold_db=args.island_threshold_db,
            frame_ms=10.0,
            max_island_ms=160.0,
            min_quiet_ms=300.0,
        )
        for island in removed_islands:
            rendered_audio[
                int(island["start_sample"]) : int(island["end_sample"])
            ] = 0.0

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, rendered_audio, model.sampling_rate)
    fix_result = None
    if not args.skip_fix_omnivoice:
        fix_result = run_fix_omnivoice(
            output,
            args.corrected_output,
            args.fix_report,
        )
    print(
        json.dumps(
            {
                "output": str(output),
                "sample_rate": model.sampling_rate,
                "device": device,
                "dtype": str(dtype).removeprefix("torch."),
                "quality": args.quality,
                "num_step": args.num_step,
                "attention_implementation": "default",
                "model": args.model,
                "voice_name": selected_profile.get("name") if selected_profile else None,
                "chunks": len(chunks),
                "linebreaks_normalized": args.normalize_linebreaks,
                "chunk_level_normalized": args.normalize_chunk_levels,
                "chunk_gain_db": chunk_gain_db,
                "removed_low_volume_islands": len(removed_islands),
                "removed_island_duration_ms": round(
                    sum(float(item["duration_ms"]) for item in removed_islands), 3
                ),
                "pause_ms": args.pause_ms if len(chunks) > 1 else 0,
                "fix_omnivoice": fix_result,
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(func=status)

    profiles = subparsers.add_parser("profiles")
    profiles.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR)
    profiles.set_defaults(func=list_profiles)

    create = subparsers.add_parser("profile-create")
    create.add_argument("--name", required=True)
    create.add_argument("--ref-audio", type=Path, required=True)
    create_ref = create.add_mutually_exclusive_group(required=True)
    create_ref.add_argument("--ref-text")
    create_ref.add_argument("--ref-text-file", type=Path)
    create.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR)
    create.add_argument("--model", default=DEFAULT_MODEL)
    create.add_argument("--language", default="Vietnamese")
    create.add_argument("--num-step", type=int, default=16)
    create.add_argument("--speed", type=float, default=1.0)
    create.add_argument("--source-url", default="")
    create.add_argument("--authorization-note", default="")
    create.add_argument("--authorized", action="store_true")
    create.add_argument("--replace", action="store_true")
    create.set_defaults(func=create_profile)

    synth = subparsers.add_parser("synthesize")
    text_group = synth.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text")
    text_group.add_argument("--text-file", type=Path)
    synth.add_argument("--output", type=Path, required=True)
    synth.add_argument("--model")
    synth.add_argument("--language")
    synth.add_argument("--voice-name")
    synth.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR)
    synth.add_argument("--ref-audio", type=Path)
    ref_group = synth.add_mutually_exclusive_group()
    ref_group.add_argument("--ref-text")
    ref_group.add_argument("--ref-text-file", type=Path)
    synth.add_argument("--instruct")
    synth.add_argument(
        "--device",
        choices=("auto", "cpu", "mps", "cuda", "xpu"),
        default="auto",
    )
    synth.add_argument(
        "--dtype",
        choices=("auto", "float32", "float16", "bfloat16"),
        default="auto",
    )
    synth.add_argument(
        "--quality",
        choices=("standard", "high"),
        default="standard",
        help=(
            "High quality uses 32 steps by default and selects MPS with the "
            "standard float16/default-attention runtime."
        ),
    )
    synth.add_argument("--num-step", type=int)
    synth.add_argument("--speed", type=float)
    synth.add_argument(
        "--split-paragraphs",
        action="store_true",
        help="Generate each blank-line-separated paragraph separately in one model session.",
    )
    synth.add_argument(
        "--normalize-linebreaks",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Normalize CRLF/CR, BOM, line whitespace, and repeated blank lines "
            "before synthesis (default: enabled; disable with --no-normalize-linebreaks)."
        ),
    )
    synth.add_argument(
        "--pause-ms",
        type=int,
        default=260,
        help="Silence inserted between paragraph chunks when --split-paragraphs is used.",
    )
    synth.add_argument(
        "--normalize-chunk-levels",
        action="store_true",
        help="Match active-speech RMS across separately generated paragraph chunks.",
    )
    synth.add_argument(
        "--max-chunk-gain-db",
        type=float,
        default=8.0,
        help="Maximum gain adjustment per chunk during chunk-level normalization.",
    )
    synth.add_argument(
        "--remove-low-volume-islands",
        action="store_true",
        help="Zero short audio islands bracketed by long quiet regions.",
    )
    synth.add_argument(
        "--island-threshold-db",
        type=float,
        default=-36.0,
        help="Quiet threshold used by --remove-low-volume-islands.",
    )
    synth.add_argument(
        "--corrected-output",
        type=Path,
        help=(
            "Corrected WAV path created automatically by $fix-omnivoice. "
            "Defaults to <output-stem>_corrected.wav."
        ),
    )
    synth.add_argument(
        "--fix-report",
        type=Path,
        help=(
            "JSON audit path for automatic $fix-omnivoice cleanup. "
            "Defaults next to the corrected WAV."
        ),
    )
    synth.add_argument(
        "--skip-fix-omnivoice",
        action="store_true",
        help="Generate raw output only; skip the default $fix-omnivoice pass.",
    )
    synth.add_argument("--offline", action="store_true")
    synth.set_defaults(func=synthesize)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command in {"synthesize", "profile-create"}:
        if args.num_step is not None and args.num_step < 1:
            parser.error("--num-step must be positive.")
        if args.speed is not None and args.speed <= 0:
            parser.error("--speed must be positive.")
        if getattr(args, "pause_ms", 0) < 0:
            parser.error("--pause-ms cannot be negative.")
        if getattr(args, "max_chunk_gain_db", 1) <= 0:
            parser.error("--max-chunk-gain-db must be positive.")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
