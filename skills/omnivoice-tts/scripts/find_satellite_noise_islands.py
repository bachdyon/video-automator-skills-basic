#!/usr/bin/env python3
"""Find short, quiet satellite regions adjacent to longer speech regions."""

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


def active_runs(active: np.ndarray) -> list[tuple[int, int]]:
    if active.size == 0:
        return []
    changes = np.flatnonzero(active[1:] != active[:-1]) + 1
    starts = np.concatenate(([0], changes))
    ends = np.concatenate((changes, [active.size]))
    return [
        (int(start), int(end))
        for start, end in zip(starts, ends)
        if bool(active[start])
    ]


def merge_runs(
    runs: list[tuple[int, int]], max_gap_frames: int
) -> list[tuple[int, int]]:
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        previous_start, previous_end = merged[-1]
        if start - previous_end <= max_gap_frames:
            merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged


def component_metrics(
    analysis: np.ndarray,
    frame_rms: np.ndarray,
    active: np.ndarray,
    sample_rate: int,
    frame_size: int,
    start_frame: int,
    end_frame: int,
) -> dict[str, float | int]:
    start_sample = start_frame * frame_size
    end_sample = min(len(analysis), end_frame * frame_size)
    samples = analysis[start_sample:end_sample]
    active_levels = frame_rms[start_frame:end_frame][active[start_frame:end_frame]]
    active_rms = (
        float(np.sqrt(np.mean(np.square(active_levels, dtype=np.float64))))
        if active_levels.size
        else 0.0
    )
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    return {
        "start_frame": start_frame,
        "end_frame": end_frame,
        "start_sample": start_sample,
        "end_sample": end_sample,
        "start_seconds": start_sample / sample_rate,
        "end_seconds": end_sample / sample_rate,
        "duration_ms": 1000.0 * (end_sample - start_sample) / sample_rate,
        "peak": peak,
        "peak_dbfs": dbfs(peak),
        "active_rms": active_rms,
        "active_rms_dbfs": dbfs(active_rms),
    }


