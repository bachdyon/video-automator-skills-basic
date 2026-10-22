---
name: voice-manager
description: Manage a scalable local registry of reusable named voice profiles across TTS engines. Use when the user asks to save or name a cloned voice, list available voices, inspect or validate voice references and consent metadata, synthesize speech by a stable voice name, or organize multiple future OmniVoice and other local TTS voices.
---

# Voice Manager

Manage named voice profiles through the bundled registry script. Keep voice data separate from skill code under `voice_profiles/<engine>/<voice-id>/`.

## Required behavior

- Require explicit confirmation that the user owns or is authorized to clone a voice before adding it.
- Never use a cloned profile for impersonation, fraud, or misleading attribution.
- Store authorization context in `profile.toml`.
- Keep `voice_profiles/` Git-ignored because reference recordings are biometric data.
- Use stable ASCII voice names such as `Socolive`, `GiongNamNews`, or `voice-female-01`.
- Delegate engine-specific cloning and synthesis to that engine's skill. For OmniVoice, load and follow `$omnivoice-tts`.
- Never delete or overwrite a profile unless the user explicitly asks. Use `--replace` only after resolving the exact target.

## Registry layout

```text
voice_profiles/
├── omnivoice/
│   └── socolive/
│       ├── profile.toml
│       ├── reference.txt
│       └── reference.wav
└── <future-engine>/
    └── <voice-id>/
```

Read [profile-schema.md](references/profile-schema.md) when adding a new engine adapter or changing profile metadata.

## Commands

List all profiles:

```bash
python3 skills/voice-manager/scripts/voice_manager.py list
```

Show one profile:

```bash
python3 skills/voice-manager/scripts/voice_manager.py show Socolive
```

Validate one profile or the entire registry:

```bash
python3 skills/voice-manager/scripts/voice_manager.py validate --voice Socolive
python3 skills/voice-manager/scripts/voice_manager.py validate
```

Treat `valid: true` as a structural and technical health check: required metadata and authorization context exist, paths stay inside the profile, the transcript is non-empty, the checksum matches, audio is decodable, and engine-specific format constraints pass. It does not prove perceptual voice quality, transcript-to-audio agreement, low noise, or absence of clipping; listen to a generated sample before approving a voice for production.

Add an authorized OmniVoice profile:

```bash
python3 skills/voice-manager/scripts/voice_manager.py add \
  --engine omnivoice \
  --name Socolive \
  --ref-audio input/reference.wav \
  --ref-text-file input/reference.txt \
  --source-url "https://example.com/source" \
  --authorization-note "User confirmed authorization in the current task." \
  --authorized
```

Synthesize by stable voice name:

```bash
python3 skills/voice-manager/scripts/voice_manager.py synthesize \
  --voice Socolive \
  --text-file jobs/<job_id>/source/narration.txt \
  --language Vietnamese \
  --output jobs/<job_id>/source/voice.wav \
  --offline
```

Pass `--language English` or another OmniVoice-supported language to override the profile's default language for one synthesis without duplicating the voice profile.

## Adding another TTS engine

1. Give the engine its own directory under `voice_profiles/`.
2. Keep the common metadata fields in the schema reference.
3. Add dispatch branches to `add_profile()` and `synthesize()` in the manager script.
4. Delegate actual inference to the engine-specific skill instead of importing its runtime into Voice Manager.
5. Add a synthetic profile test and validate the full registry.
