# Project Agent Instructions

If `AGENTS.customs.md` exists at the repository root, read it immediately after this file. When the two files conflict, `AGENTS.customs.md` wins.

This repository keeps reusable project skills in `skills/<skill>/SKILL.md`.
Official third-party agent skills installed by the `skills` CLI live in `.agents/skills/<skill>/SKILL.md`.
User-made skills and tools live in `customs/` (see the Customs Rule).

## Customs Rule

When the user asks to create or change a skill or tool, write it under `customs/skills/<name>/` or `customs/tools/<name>/`. Never edit official files in `skills/`, `tools/`, `packages/`, or `.agents/skills/` for a user customization; upgrades overwrite them.

- To customize an official item, copy it into `customs/` under the same name and edit the copy. A customs item with the same name overrides the official one.
- Resolve names customs-first: `customs/skills/<name>/SKILL.md`, then `skills/<name>/SKILL.md`, then `.agents/skills/<name>/SKILL.md`.
- After creating or changing a customs item, add or update exactly one line for it under `## Customs registry` in `AGENTS.customs.md`, for example `- $my-skill → customs/skills/my-skill/ — short description`. Mark overrides with `(overrides official)`.
- If `AGENTS.customs.md` does not exist, create it with this first line: `This file overrides AGENTS.md wherever they conflict.`, followed by a `## Customs registry` section.
- Never put secrets or API keys in `customs/` or `AGENTS.customs.md`; keep them in `.env`.

## Edition Rule

`VERSION` states which edition is installed (`basic` or `premium`).

- If the user asks for a skill or tool that is not in this checkout or in `customs/`, say that it is part of VAS Premium. Do not rebuild it unless the user explicitly asks for their own version in `customs/`.
- If the user asks to install a ZIP from the VAS course other than the Premium upgrade, say it needs VAS Premium; do not unzip it by hand.
- When the user asks to upgrade to Premium, or to update Premium, with a ZIP file, run `python3 scripts/vas.py upgrade <path-to-zip>` once and report its doctor summary. Do not unzip or copy files by hand. If the doctor reports FAIL, offer `python3 scripts/vas.py upgrade --rollback`.
- To check that an installation works, run `python3 scripts/vas.py doctor`.

## Installation Rule

When the user asks you to install VAS, set up only the core so they can start right away; everything else installs the first time a feature needs it (see the Dependency Rule).

1. VAS must sit directly in the folder the user opened: `AGENTS.md`, `skills/`, and `scripts/` belong at its top level. If cloning or unzipping created an intermediate folder (for example `video-automator-skills-basic/` or `vas-premium-<version>/`), move everything, including hidden files such as `.git`, `.agents`, `.claude`, and `.vas`, up into the opened folder and remove the empty intermediate folder before continuing. If the opened folder is not empty and `git clone <url> .` refuses, use `git init`, `git remote add origin <url>`, and `git pull origin main` instead.
   If you extracted a ZIP, run `python3 scripts/vas.py repair` afterwards to restore the skill links the ZIP tool may have turned into plain files.
2. Make sure Python 3.11 or newer is available, installing it with the platform's usual installer if needed (Homebrew on macOS, winget on Windows, the system package manager on Linux). Ask the user before anything that needs administrator rights or a password; never type a password yourself.
3. If `.env` does not exist, copy `env.example` to `.env`. Never fill in API keys yourself or ask the user to paste a key into the chat; tell them which key a feature needs and let them edit `.env`.
4. Run `python3 scripts/vas.py doctor` and fix every `FAIL` line. `INFO` lines marked "installed the first time a feature needs it" and `WARN` lines are expected at this point.
5. Do not install Node.js, Remotion libraries, Python packages, or voice models now.

When no `FAIL` remains, reply with exactly one word: `Sẵn sàng`. If something still fails, do not say `Sẵn sàng`; explain in plain language what is missing and what the user can do.

## Dependency Rule

