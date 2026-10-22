#!/usr/bin/env python3
"""Build a Remotion props JSON file with subtitle pages (no punch)."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SPLIT_SCRIPT = SCRIPT_DIR / "split_subtitle_screens.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--display-text-file", type=Path, help="Script có dấu câu (vd. narration_vi.txt).")
    parser.add_argument("--screens-output", type=Path, help="Optional subtitle_screens.json path.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--source-video", default="assets/source.mp4")
    parser.add_argument("--voice-audio", default="assets/voice.wav")
    parser.add_argument("--source-audio", default="", help="Optional retimed original bed WAV path for the props file")
    parser.add_argument("--source-audio-volume", type=float, default=0.3)
    parser.add_argument("--subtitle-bottom-px", type=int, default=380)
    parser.add_argument("--subtitle-max-width-px", type=int, default=640)
    parser.add_argument("--subtitle-font-size", type=int, default=32)
    parser.add_argument("--max-words", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=36)
    parser.add_argument("--trim-before-frames", type=int, default=0)
    args = parser.parse_args()

    screens_path = args.screens_output or args.output.parent.parent.parent / "source" / "subtitle_screens.json"
    cmd = [
        sys.executable,
        str(SPLIT_SCRIPT),
        "--transcript",
        str(args.transcript),
        "--output",
        str(screens_path),
        "--max-words",
        str(args.max_words),
        "--max-chars",
        str(args.max_chars),
    ]
    if args.display_text_file:
        cmd.extend(["--display-text-file", str(args.display_text_file)])
    subprocess.run(cmd, check=True)

    pages = json.loads(screens_path.read_text(encoding="utf-8")).get("pages") or []
    duration_frames = max(1, math.ceil(args.duration_seconds * args.fps) - args.trim_before_frames)
    payload = {
        "fps": args.fps,
        "durationInFrames": duration_frames,
        "sourceVideo": args.source_video,
        "voiceAudio": args.voice_audio,
        "subtitle_pages": pages,
        "trimBeforeFrames": args.trim_before_frames,
        "subtitleBottomPx": args.subtitle_bottom_px,
        "subtitleMaxWidthPx": args.subtitle_max_width_px,
        "subtitleFontSize": args.subtitle_font_size,
    }
    if args.source_audio:
        payload["sourceAudio"] = args.source_audio
        payload["sourceAudioVolume"] = args.source_audio_volume
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} pages={len(pages)} durationInFrames={payload['durationInFrames']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
