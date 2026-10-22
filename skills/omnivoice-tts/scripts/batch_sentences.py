#!/usr/bin/env python3
"""Synthesize each [[sentences]] entry from a transcript TOML with one OmniVoice session."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import importlib.util

_spec = importlib.util.spec_from_file_location("omnivoice_tts", SCRIPT_DIR / "omnivoice_tts.py")
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

DEFAULT_CACHE = _mod.DEFAULT_CACHE
DEFAULT_MODEL = _mod.DEFAULT_MODEL
DEFAULT_PROFILES_DIR = _mod.DEFAULT_PROFILES_DIR
best_device = _mod.best_device
load_profile = _mod.load_profile
resolve_dtype = _mod.resolve_dtype


def load_sentences(transcript_path: Path, *, shard: int, shard_count: int) -> list[dict]:
    data = tomllib.loads(transcript_path.read_text(encoding="utf-8"))
    sentences = data.get("sentences") or []
    if shard_count < 1:
        raise SystemExit("--shard-count must be >= 1")
    if shard < 0 or shard >= shard_count:
        raise SystemExit(f"--shard must be in [0, {shard_count - 1}]")
    picked = [s for i, s in enumerate(sentences) if i % shard_count == shard]
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--voice-name", required=True)
    parser.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--language", default="Vietnamese")
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "mps", "cuda", "xpu"))
    parser.add_argument("--num-step", type=int, default=16)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--manifest", type=Path, help="Write JSON manifest for this shard")
    args = parser.parse_args()

    import os

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(args.cache_dir))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(args.cache_dir / "hub"))

    import soundfile as sf  # noqa: WPS433
    import torch  # noqa: WPS433
    from omnivoice import OmniVoice  # noqa: WPS433

    sentences = load_sentences(args.transcript, shard=args.shard, shard_count=args.shard_count)
    if not sentences:
        print("No sentences for this shard.", file=sys.stderr)
        return 0

    profile = load_profile(args.profiles_dir, args.voice_name)
    ref_audio = profile["_audio"]
    ref_text = profile["_text"].read_text(encoding="utf-8").strip()

    device = best_device(torch, args.device)
    dtype = resolve_dtype(torch, device, "auto")
    print(
        f"[shard {args.shard}/{args.shard_count}] Loading {args.model} on {device}...",
        file=sys.stderr,
    )
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=dtype,
        load_asr=False,
    )
    generate_args = {
        "language": args.language,
        "num_step": args.num_step,
        "speed": args.speed,
        "ref_audio": str(ref_audio.resolve()),
        "ref_text": ref_text,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    for index, sentence in enumerate(sentences, start=1):
        sid = str(sentence["id"])
        text = str(sentence.get("sentence") or "").strip()
        if not text:
            print(f"Skip empty {sid}", file=sys.stderr)
            continue
        print(f"[shard {args.shard}] {index}/{len(sentences)} {sid} ({len(text)} chars)", file=sys.stderr)
        audio = model.generate(text=text, **generate_args)
        if not audio:
            raise RuntimeError(f"OmniVoice returned no audio for {sid}")
        out_path = args.output_dir / f"{sid}.wav"
        sf.write(out_path, audio[0], model.sampling_rate)
        manifest.append(
            {
                "id": sid,
                "start": sentence.get("start"),
                "end": sentence.get("end"),
                "text": text,
                "wav": str(out_path),
                "shard": args.shard,
            }
        )

    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"shard": args.shard, "generated": len(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
