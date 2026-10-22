#!/usr/bin/env python3
"""Generate local speech with Supertonic and a persistent repo-local model cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent
DEFAULT_MODEL = "supertonic-3"
DEFAULT_CACHE_ROOT = REPO_ROOT / ".cache" / "supertonic"


def import_supertonic():
    try:
        from supertonic import TTS
        from supertonic.loader import has_all_onnx_modules
    except ImportError as exc:
        requirements = SKILL_DIR / "scripts" / "requirements.txt"
        raise SystemExit(
            "Supertonic SDK is not installed for this Python interpreter. Run:\n"
            f"{sys.executable} -m pip install -r {requirements}"
        ) from exc
    return TTS, has_all_onnx_modules


def model_dir_for(args: argparse.Namespace) -> Path:
    if args.model_dir:
        return Path(args.model_dir).expanduser().resolve()
    return (DEFAULT_CACHE_ROOT / args.model).resolve()


def model_status(args: argparse.Namespace) -> dict[str, object]:
    _, has_all_onnx_modules = import_supertonic()
    model_dir = model_dir_for(args)
    voice_dir = model_dir / "voice_styles"
    voices = sorted(path.stem for path in voice_dir.glob("*.json")) if voice_dir.is_dir() else []
    return {
        "model": args.model,
        "model_dir": str(model_dir),
        "ready": has_all_onnx_modules(model_dir) and bool(voices),
        "voices": voices,
    }


def build_tts(args: argparse.Namespace):
    TTS, _ = import_supertonic()
    model_dir = model_dir_for(args)
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    return TTS(
        model=args.model,
        model_dir=model_dir,
        auto_download=not args.no_download,
        intra_op_num_threads=args.intra_op_threads,
        inter_op_num_threads=args.inter_op_threads,
    )


def read_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        text = args.text
    else:
        text = Path(args.text_file).read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        raise SystemExit("Input text is empty.")
    return text


def run_status(args: argparse.Namespace) -> int:
    print(json.dumps(model_status(args), ensure_ascii=False, indent=2))
    return 0


def run_list_voices(args: argparse.Namespace) -> int:
    tts = build_tts(args)
    payload = {
        "model": args.model,
        "model_dir": str(model_dir_for(args)),
        "voices": tts.voice_style_names,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_synthesize(args: argparse.Namespace) -> int:
    text = read_text(args)
    tts = build_tts(args)
    if args.voice_style:
        voice_style = tts.get_voice_style_from_path(Path(args.voice_style).expanduser().resolve())
        voice_label = str(Path(args.voice_style).expanduser().resolve())
    else:
        voice_style = tts.get_voice_style(args.voice)
        voice_label = args.voice

    wav, duration = tts.synthesize(
        text=text,
        lang=args.lang,
        voice_style=voice_style,
        total_steps=args.steps,
        speed=args.speed,
        max_chunk_length=args.max_chunk_length,
        silence_duration=args.silence_duration,
        verbose=args.verbose,
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    tts.save_audio(wav, str(output))
    seconds = float(duration[0]) if len(duration) else 0.0
    payload = {
        "state": "SUCCEED",
        "provider": "supertonic",
        "model": args.model,
        "model_dir": str(model_dir_for(args)),
        "voice": voice_label,
        "language": args.lang,
        "sample_rate": int(tts.sample_rate),
        "duration_seconds": round(seconds, 3),
        "output": str(output),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=["supertonic", "supertonic-2", "supertonic-3"])
    parser.add_argument("--model-dir", help="Override the persistent repo-local model directory.")
    parser.add_argument("--no-download", action="store_true", help="Fail when model assets are missing.")
    parser.add_argument("--intra-op-threads", type=int)
    parser.add_argument("--inter-op-threads", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Inspect cache without downloading a model.")
    add_model_options(status)
    status.set_defaults(func=run_status)

    voices = subparsers.add_parser("list-voices", help="List voices, downloading the model if needed.")
    add_model_options(voices)
    voices.set_defaults(func=run_list_voices)

    synthesize = subparsers.add_parser("synthesize", help="Generate a WAV file.")
    add_model_options(synthesize)
    text_group = synthesize.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text")
    text_group.add_argument("--text-file")
    voice_group = synthesize.add_mutually_exclusive_group()
    voice_group.add_argument("--voice", default="F1")
    voice_group.add_argument("--voice-style", help="Path to a custom Voice Builder JSON file.")
    synthesize.add_argument("--lang", default="vi")
    synthesize.add_argument("--speed", type=float, default=1.05)
    synthesize.add_argument("--steps", type=int, default=8)
    synthesize.add_argument("--max-chunk-length", type=int)
    synthesize.add_argument("--silence-duration", type=float, default=0.3)
    synthesize.add_argument("--output", required=True)
    synthesize.add_argument("--verbose", action="store_true")
    synthesize.set_defaults(func=run_synthesize)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
