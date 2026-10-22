# Voice profile schema

Each profile is one directory at `voice_profiles/<engine>/<voice-id>/`.

Required `profile.toml` fields:

```toml
schema_version = 1
id = "socolive"
name = "Socolive"
engine = "omnivoice"
model = "k2-fsa/OmniVoice"
language = "Vietnamese"
reference_audio = "reference.wav"
reference_text = "reference.txt"
reference_sha256 = "<sha256 of normalized reference audio>"
num_step = 16
speed = 1.0
created_at = "<ISO-8601 UTC timestamp>"
authorization_confirmed = true
authorization_note = "<concise confirmation context>"
source_url = "<source URL when applicable>"
```

Rules:

- Resolve `reference_audio` and `reference_text` relative to the profile directory.
- Keep both paths inside the profile directory.
- Normalize OmniVoice references to mono PCM WAV at 24 kHz.
- Preserve Vietnamese diacritics in the transcript.
- Treat `id` as the stable machine identifier and `name` as the display name.
- Record the engine and model so profiles are not silently used by incompatible runtimes.
- Verify `reference_sha256` when validating or transferring a profile.
- Keep authorization metadata with the profile when backing it up.