Install a dependency only when the current task needs it and it is missing, then continue the task. Install nothing for features the user is not using. Before running a skill for the first time, read the requirements in its `SKILL.md` (and its `scripts/requirements.txt` if present) to know what it needs. Ask before anything that needs administrator rights or a password.

If you cannot install something yourself (no permission, a password or administrator prompt, an unsupported system, or the install keeps failing), stop and tell the user in plain language what to install and how, step by step, then wait. Do not switch to a different tool or a lower-quality workaround without saying so.

- Video rendering with Remotion: Node.js 18 or newer, then `npm install` once in the repository root.
- Audio or video processing: `ffmpeg` and `ffprobe` through the platform's usual installer.
- A skill's Python packages: create `.venv` with `python3 -m venv .venv` if it does not exist, then install that skill's `scripts/requirements.txt` (or the packages its `SKILL.md` names) with `.venv/bin/python -m pip install` (`.venv\Scripts\python` on Windows). Install only that skill's packages.
- Video download: `yt-dlp` into `.venv`.
- OmniVoice voice generation: `python3.11 skills/omnivoice-tts/scripts/setup_omnivoice.py` (or `python3.12`); the model downloads on the first synthesis.

Before saying a task is done, check that the newly installed dependency works for that task. To check every dependency at once, run `python3 scripts/vas.py doctor --full`.

## Job Context Rule

When a request starts video-production work (planning, generating assets, rendering, or editing a video) and no existing `jobs/<job_id>/` is explicitly present in the chat context, create a new isolated job first with `$video-job-manager`, so all artifacts use the new job's canonical paths. Reuse an existing job only when its exact job ID or path is already provided in the chat context. Do not create a job for requests that are not video production, such as installing or upgrading VAS, installing anything from a ZIP, checking the installation, or creating your own skill or tool.

When a user request matches a project skill, load that skill's `SKILL.md` first, then load referenced scripts or supporting files only as needed. For Remotion work, load `$remotion-best-practices` first, then every specialist skill selected by that router. Prefer bundled scripts over regenerating equivalent code.

## Parallel-First Execution Rule

Default to the maximum useful parallelism for all project work. Split independent stories, assets, research tracks, image-generation tasks, validations, or other separable workstreams across concurrent agents and concurrent tool calls whenever the active environment permits it. The primary agent decides the appropriate grouping, concurrency level, and number of agents based on workload, rate limits, resource constraints, and the platform's available agent slots.

For example, when a job contains five independent news stories, assign one workstream or agent per story and run as many simultaneously as the current agent-slot limit allows; immediately schedule the remaining stories as slots become free. Do not serialize independent work merely for convenience.

Keep tasks sequential only at genuine dependency boundaries where an output is required by the next step. Examples include selecting or downloading an image before enhancing that image, generating narration audio before extracting word timestamps, producing asset semantics before an asset-grounded creative plan, and completing a render before final media QA. Parallelize work within and on either side of those dependency boundaries wherever possible.

For Claude Code compatibility, `.claude/skills/*` mirrors these project skills with symlinks so Claude can auto-discover them as project skills.

Hard rule: any task that creates, scaffolds, updates, previews, renders, or validates a Remotion project must first load and explicitly reference the official `$remotion-best-practices` router from `.agents/skills/remotion-best-practices`, then load every specialist Remotion skill selected by that router before making those specialist decisions.

At the start of a new video/Remotion project, run `scripts/ensure-remotion-skill.sh` to verify the complete official Remotion skill set and its Claude Code symlinks. If any skill is missing, suggest installing the bundle with `npx skills add remotion-dev/skills --yes`; if the task requires Remotion work now, ask for permission to run `scripts/ensure-remotion-skill.sh --install`, then continue only after validation succeeds.

Remotion dependency rule: new `jobs/<job_id>/remotion/node_modules` paths must be symlinks to repo-root `../../../node_modules`. Do not run `npm install` inside individual job folders. If dependencies are missing, run `npm install` once at repo root and reuse that shared install for all future jobs.

## Typography Line-Height Rule

