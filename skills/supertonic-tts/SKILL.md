---
name: supertonic-tts
description: Generate local multilingual text-to-speech audio with Supertonic 3 and ONNX Runtime, especially Vietnamese WAV narration without an API key or GPU. Use when the user explicitly requests Supertonic, wants private/offline/local TTS, needs a reusable cached model, or wants to inspect/download Supertonic models and preset voices.
---

# Supertonic TTS

Generate 44.1 kHz WAV audio locally with the bundled CLI wrapper. Use `supertonic-3` by default because it supports Vietnamese and 30 other languages.

## Required behavior

- Run with the repository `.venv/bin/python` when available.
- Store models in the shared, Git-ignored cache `.cache/supertonic/<model>/`.
- Let the wrapper download a model only when required files are missing. Reuse the existing model directory on later calls.
- Do not delete or redownload a valid cache unless the user explicitly requests it.
- Expect CPU inference. Do not require CUDA or a GPU.
- Preserve Vietnamese diacritics in input text.
- Write generated audio to a stable job path such as `jobs/<job_id>/source/voice.wav` when working inside a video job.
- Use the repository Voice Rule instead of this skill for Threads Video and screenshot/commentary jobs unless the user explicitly asks for Supertonic.

## Synthesize

Use the wrapper instead of rewriting the SDK call:

```bash
.venv/bin/python skills/supertonic-tts/scripts/supertonic_tts.py synthesize \
  --text "Xin chào. Đây là giọng đọc được tạo bằng Supertonic." \
  --lang vi \
  --voice F1 \
  --output source/voice.wav
```

For longer text, pass a UTF-8 file:

```bash
.venv/bin/python skills/supertonic-tts/scripts/supertonic_tts.py synthesize \
  --text-file jobs/<job_id>/source/narration.txt \
  --lang vi \
  --voice F1 \
  --output jobs/<job_id>/source/voice.wav
```

Useful options:

- `--voice F1`: preset `F1`–`F5` or `M1`–`M5`.
- `--voice-style path/to/custom.json`: use a Voice Builder style JSON instead of a preset.
- `--speed 1.05`: valid range `0.7`–`2.0`.
- `--steps 8`: quality/compute tradeoff; normally use `5`–`12`.
- `--model supertonic-3`: multilingual model and default.
- `--model-dir <path>`: override the shared repo cache.
- `--no-download`: fail instead of downloading when the model is absent.

## Inspect cache and voices

Check cache state without loading or downloading the model:

```bash
.venv/bin/python skills/supertonic-tts/scripts/supertonic_tts.py status
```

List preset voices. This initializes the model and therefore downloads it if missing:

```bash
.venv/bin/python skills/supertonic-tts/scripts/supertonic_tts.py list-voices
```

## Dependency recovery

The repository `.venv` should contain `supertonic`. If import fails, install the pinned compatible range once and retry:

```bash
.venv/bin/pip install -r skills/supertonic-tts/scripts/requirements.txt
```

If network or sandbox policy blocks either package or model download, request the required permission and rerun the same command. Do not substitute another TTS provider when the user explicitly selected Supertonic.
