---
name: fix-omnivoice
description: Clean isolated low-volume artifacts, satellite sounds, and sub-threshold tails from OmniVoice-generated PCM WAV files while preserving duration and every sample outside the detected regions. Use after every OmniVoice TTS synthesis by default, when a user asks for corrected/clean OmniVoice output, or when generated speech contains occasional short sounds inside otherwise quiet pauses.
---

# Fix OmniVoice

Create a separate corrected WAV from an OmniVoice-generated original. Never overwrite the original unless the user explicitly requests it.

## Run

Use the deterministic two-pass cleaner:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/fix-omnivoice/scripts/fix_omnivoice.py \
  --input jobs/<job_id>/source/voice.wav \
  --output jobs/<job_id>/source/voice_corrected.wav \
  --report jobs/<job_id>/source/voice_corrected_report.json
```

Defaults implement the validated cleanup:

1. Detect isolated low-volume clusters at `-50 dBFS`.
2. Replace those clusters with digital zero without removing time.
3. Detect residual tails on the corrected signal at `-55 dBFS`.
4. Replace those tails with digital zero.
5. Verify that no sample outside the union of detected regions changed.
6. Run a final `-55 dBFS` residual scan and fail if candidates remain.

## Required behavior

- Accept mono 16-bit PCM WAV input, the native OmniVoice output format.
- Preserve sample rate, channel count, frame count, duration, and WAV parameters.
- Preserve the original file and write the corrected file separately.
- Write the JSON audit report next to the corrected file.
- Treat the result as valid only when:
  - `outside_changed_samples` is `0`;
  - `inside_nonzero_samples` is `0`;
  - `residual_cluster_count` is `0`;
  - input and output WAV parameters match.
- Do not use a whole-track noise gate. It can remove quiet consonants and breath detail.
- Do not reuse timestamps from a different synthesis. Detect regions on each newly generated WAV.

## OmniVoice integration

`$omnivoice-tts` invokes this skill automatically after successful synthesis. Its normal contract is:

```text
requested output: voice.wav
automatic corrected output: voice_corrected.wav
automatic report: voice_corrected_report.json
```

Use `--skip-fix-omnivoice` only when the user explicitly requests raw output only or when debugging the synthesizer.

If the requested output already ends in `_corrected.wav`, derive the corrected sibling as `<stem>_fixed.wav` to avoid overwriting the original.