def find_satellites(
    audio: np.ndarray,
    sample_rate: int,
    *,
    silence_threshold_db: float,
    frame_ms: float,
    merge_gap_ms: float,
    main_min_ms: float,
    satellite_min_ms: float,
    satellite_max_ms: float,
    max_main_gap_ms: float,
    min_peak_ratio: float,
    max_peak_ratio: float,
    min_rms_difference_db: float,
    min_outer_quiet_ms: float,
) -> dict[str, object]:
    analysis = audio if audio.ndim == 1 else np.mean(audio, axis=1)
    frame_size = max(1, round(sample_rate * frame_ms / 1000.0))
    frame_count = math.ceil(len(analysis) / frame_size)
    padded = np.pad(analysis, (0, frame_count * frame_size - len(analysis)))
    frames = padded.reshape(frame_count, frame_size)
    frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    active = frame_rms >= 10.0 ** (silence_threshold_db / 20.0)
    raw_runs = active_runs(active)
    components = merge_runs(raw_runs, round(merge_gap_ms / frame_ms))
    metrics = [
        component_metrics(
            analysis,
            frame_rms,
            active,
            sample_rate,
            frame_size,
            start,
            end,
        )
        for start, end in components
    ]
    main_indices = [
        index
        for index, component in enumerate(metrics)
        if float(component["duration_ms"]) >= main_min_ms
    ]

    satellites: list[dict[str, object]] = []
    for index, candidate in enumerate(metrics):
        duration_ms = float(candidate["duration_ms"])
        if not satellite_min_ms <= duration_ms <= satellite_max_ms:
            continue
        nearest = None
        for main_index in main_indices:
            main = metrics[main_index]
            if int(candidate["end_sample"]) <= int(main["start_sample"]):
                side = "before"
                gap_ms = 1000.0 * (
                    int(main["start_sample"]) - int(candidate["end_sample"])
                ) / sample_rate
            elif int(candidate["start_sample"]) >= int(main["end_sample"]):
                side = "after"
                gap_ms = 1000.0 * (
                    int(candidate["start_sample"]) - int(main["end_sample"])
                ) / sample_rate
            else:
                continue
            if gap_ms > max_main_gap_ms:
                continue
            if nearest is None or gap_ms < nearest["gap_ms"]:
                nearest = {
                    "main_index": main_index,
                    "side": side,
                    "gap_ms": gap_ms,
                }
        if nearest is None:
            continue

        main = metrics[int(nearest["main_index"])]
        if nearest["side"] == "before":
            previous_end = int(metrics[index - 1]["end_sample"]) if index > 0 else 0
            outer_quiet_ms = 1000.0 * (
                int(candidate["start_sample"]) - previous_end
            ) / sample_rate
        else:
            next_start = (
                int(metrics[index + 1]["start_sample"])
                if index + 1 < len(metrics)
                else len(analysis)
            )
            outer_quiet_ms = 1000.0 * (
                next_start - int(candidate["end_sample"])
            ) / sample_rate
        if outer_quiet_ms < min_outer_quiet_ms:
            continue

        main_peak = float(main["peak"])
        peak_ratio = float(candidate["peak"]) / main_peak if main_peak > 0 else 0.0
        if not min_peak_ratio < peak_ratio < max_peak_ratio:
            continue
        rms_difference_db = float(main["active_rms_dbfs"]) - float(
            candidate["active_rms_dbfs"]
        )
        if rms_difference_db < min_rms_difference_db:
            continue

        satellites.append(
            {
                "index": len(satellites) + 1,
                "start_sample": int(candidate["start_sample"]),
                "end_sample": int(candidate["end_sample"]),
                "start_seconds": round(float(candidate["start_seconds"]), 6),
                "end_seconds": round(float(candidate["end_seconds"]), 6),
                "duration_ms": round(duration_ms, 3),
                "side_of_main": nearest["side"],
                "gap_to_main_ms": round(float(nearest["gap_ms"]), 3),
                "outer_quiet_ms": round(outer_quiet_ms, 3),
                "peak_ratio_to_main": round(peak_ratio, 6),
                "peak_percent_of_main": round(peak_ratio * 100.0, 3),
                "peak_dbfs": round(float(candidate["peak_dbfs"]), 3),
                "active_rms_dbfs": round(float(candidate["active_rms_dbfs"]), 3),
                "rms_difference_db": round(rms_difference_db, 3),
                "main_start_seconds": round(float(main["start_seconds"]), 6),
                "main_end_seconds": round(float(main["end_seconds"]), 6),
                "main_duration_ms": round(float(main["duration_ms"]), 3),
                "main_peak_dbfs": round(float(main["peak_dbfs"]), 3),
                "main_active_rms_dbfs": round(float(main["active_rms_dbfs"]), 3),
            }
        )

    return {
        "component_count": len(metrics),
        "main_count": len(main_indices),
        "satellites": satellites,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--silence-threshold-db", type=float, default=-36.0)
    parser.add_argument("--frame-ms", type=float, default=10.0)
    parser.add_argument("--merge-gap-ms", type=float, default=200.0)
    parser.add_argument("--main-min-ms", type=float, default=1000.0)
    parser.add_argument("--satellite-min-ms", type=float, default=10.0)
    parser.add_argument("--satellite-max-ms", type=float, default=800.0)
    parser.add_argument("--max-main-gap-ms", type=float, default=1500.0)
    parser.add_argument("--min-peak-ratio", type=float, default=0.20)
    parser.add_argument("--max-peak-ratio", type=float, default=0.60)
    parser.add_argument("--min-rms-difference-db", type=float, default=4.0)
    parser.add_argument("--min-outer-quiet-ms", type=float, default=100.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument(
        "--zero-output",
        type=Path,
        help="Write a same-length copy with every detected satellite set to zero.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 0 <= args.min_peak_ratio < args.max_peak_ratio <= 1:
        raise SystemExit("Peak ratios must satisfy 0 <= min < max <= 1.")
    positive_values = (
        args.frame_ms,
        args.main_min_ms,
        args.satellite_min_ms,
        args.satellite_max_ms,
        args.max_main_gap_ms,
    )
    if any(value <= 0 for value in positive_values):
        raise SystemExit("Frame and region durations must be positive.")
    if args.merge_gap_ms < 0 or args.min_outer_quiet_ms < 0:
        raise SystemExit("Gap and quiet durations cannot be negative.")

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input audio does not exist: {input_path}")
    audio, sample_rate = sf.read(input_path, always_2d=False, dtype="float32")
    result = find_satellites(
        audio,
        sample_rate,
        silence_threshold_db=args.silence_threshold_db,
        frame_ms=args.frame_ms,
        merge_gap_ms=args.merge_gap_ms,
        main_min_ms=args.main_min_ms,
        satellite_min_ms=args.satellite_min_ms,
        satellite_max_ms=args.satellite_max_ms,
        max_main_gap_ms=args.max_main_gap_ms,
        min_peak_ratio=args.min_peak_ratio,
        max_peak_ratio=args.max_peak_ratio,
        min_rms_difference_db=args.min_rms_difference_db,
        min_outer_quiet_ms=args.min_outer_quiet_ms,
    )
    satellites = list(result["satellites"])
    report = {
        "input": str(input_path),
        "sample_rate": sample_rate,
        "duration_seconds": round(len(audio) / sample_rate, 6),
        "parameters": {
            "silence_threshold_db": args.silence_threshold_db,
            "frame_ms": args.frame_ms,
            "merge_gap_ms": args.merge_gap_ms,
            "main_min_ms": args.main_min_ms,
            "satellite_min_ms": args.satellite_min_ms,
            "satellite_max_ms": args.satellite_max_ms,
            "max_main_gap_ms": args.max_main_gap_ms,
            "min_peak_ratio_exclusive": args.min_peak_ratio,
            "max_peak_ratio_exclusive": args.max_peak_ratio,
            "min_rms_difference_db": args.min_rms_difference_db,
            "min_outer_quiet_ms": args.min_outer_quiet_ms,
        },
        "component_count": result["component_count"],
        "main_count": result["main_count"],
        "satellite_count": len(satellites),
        "satellites": satellites,
    }
    if args.json_output:
        path = args.json_output.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.csv_output:
        path = args.csv_output.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = list(satellites[0].keys()) if satellites else [
                "index",
                "start_seconds",
                "end_seconds",
                "duration_ms",
                "side_of_main",
                "gap_to_main_ms",
                "outer_quiet_ms",
                "peak_percent_of_main",
                "rms_difference_db",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(satellites)
    zero_output = None
    if args.zero_output:
        path = args.zero_output.expanduser().resolve()
        if path == input_path:
            raise SystemExit("--zero-output must not overwrite the input audio.")
        path.parent.mkdir(parents=True, exist_ok=True)
        zeroed = audio.copy()
        for satellite in satellites:
            zeroed[
                int(satellite["start_sample"]) : int(satellite["end_sample"])
            ] = 0.0
        sf.write(path, zeroed, sample_rate, subtype=sf.info(input_path).subtype)
        zero_output = str(path)
    summary = {key: value for key, value in report.items() if key != "satellites"}
    summary["zero_output"] = zero_output
    summary["zeroed_duration_ms"] = round(
        sum(float(item["duration_ms"]) for item in satellites), 3
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
