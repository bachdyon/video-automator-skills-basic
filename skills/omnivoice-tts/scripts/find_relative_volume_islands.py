#!/usr/bin/env python3
"""Find audio islands whose peak is below a ratio of the file-wide peak."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf


def dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def boolean_runs(values: np.ndarray) -> list[tuple[bool, int, int]]:
    if values.size == 0:
        return []
    changes = np.flatnonzero(values[1:] != values[:-1]) + 1
    starts = np.concatenate(([0], changes))
    ends = np.concatenate((changes, [values.size]))
    return [(bool(values[start]), int(start), int(end)) for start, end in zip(starts, ends)]


def find_relative_islands(
    audio: np.ndarray,
    sample_rate: int,
    *,
    min_peak_ratio: float,
    max_peak_ratio: float,
    min_island_ms: float,
    min_quiet_before_ms: float,
    min_quiet_after_ms: float,
    silence_threshold_db: float,
    frame_ms: float,
) -> tuple[float, list[dict[str, float | int]]]:
    analysis = audio if audio.ndim == 1 else np.mean(audio, axis=1)
    global_peak = float(np.max(np.abs(analysis)))
    if global_peak <= 0:
        return 0.0, []

    frame_size = max(1, round(sample_rate * frame_ms / 1000.0))
    frame_count = math.ceil(len(analysis) / frame_size)
    padded = np.pad(analysis, (0, frame_count * frame_size - len(analysis)))
    frames = padded.reshape(frame_count, frame_size)
    frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    quiet = frame_rms < 10.0 ** (silence_threshold_db / 20.0)
    runs = boolean_runs(quiet)

    islands: list[dict[str, float | int]] = []
    for index in range(1, len(runs) - 1):
        is_quiet, start_frame, end_frame = runs[index]
        previous = runs[index - 1]
        following = runs[index + 1]
        if is_quiet or not previous[0] or not following[0]:
            continue

        start_sample = start_frame * frame_size
        end_sample = min(len(analysis), end_frame * frame_size)
        samples = analysis[start_sample:end_sample]
        duration_ms = 1000.0 * (end_sample - start_sample) / sample_rate
        if duration_ms < min_island_ms:
            continue
        quiet_before_ms = (previous[2] - previous[1]) * frame_ms
        quiet_after_ms = (following[2] - following[1]) * frame_ms
        if quiet_before_ms < min_quiet_before_ms:
            continue
        if quiet_after_ms < min_quiet_after_ms:
            continue
        peak = float(np.max(np.abs(samples)))
        peak_ratio = peak / global_peak
        if peak_ratio <= min_peak_ratio or peak_ratio >= max_peak_ratio:
            continue
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        islands.append(
            {
                "index": len(islands) + 1,
                "start_sample": start_sample,
                "end_sample": end_sample,
                "start_seconds": round(start_sample / sample_rate, 6),
                "end_seconds": round(end_sample / sample_rate, 6),
                "duration_ms": round(duration_ms, 3),
                "peak_ratio": round(peak_ratio, 6),
                "peak_percent": round(peak_ratio * 100.0, 3),
                "peak_dbfs": round(dbfs(peak), 3),
                "rms_dbfs": round(dbfs(rms), 3),
                "quiet_before_ms": round(quiet_before_ms, 3),
                "quiet_after_ms": round(quiet_after_ms, 3),
            }
        )
    return global_peak, islands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--min-peak-ratio", type=float, default=0.0)
    parser.add_argument("--max-peak-ratio", type=float, default=0.60)
    parser.add_argument("--min-island-ms", type=float, default=0.0)
    parser.add_argument("--min-quiet-before-ms", type=float, default=0.0)
    parser.add_argument("--min-quiet-after-ms", type=float, default=0.0)
    parser.add_argument("--silence-threshold-db", type=float, default=-36.0)
    parser.add_argument("--frame-ms", type=float, default=10.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument(
        "--zero-output",
        type=Path,
        help="Write a same-length copy with every reported island set to digital zero.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 0 <= args.min_peak_ratio < args.max_peak_ratio <= 1:
        raise SystemExit(
            "Peak ratios must satisfy 0 <= min-peak-ratio < max-peak-ratio <= 1."
        )
    if args.min_island_ms < 0:
        raise SystemExit("--min-island-ms cannot be negative.")
    if args.min_quiet_before_ms < 0 or args.min_quiet_after_ms < 0:
        raise SystemExit("Minimum quiet durations cannot be negative.")
    if args.frame_ms <= 0:
        raise SystemExit("--frame-ms must be positive.")

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input audio does not exist: {input_path}")
    audio, sample_rate = sf.read(input_path, always_2d=False, dtype="float32")
    global_peak, islands = find_relative_islands(
        audio,
        sample_rate,
        min_peak_ratio=args.min_peak_ratio,
        max_peak_ratio=args.max_peak_ratio,
        min_island_ms=args.min_island_ms,
        min_quiet_before_ms=args.min_quiet_before_ms,
        min_quiet_after_ms=args.min_quiet_after_ms,
        silence_threshold_db=args.silence_threshold_db,
        frame_ms=args.frame_ms,
    )
    report = {
        "input": str(input_path),
        "sample_rate": sample_rate,
        "duration_seconds": round(len(audio) / sample_rate, 6),
        "global_peak": round(global_peak, 8),
        "global_peak_dbfs": round(dbfs(global_peak), 3),
        "min_peak_ratio_exclusive": args.min_peak_ratio,
        "min_peak_percent_exclusive": args.min_peak_ratio * 100.0,
        "max_peak_ratio": args.max_peak_ratio,
        "max_peak_percent": args.max_peak_ratio * 100.0,
        "min_island_ms": args.min_island_ms,
        "min_quiet_before_ms": args.min_quiet_before_ms,
        "min_quiet_after_ms": args.min_quiet_after_ms,
        "silence_threshold_db": args.silence_threshold_db,
        "frame_ms": args.frame_ms,
        "minimum_quiet_frames_each_side": 1,
        "island_count": len(islands),
        "islands": islands,
    }

    if args.json_output:
        json_path = args.json_output.expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.csv_output:
        csv_path = args.csv_output.expanduser().resolve()
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = list(islands[0].keys()) if islands else [
                "index",
                "start_seconds",
                "end_seconds",
                "duration_ms",
                "peak_ratio",
                "peak_percent",
                "peak_dbfs",
                "rms_dbfs",
                "quiet_before_ms",
                "quiet_after_ms",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(islands)
    if args.zero_output:
        zero_path = args.zero_output.expanduser().resolve()
        if zero_path == input_path:
            raise SystemExit("--zero-output must not overwrite the input audio.")
        zero_path.parent.mkdir(parents=True, exist_ok=True)
        zeroed = audio.copy()
        for island in islands:
            zeroed[
                int(island["start_sample"]) : int(island["end_sample"])
            ] = 0.0
        sf.write(zero_path, zeroed, sample_rate, subtype=sf.info(input_path).subtype)

    summary = {key: value for key, value in report.items() if key != "islands"}
    summary["json_output"] = (
        str(args.json_output.expanduser().resolve()) if args.json_output else None
    )
    summary["csv_output"] = (
        str(args.csv_output.expanduser().resolve()) if args.csv_output else None
    )
    summary["zero_output"] = (
        str(args.zero_output.expanduser().resolve()) if args.zero_output else None
    )
    summary["zeroed_duration_seconds"] = round(
        sum(float(item["duration_ms"]) for item in islands) / 1000.0, 6
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
