---
name: video-storyboard-contact-sheet
description: Convert a finished video into a single flat storyboard/contact-sheet image containing evenly sampled or manually timed still frames, optional timestamps, shot numbers, title, and video metadata. Use when the user asks to export video stills onto one canvas, make a storyboard sheet, contact sheet, frame overview, visual QA board, or a single image summarizing an MP4, MOV, WebM, MKV, or other FFmpeg-readable video.
---

# Video Storyboard Contact Sheet

Use the bundled script to turn one finished video into one PNG or JPEG canvas. Prefer PNG for review and archival; use JPEG only when file size matters.

## Requirements

- Require `ffmpeg` and `ffprobe` on `PATH`.
- Run with a Python environment containing Pillow. Prefer repo-root `.venv/bin/python`.
- Never modify the input video.

## Default workflow

1. Resolve the exact input video and confirm it exists.
2. Choose representative timestamps:
   - Use uniform sampling by default.
   - Use `--times` when scene boundaries or approved review frames are already known.
   - Sample frame centers, not the exact first or last frame, to avoid blank transitions.
3. Generate one canvas with `scripts/create_storyboard_sheet.py`.
4. Verify the result visually. Check frame order, aspect ratio, labels, clipping, and empty/duplicate frames.
5. Return both the storyboard image and its absolute path.

## Quick start

```bash
.venv/bin/python skills/video-storyboard-contact-sheet/scripts/create_storyboard_sheet.py \
  path/to/final_video.mp4 \
  --output path/to/final_video_storyboard.png
```

The default layout uses 12 uniformly sampled stills, 4 columns, a 1920-pixel-wide canvas, timestamps, shot numbers, a title strip, and neutral review colors.

## Useful options

Choose density and canvas layout:

```bash
.venv/bin/python skills/video-storyboard-contact-sheet/scripts/create_storyboard_sheet.py \
  path/to/video.mp4 \
  --output path/to/storyboard.png \
  --frames 16 \
  --columns 4 \
  --canvas-width 2400
```

Use exact timestamps in seconds:

```bash
.venv/bin/python skills/video-storyboard-contact-sheet/scripts/create_storyboard_sheet.py \
  path/to/video.mp4 \
  --output path/to/storyboard.png \
  --times "1.2,5.8,11.2,17.8,21,25.5"
```

Limit sampling to a range:

```bash
.venv/bin/python skills/video-storyboard-contact-sheet/scripts/create_storyboard_sheet.py \
  path/to/video.mp4 \
  --start 30 \
  --end 120 \
  --frames 12
```

Create a clean board without labels:

```bash
.venv/bin/python skills/video-storyboard-contact-sheet/scripts/create_storyboard_sheet.py \
  path/to/video.mp4 \
  --no-labels \
  --no-header
```

## Output rules

- Preserve the video frame aspect ratio inside every cell; never stretch stills.
- Keep frames in chronological reading order from left to right, then top to bottom.
- Use identical frame boxes and gaps across the sheet.
- Label time as `HH:MM:SS.s` and number frames from `01`.
- Include filename, duration, resolution, frame count, and sampling mode in the header unless `--no-header` is used.
- Fail clearly when the video cannot be probed, a requested timestamp falls outside the selected range, or Pillow/FFmpeg is unavailable.
- Use a temporary directory for extracted stills and remove it automatically.

## Visual verification

Open the produced image and confirm:

- all cells contain a decoded frame;
- no important content is cropped by the cell;
- timestamps increase monotonically;
- the sheet is a single image, not an image sequence;
- text remains readable at normal viewing size.

If multiple adjacent stills are visually identical, rerun with exact `--times` derived from scene boundaries rather than increasing the frame count.