Any new text added to a video, image, presentation, document, website, or other visual artifact must use a line height of at least `1.25` (`125%`) so adjacent lines do not overlap. This applies to titles, subtitles, captions, labels, body copy, and any other multiline text. Use a line height below `1.25` only when the user or an applicable skill explicitly specifies a different value.

## Voice Rule

For voice/narration/TTS requests with no provider named by the user, use `$omnivoice-tts`.

## Project Skills

- `$facebook-reel-downloader`: Download public or user-authorized Facebook Reels/videos with yt-dlp into the global raw asset pool or a specific job, with optional browser cookies and a TOML media report.
- `$free-tts`: Generate free/local Vietnamese narration with VieNeu-TTS when the user explicitly asks for it, or approves it as a fallback when OmniVoice is unavailable.
- `$supertonic-tts`: Generate private local multilingual TTS with Supertonic.
- `$fix-omnivoice`: Clean and audit low-volume artifacts in OmniVoice output.
- `$omnivoice-tts`: Generate local multilingual TTS or authorized zero-shot voice clones when the user names no other provider.
- `$voice-manager`: Manage a scalable local registry of authorized named voice profiles across TTS engines, including adding, listing, inspecting, validating, and synthesizing by stable voice name.
- `$video-downloader`: Download public video, audio, or extractor-provided thumbnails from any site supported by yt-dlp into `raw_assets/` or `jobs/<id>/input/raw_assets/`.
- `$tiktok-downloader`: Download public TikTok videos with yt-dlp first and automatic TikWM fallback when the extractor fails.
- `$youtube-fast-download`: Download public YouTube videos or Shorts quickly with yt-dlp, save MP4 video, and optionally export MP3 audio.
- `$video-audio-extractor`: Extract an audio track from video to WAV/MP3 for transcript, dedupe, or background-music reuse.
- `$word-timestamps-extractor`: Extract narration transcript with sentence and word timestamps.
- `$remotion-best-practices`: Official router installed from `remotion-dev/skills`; load it first for all Remotion work, then follow it to the relevant specialist skills.
- `$remotion-captions`: Official Remotion guidance for transcribing, importing, displaying, and animating captions.
- `$remotion-create`: Official Remotion guidance for scaffolding a project or composition and starting Studio.
- `$remotion-docs`: Official workflow for searching and reading current Remotion API documentation.
- `$remotion-interactivity`: Official guidance for structuring markup so elements and keyframes remain editable in Remotion Studio.
- `$remotion-maps`: Official Remotion map-animation router for static maps, Mapbox, MapLibre, MapTiler, GeoJSON, and CesiumJS.
- `$remotion-markup`: Official best practices for Remotion React markup, animation, layout, typography, media, effects, audio, fonts, and timing.
- `$remotion-multimedia`: Official Mediabunny guidance for browser-based video/audio processing and metadata.
- `$remotion-render`: Official guidance for rendering Remotion videos, stills, and transparent output.
- `$remotion-saas`: Official architecture guidance for Remotion-powered apps, Players, render backends, and automation.
- `$remotion-upgrade`: Official workflow for upgrading Remotion, compatible multimedia dependencies, and the installed Remotion skill set.
- `$motion`: Third-party skill for Motion (formerly Framer Motion) and CSS animation: best practices, examples, spring/bounce generation and performance audits.
- `$motion-design`: Third-party skill applying motion design principles (timing, easing, choreography, Disney principles) to animations and transitions.
- `$subtitle-screen-splitter`: Split subtitle text or word-level transcripts into screen-sized pages, breaking after punctuation and before capitalized sentence starts.
- `$video-compress-under-25mb`: Compress local videos under 25MB with H.264/AAC 2-pass encoding, preserving resolution/fps when possible, for upload limits such as Zernio upload-direct.
- `$video-job-manager`: Create and manage isolated video production jobs and canonical paths.
- `$video-storyboard-contact-sheet`: Convert a finished video into one flat storyboard/contact-sheet image with uniformly sampled or exact-time stills, shot numbers, timestamps, title, and video metadata.
