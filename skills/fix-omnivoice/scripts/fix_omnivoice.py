#!/usr/bin/env python3
"""Two-pass, sample-preserving cleanup for OmniVoice PCM WAV output."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import wave

import numpy as np


def amplitude_dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1.0 / 32768.0))


def find_long_quiet_runs(
    samples: np.ndarray,
    threshold: int,
    minimum_samples: int,
) -> list[tuple[int, int]]:
    loud = np.flatnonzero(np.abs(samples.astype(np.int32)) > threshold)
    if loud.size == 0:
        return [(0, len(samples))]

    quiet: list[tuple[int, int]] = []
    if int(loud[0]) >= minimum_samples:
        quiet.append((0, int(loud[0])))

    gap_indices = np.flatnonzero(np.diff(loud) - 1 >= minimum_samples)
    for index in gap_indices:
        quiet.append((int(loud[index]) + 1, int(loud[index + 1])))

    final_start = int(loud[-1]) + 1
    if len(samples) - final_start >= minimum_samples:
        quiet.append((final_start, len(samples)))
    return quiet


def find_clusters(
    samples: np.ndarray,
    sample_rate: int,
    *,
    threshold_db: float,
    minimum_quiet_ms: float,
    minimum_outer_quiet_ms: float,
    minimum_cluster_ms: float,
    maximum_cluster_ms: float,
    maximum_peak_db: float,
) -> list[dict[str, float | int]]:
    threshold = round(32768.0 * 10.0 ** (threshold_db / 20.0))
    minimum_quiet = round(minimum_quiet_ms * sample_rate / 1000.0)
    minimum_outer_quiet = round(minimum_outer_quiet_ms * sample_rate / 1000.0)
    minimum_cluster = round(minimum_cluster_ms * sample_rate / 1000.0)
    maximum_cluster = round(maximum_cluster_ms * sample_rate / 1000.0)
    quiet_runs = find_long_quiet_runs(samples, threshold, minimum_quiet)
    clusters: list[dict[str, float | int]] = []

    for index in range(len(quiet_runs) - 1):
        quiet_before = quiet_runs[index]
        quiet_after = quiet_runs[index + 1]
        start = quiet_before[1]
        end = quiet_after[0]
        length = end - start
        if not minimum_cluster <= length <= maximum_cluster:
            continue

        before_length = quiet_before[1] - quiet_before[0]
        after_length = quiet_after[1] - quiet_after[0]
        before_ok = before_length >= minimum_outer_quiet or quiet_before[0] == 0
        after_ok = after_length >= minimum_outer_quiet or quiet_after[1] == len(samples)
        if not (before_ok and after_ok):
            continue

        segment = samples[start:end].astype(np.float32) / 32768.0
        peak = float(np.max(np.abs(segment))) if segment.size else 0.0
        peak_db = amplitude_dbfs(peak)
        if peak_db > maximum_peak_db:
            continue

        clusters.append(
            {
                "start_sample": start,
                "end_sample": end,
                "start_seconds": round(start / sample_rate, 6),
                "end_seconds": round(end / sample_rate, 6),
                "duration_ms": round(length * 1000.0 / sample_rate, 3),
                "peak_dbfs": round(peak_db, 3),
                "quiet_before_ms": round(before_length * 1000.0 / sample_rate, 3),
                "quiet_after_ms": round(after_length * 1000.0 / sample_rate, 3),
            }
        )
    return clusters


def apply_clusters(samples: np.ndarray, clusters: list[dict[str, float | int]]) -> None:
    for cluster in clusters:
        samples[int(cluster["start_sample"]) : int(cluster["end_sample"])] = 0


def cluster_mask(
    sample_count: int,
    stages: list[list[dict[str, float | int]]],
) -> np.ndarray:
    mask = np.zeros(sample_count, dtype=bool)
    for clusters in stages:
        for cluster in clusters:
            mask[int(cluster["start_sample"]) : int(cluster["end_sample"])] = True
    return mask


def region_count(mask: np.ndarray) -> int:
    transitions = np.diff(np.r_[False, mask, False].astype(np.int8))
    return int(np.count_nonzero(transitions == 1))


def derived_output(input_path: Path) -> Path:
    if input_path.stem.endswith("_corrected"):
        return input_path.with_name(f"{input_path.stem}_fixed.wav")
    return input_path.with_name(f"{input_path.stem}_corrected.wav")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean isolated OmniVoice artifacts without changing timing."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--first-threshold-db", type=float, default=-50.0)
    parser.add_argument("--second-threshold-db", type=float, default=-55.0)
    parser.add_argument("--minimum-quiet-ms", type=float, default=80.0)
    parser.add_argument("--minimum-outer-quiet-ms", type=float, default=150.0)
    parser.add_argument("--minimum-cluster-ms", type=float, default=10.0)
    parser.add_argument("--first-maximum-cluster-ms", type=float, default=450.0)
    parser.add_argument("--second-maximum-cluster-ms", type=float, default=500.0)
    parser.add_argument("--maximum-peak-db", type=float, default=-22.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input WAV does not exist: {input_path}")

    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else derived_output(input_path)
    )
    report_path = (
        args.report.expanduser().resolve()
        if args.report
        else output_path.with_name(f"{output_path.stem}_report.json")
    )
    if output_path == input_path:
        raise SystemExit("Refusing to overwrite the original WAV.")

    with wave.open(str(input_path), "rb") as source:
        params = source.getparams()
        if params.nchannels != 1 or params.sampwidth != 2 or params.comptype != "NONE":
            raise SystemExit("Expected uncompressed mono 16-bit PCM WAV input.")
        original = np.frombuffer(
            source.readframes(params.nframes), dtype="<i2"
        ).copy()

    common = {
        "sample_rate": params.framerate,
        "minimum_quiet_ms": args.minimum_quiet_ms,
        "minimum_outer_quiet_ms": args.minimum_outer_quiet_ms,
        "minimum_cluster_ms": args.minimum_cluster_ms,
        "maximum_peak_db": args.maximum_peak_db,
    }
    corrected = original.copy()
    stage1 = find_clusters(
        corrected,
        threshold_db=args.first_threshold_db,
        maximum_cluster_ms=args.first_maximum_cluster_ms,
        **common,
    )
    apply_clusters(corrected, stage1)
    stage2 = find_clusters(
        corrected,
        threshold_db=args.second_threshold_db,
        maximum_cluster_ms=args.second_maximum_cluster_ms,
        **common,
    )
    apply_clusters(corrected, stage2)
    mask = cluster_mask(len(original), [stage1, stage2])
    verified_audio = corrected
    params_match = True
    if not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as output:
            output.setparams(params)
            output.writeframes(corrected.astype("<i2", copy=False).tobytes())
        with wave.open(str(output_path), "rb") as written:
            params_match = written.getparams() == params
            verified_audio = np.frombuffer(
                written.readframes(written.getnframes()), dtype="<i2"
            ).copy()

    residual = find_clusters(
        verified_audio,
        threshold_db=args.second_threshold_db,
        maximum_cluster_ms=args.second_maximum_cluster_ms,
        **common,
    )
    outside_changed = int(
        np.count_nonzero(original[~mask] != verified_audio[~mask])
    )
    inside_nonzero = int(np.count_nonzero(verified_audio[mask]))
    valid = (
        outside_changed == 0
        and inside_nonzero == 0
        and len(residual) == 0
        and params_match
    )

    report = {
        "input": str(input_path),
        "output": None if args.dry_run else str(output_path),
        "sample_rate": params.framerate,
        "duration_seconds": round(params.nframes / params.framerate, 6),
        "parameters": {
            "first_threshold_db": args.first_threshold_db,
            "second_threshold_db": args.second_threshold_db,
            "minimum_quiet_ms": args.minimum_quiet_ms,
            "minimum_outer_quiet_ms": args.minimum_outer_quiet_ms,
            "minimum_cluster_ms": args.minimum_cluster_ms,
            "first_maximum_cluster_ms": args.first_maximum_cluster_ms,
            "second_maximum_cluster_ms": args.second_maximum_cluster_ms,
            "maximum_peak_db": args.maximum_peak_db,
        },
        "stage1": {
            "cluster_count": len(stage1),
            "clusters": stage1,
        },
        "stage2": {
            "cluster_count": len(stage2),
            "clusters": stage2,
        },
        "summary": {
            "unique_region_count": region_count(mask),
            "muted_duration_ms": round(float(mask.sum()) * 1000.0 / params.framerate, 3),
            "nonzero_samples_removed": int(np.count_nonzero(original[mask])),
        },
        "verification": {
            "wav_params_match": params_match,
            "outside_changed_samples": outside_changed,
            "inside_nonzero_samples": inside_nonzero,
            "residual_cluster_count": len(residual),
            "valid": valid,
        },
    }

    if not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False))
    if not valid:
        raise SystemExit("Fix OmniVoice verification failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
