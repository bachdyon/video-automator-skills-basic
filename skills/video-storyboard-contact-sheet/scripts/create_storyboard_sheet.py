#!/usr/bin/env python3
"""Create one labeled storyboard/contact-sheet image from a finished video."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as exc:
    raise SystemExit(
        "Pillow is required. Run this script with the repository .venv or install Pillow."
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export representative video stills onto one flat storyboard canvas."
    )
    parser.add_argument("input", type=Path, help="Input video readable by FFmpeg.")
    parser.add_argument("--output", type=Path, help="Output .png, .jpg, or .jpeg path.")
    parser.add_argument("--frames", type=int, default=12, help="Uniform still count.")
    parser.add_argument("--columns", type=int, default=4, help="Storyboard columns.")
    parser.add_argument("--canvas-width", type=int, default=1920, help="Canvas width in pixels.")
    parser.add_argument("--times", help="Comma-separated timestamps in seconds; overrides --frames.")
    parser.add_argument("--start", type=float, default=0.0, help="Sampling range start in seconds.")
    parser.add_argument("--end", type=float, help="Sampling range end in seconds.")
    parser.add_argument("--title", help="Header title; defaults to the video filename.")
    parser.add_argument("--background", default="#d8d3c8", help="Canvas background color.")
    parser.add_argument("--card-background", default="#f4f0e6", help="Cell and header color.")
    parser.add_argument("--label-background", default="#111111", help="Label strip color.")
    parser.add_argument("--label-color", default="#f7f3e8", help="Label text color.")
    parser.add_argument("--accent", default="#cb2733", help="Shot-number accent color.")
    parser.add_argument("--gap", type=int, default=18, help="Gap between cells.")
    parser.add_argument("--margin", type=int, default=24, help="Outer canvas margin.")
    parser.add_argument("--no-labels", action="store_true", help="Hide shot/timestamp strips.")
    parser.add_argument("--no-header", action="store_true", help="Hide title and metadata header.")
    parser.add_argument("--jpeg-quality", type=int, default=92, help="JPEG quality from 1 to 100.")
    return parser.parse_args()


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Required binary not found on PATH: {name}")


def probe_video(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise SystemExit("The input has no decodable video stream.")
    stream = streams[0]
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise SystemExit("Could not determine a positive video duration.")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": stream.get("r_frame_rate", "unknown"),
        "duration": duration,
    }


def parse_times(raw: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise SystemExit("--times must contain comma-separated seconds.") from exc
    if not values:
        raise SystemExit("--times did not contain any timestamps.")
    if any(value < 0 for value in values):
        raise SystemExit("--times cannot contain negative timestamps.")
    if values != sorted(values):
        raise SystemExit("--times must be in chronological order.")
    return values


def choose_times(args: argparse.Namespace, duration: float) -> tuple[list[float], str]:
    end = duration if args.end is None else args.end
    if args.start < 0 or end <= args.start or end > duration + 0.001:
        raise SystemExit(
            f"Invalid range {args.start:.3f}–{end:.3f}; video duration is {duration:.3f}s."
        )
    if args.times:
        times = parse_times(args.times)
        if times[0] < args.start or times[-1] > end:
            raise SystemExit("At least one --times value falls outside --start/--end.")
        return times, "manual"
    if args.frames < 1:
        raise SystemExit("--frames must be at least 1.")
    span = end - args.start
    times = [args.start + span * (index + 0.5) / args.frames for index in range(args.frames)]
    return times, "uniform"


def format_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining:04.1f}"


def find_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def extract_frame(video: Path, timestamp: float, output: Path, width: int, height: int) -> None:
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{timestamp:.6f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        vf,
        str(output),
    ]
    subprocess.run(command, check=True)
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"FFmpeg did not create a frame at {timestamp:.3f}s.")


def main() -> int:
    args = parse_args()
    require_binary("ffmpeg")
    require_binary("ffprobe")

    video = args.input.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"Input video does not exist: {video}")
    if args.columns < 1 or args.canvas_width < 320 or args.margin < 0 or args.gap < 0:
        raise SystemExit("Invalid columns, canvas width, margin, or gap.")

    output = (
        args.output.expanduser().resolve()
        if args.output
        else video.with_name(f"{video.stem}_storyboard.png")
    )
    if output.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise SystemExit("Output extension must be .png, .jpg, or .jpeg.")
    output.parent.mkdir(parents=True, exist_ok=True)

    metadata = probe_video(video)
    timestamps, sampling_mode = choose_times(args, metadata["duration"])
    count = len(timestamps)
    columns = min(args.columns, count)
    rows = math.ceil(count / columns)

    inner_width = args.canvas_width - 2 * args.margin - (columns - 1) * args.gap
    if inner_width <= columns * 100:
        raise SystemExit("Canvas is too narrow for the selected columns/margins/gaps.")
    cell_width = inner_width // columns
    frame_height = round(cell_width * metadata["height"] / metadata["width"])
    label_height = 0 if args.no_labels else max(42, round(cell_width * 0.085))
    cell_height = frame_height + label_height
    header_height = 0 if args.no_header else max(104, round(args.canvas_width * 0.07))
    canvas_height = (
        2 * args.margin + header_height + rows * cell_height + (rows - 1) * args.gap
    )

    canvas = Image.new("RGB", (args.canvas_width, canvas_height), args.background)
    draw = ImageDraw.Draw(canvas)
    title_font = find_font(max(28, round(args.canvas_width * 0.022)), bold=True)
    meta_font = find_font(max(17, round(args.canvas_width * 0.011)))
    label_font = find_font(max(17, round(cell_width * 0.038)), bold=True)

    if not args.no_header:
        x0 = args.margin
        y0 = args.margin
        x1 = args.canvas_width - args.margin
        y1 = args.margin + header_height - args.gap
        draw.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=args.card_background)
        title = args.title or video.name
        draw.text((x0 + 24, y0 + 18), title, font=title_font, fill="#111111")
        detail = (
            f"{metadata['width']}×{metadata['height']}  •  "
            f"{format_time(metadata['duration'])}  •  "
            f"{count} stills  •  {sampling_mode} sampling"
        )
        draw.text((x0 + 24, y0 + 62), detail, font=meta_font, fill="#55514b")

    with tempfile.TemporaryDirectory(prefix="storyboard-stills-") as temp_dir:
        temp_path = Path(temp_dir)
        for index, timestamp in enumerate(timestamps):
            frame_path = temp_path / f"frame-{index:03d}.png"
            extract_frame(video, timestamp, frame_path, cell_width, frame_height)
            with Image.open(frame_path) as raw_frame:
                frame = ImageOps.exif_transpose(raw_frame).convert("RGB")

            row, column = divmod(index, columns)
            x = args.margin + column * (cell_width + args.gap)
            y = args.margin + header_height + row * (cell_height + args.gap)
            canvas.paste(frame, (x, y))

            if not args.no_labels:
                draw.rectangle(
                    (x, y + frame_height, x + cell_width, y + cell_height),
                    fill=args.label_background,
                )
                shot = f"{index + 1:02d}"
                label_y = y + frame_height + (label_height - label_font.size) // 2 - 2
                draw.text((x + 16, label_y), shot, font=label_font, fill=args.accent)
                time_text = format_time(timestamp)
                bbox = draw.textbbox((0, 0), time_text, font=label_font)
                draw.text(
                    (x + cell_width - (bbox[2] - bbox[0]) - 16, label_y),
                    time_text,
                    font=label_font,
                    fill=args.label_color,
                )

    save_kwargs: dict[str, object] = {}
    if output.suffix.lower() in {".jpg", ".jpeg"}:
        save_kwargs = {"quality": max(1, min(args.jpeg_quality, 100)), "optimize": True}
    canvas.save(output, **save_kwargs)

    result = {
        "input": str(video),
        "output": str(output),
        "video_duration_seconds": round(metadata["duration"], 3),
        "video_resolution": [metadata["width"], metadata["height"]],
        "sampling_mode": sampling_mode,
        "timestamps_seconds": [round(value, 3) for value in timestamps],
        "stills": count,
        "columns": columns,
        "rows": rows,
        "canvas_resolution": [args.canvas_width, canvas_height],
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Media command failed with exit code {exc.returncode}.") from exc
