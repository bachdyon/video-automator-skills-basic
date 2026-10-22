#!/usr/bin/env python3
"""Remove short audio islands bracketed by long quiet regions."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf


def dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def runs(values: np.ndarray) -> list[tuple[bool, int, int]]:
    if values.size == 0:
        return []
    changes = np.flatnonzero(values[1:] != values[:-1]) + 1
    starts = np.concatenate(([0], changes))
    ends = np.concatenate((changes, [values.size]))
    return [(bool(values[start]), int(start), int(end)) for start, end in zip(starts, ends)]


def find_islands(
    audio: np.ndarray,
    sample_rate: int,
    *,
    threshold_db: float,
    frame_ms: float,
    max_island_ms: float,
    min_quiet_ms: float,
) -> list[dict[str, float | int]]:
    analysis = audio if audio.ndim == 1 else np.mean(audio, axis=1)
    frame_size = max(1, round(sample_rate * frame_ms / 1000.0))
    frame_count = math.ceil(len(analysis) / frame_size)
    padded = np.pad(analysis, (0, frame_count * frame_size - len(analysis)))
    framed = padded.reshape(frame_count, frame_size)
    rms = np.sqrt(np.mean(np.square(framed, dtype=np.float64), axis=1))
    quiet = rms < 10.0 ** (threshold_db / 20.0)
    frame_runs = runs(quiet)

    islands: list[dict[str, float | int]] = []
    for index in range(1, len(frame_runs) - 1):
        is_quiet, start_frame, end_frame = frame_runs[index]
        if is_quiet:
            continue
        previous = frame_runs[index - 1]
        following = frame_runs[index + 1]
        if not previous[0] or not following[0]:
            continue

        duration_ms = (end_frame - start_frame) * frame_ms
        previous_quiet_ms = (previous[2] - previous[1]) * frame_ms
        following_quiet_ms = (following[2] - following[1]) * frame_ms
        if duration_ms > max_island_ms:
            continue
        if min(previous_quiet_ms, following_quiet_ms) < min_quiet_ms:
            continue

        start_sample = start_frame * frame_size
        end_sample = min(len(audio), end_frame * frame_size)
        island_audio = analysis[start_sample:end_sample]
        island_rms = float(np.sqrt(np.mean(np.square(island_audio, dtype=np.float64))))
        island_peak = float(np.max(np.abs(island_audio)))
        islands.append(
            {
                "start_sample": start_sample,
                "end_sample": end_sample,
                "start_seconds": round(start_sample / sample_rate, 6),
                "end_seconds": round(end_sample / sample_rate, 6),
                "duration_ms": round(1000.0 * (end_sample - start_sample) / sample_rate, 3),
                "rms_dbfs": round(dbfs(island_rms), 3),
                "peak_dbfs": round(dbfs(island_peak), 3),
                "quiet_before_ms": round(previous_quiet_ms, 3),
                "quiet_after_ms": round(following_quiet_ms, 3),
            }
        )
    return islands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--threshold-db", type=float, default=-36.0)
    parser.add_argument("--frame-ms", type=float, default=10.0)
    parser.add_argument("--max-island-ms", type=float, default=160.0)
    parser.add_argument("--min-quiet-ms", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input audio does not exist: {input_path}")
    if not args.dry_run and args.output is None:
        raise SystemExit("Provide --output unless --dry-run is used.")
    if args.frame_ms <= 0 or args.max_island_ms <= 0 or args.min_quiet_ms <= 0:
        raise SystemExit("Frame and duration values must be positive.")

    audio, sample_rate = sf.read(input_path, always_2d=False, dtype="float32")
    islands = find_islands(
        audio,
        sample_rate,
        threshold_db=args.threshold_db,
        frame_ms=args.frame_ms,
        max_island_ms=args.max_island_ms,
        min_quiet_ms=args.min_quiet_ms,
    )

    output_path = None
    if not args.dry_run:
        cleaned = audio.copy()
        for island in islands:
            cleaned[int(island["start_sample"]) : int(island["end_sample"])] = 0.0
        output_path = args.output.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output_path, cleaned, sample_rate)

    print(
        json.dumps(
            {
                "input": str(input_path),
                "output": str(output_path) if output_path else None,
                "sample_rate": sample_rate,
                "threshold_db": args.threshold_db,
                "frame_ms": args.frame_ms,
                "max_island_ms": args.max_island_ms,
                "min_quiet_ms": args.min_quiet_ms,
                "removed_count": len(islands),
                "removed_duration_ms": round(
                    sum(float(item["duration_ms"]) for item in islands), 3
                ),
                "islands": islands,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
