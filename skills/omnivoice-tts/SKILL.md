---
name: omnivoice-tts
description: Generate local multilingual text-to-speech and reusable named zero-shot voice profiles with the official k2-fsa/OmniVoice model. Use as this repository's default voice/narration provider when no provider or template-specific voice is requested; also use when the user explicitly requests OmniVoice or k2-fsa/OmniVoice, needs a reusable cloned voice from a short authorized reference recording, wants to manage named local voice profiles, or wants CPU/MPS/CUDA/XPU-local inference without a cloud voice API.
---

# OmniVoice TTS

Generate 24 kHz WAV speech with `k2-fsa/OmniVoice`. Use the bundled wrapper instead of rewriting the model-loading and device-selection code.

## Required behavior

- Use the isolated Python 3.11 environment at `.cache/omnivoice-tts/venv/`. Do not install into the repository `.venv`.
- Store Hugging Face weights in `.cache/omnivoice-tts/huggingface/`. Both paths are Git-ignored.
- Use `k2-fsa/OmniVoice` unless the user explicitly selects another compatible checkpoint.
- Preserve Vietnamese diacritics. Pass `--language Vietnamese` for Vietnamese narration.
- Prefer a clean 3–10 second reference clip and provide its exact transcript with `--ref-text` or `--ref-text-file`. Providing the transcript avoids loading Whisper and improves repeatability.
- Use only audio the user owns or is authorized to clone. Do not facilitate deceptive impersonation.
- Require explicit authorization confirmation before creating a named profile. Record a concise authorization note in profile metadata.
- Store reusable profiles in `voice_profiles/omnivoice/<voice-id>/`. This local directory is Git-ignored because it contains biometric voice samples.
- Write job narration to a stable path such as `jobs/<job_id>/source/voice.wav`.
- Before every synthesis, apply the text-preparation workflow below, including when using a batch or job-local runner. Do not pass raw line breaks inside a chunk to the model.
- Run `$fix-omnivoice` after every successful synthesis by default. Keep the requested output as the raw original and create a corrected sibling plus JSON audit report.
- Use `--skip-fix-omnivoice` only when the user explicitly requests raw-only output or when debugging synthesis artifacts.
- For template-based jobs, follow the matching `template.toml` and template skill; their voice contract takes precedence over this repository-level fallback.

## Chuẩn bị văn bản trước TTS

Thực hiện trước khi sinh audio, kể cả khi dùng script batch hoặc runner riêng cho job. Đây là bước agent phải áp dụng; `--normalize-linebreaks` hiện chỉ chuẩn hóa định dạng, chưa tự thực hiện toàn bộ quy trình này.

1. **Giữ bản gốc.** Lưu nguyên văn vào `source/narration_original.txt` hoặc giữ file gốc đã có. Tạo bản dùng để đọc riêng tại `source/narration_tts.txt`; không ghi đè bản gốc. Giữ dấu tiếng Việt, thứ tự câu và lời thoại. Không tự thêm lời dẫn, rút gọn hay diễn đạt lại khi người dùng yêu cầu đọc nguyên văn.
2. **Phân biệt xuống dòng trình bày và ngắt nhịp.** Chuẩn hóa CRLF/CR thành LF, bỏ BOM và khoảng trắng thừa. Với dòng bị ngắt chỉ để trình bày, nối bằng **một khoảng trắng**, giữ dấu câu. Với dòng đánh dấu chuyển ý, nhấn ý hoặc đổi người nói, tách thành beat riêng. Không mặc định mọi xuống dòng đều cần nghỉ dài, cũng không gom các lượt thoại chỉ để đạt độ dài chunk.
3. **Chuẩn hóa cách đọc khi cần.** Kiểm tra số, ngày tháng, đơn vị và chữ viết tắt. Chỉ đổi sang dạng đọc bằng chữ khi cách hiểu rõ từ ngữ cảnh; giữ nguyên giá trị và ý nghĩa. Không tự đoán ngày tháng mơ hồ, tên riêng hay chữ viết tắt nhiều nghĩa. Ghi các thay đổi ngoài khoảng trắng vào `source/narration_normalization.md` khi có; chỉ hỏi lại nếu sự mơ hồ thực sự làm thay đổi lời đọc. Không chèn dấu chấm máy móc ở mỗi dòng hoặc dùng nhiều dấu chấm để ép khoảng nghỉ.
4. **Lập beat và khoảng nghỉ.** Với wrapper chuẩn, mỗi beat nằm trên một dòng, cách nhau bằng một dòng trống; dùng `--split-paragraphs --pause-ms`. Khi cần ngữ điệu hoặc khoảng nghỉ khác nhau theo vai, lưu `source/voice_segments.json` với `id`, `text`, `role`, `instruct`, `speed`, `pause_ms`. Trường `text` của mỗi beat không chứa CR/LF. Runner phải sinh từng beat rồi ghép với khoảng lặng đã định; wrapper CLI hiện chỉ có một cấu hình chung cho mỗi lần gọi, không tự đọc manifest này.
5. **Đối chiếu trước khi sinh.** Ghép lại lời của các beat theo thứ tự và so với bản gốc sau khi chuẩn hóa khoảng trắng cùng các thay đổi cách đọc đã ghi nhận. Kiểm tra không mất, thêm, lặp hoặc đảo câu; không đưa nhãn vai, ghi chú diễn xuất hay metadata vào phần lời đọc. Nếu người dùng yêu cầu một chunk duy nhất, nối các dòng bằng khoảng trắng; không hứa có khoảng nghỉ chính xác bên trong chunk đó.

### Tránh lỗi dính chữ ở ranh giới dòng

Runtime OmniVoice đang cài có bước `_combine_text()` xóa CR/LF bằng chuỗi rỗng. Vì vậy `"qua thành.\nKhông đánh thắng trận."` có thể thành `"qua thành.Không đánh thắng trận."`; nếu không có dấu câu thì hai từ có thể dính liền. **Trước mỗi lệnh `model.generate`, bảo đảm từng chunk không còn xuống dòng nội bộ.** Chọn ranh giới beat trước, sau đó thay xuống dòng còn lại trong từng chunk bằng khoảng trắng. Không xóa toàn bộ ranh giới đoạn trước khi chia beat.

`--normalize-linebreaks` không sửa lỗi này một mình: nó vẫn giữ xuống dòng đơn. File `narration_tts.txt` cần được chuẩn bị theo quy trình trên và truyền cùng `--split-paragraphs`; không gửi nguyên file chứa các dòng trống vào một lần `model.generate`.

### Khoảng nghỉ và thoại nhiều vai trong cùng một giọng

- Chọn khoảng nghỉ theo ý nghĩa và nhịp kể; tham khảo các mức ở phần dưới, không cố định một độ dài cho mọi dòng. `pause_ms` là **khoảng lặng chèn thêm**: tổng khoảng nghỉ nghe được còn gồm phần im lặng ở đuôi/đầu hai clip. Không mặc định xuống dòng sẽ nghỉ lâu hơn dấu chấm, hay dấu chấm luôn tạo cùng một khoảng nghỉ.
- Khi người dùng yêu cầu một giọng diễn nhiều vai, giữ cùng voice profile/reference cho mọi beat. Phân biệt vai bằng dấu câu, tốc độ vừa phải và preset `instruct` được runtime hỗ trợ; nhãn cảm xúc tự do chỉ là ghi chú đạo diễn, không truyền như preset. Không đổi giọng hoặc thêm tiếng cảm thán ngoài kịch bản để tạo khác biệt.
- Kiểm tra các chỗ nối đại diện, nhất là chuyển người nói và câu rất ngắn. Nghe thử khi có khả năng; nếu chỉ kiểm tra waveform/thời gian hoặc ASR, nêu đúng giới hạn. ASR kiểm tra nội dung không xác nhận khoảng nghỉ tự nhiên; `$fix-omnivoice` làm sạch nhiễu không sửa nhịp đọc. Khi có lỗi dính câu, sửa ranh giới beat hoặc văn bản đầu vào rồi sinh lại phần bị ảnh hưởng.

## Project narration conventions

- For Vietnamese narration in this project, prefer the named `Socolive` profile when the user has selected it or when the job's voice contract specifies it. Do not silently replace an explicitly selected voice or a template-specific voice.
- Preserve Vietnamese diacritics and direct-dialogue quotation marks. Use Vietnamese curly quotes: `“...”`.
- For hesitation, use the Unicode ellipsis `…`, not four ASCII periods. Example: `“Ờ… anh bán gì cơ?”`. The ellipsis gives the model a natural internal hesitation; it is not a precise millisecond timer.
- Use the prepared TTS text: one line per beat, one blank line between beats. The wrapper normalizes line-ending formats but preserves single line breaks; the text-preparation workflow above must resolve those before synthesis. Disable formatting normalization only for debugging with `--no-normalize-linebreaks`.
- When the narration needs a deliberate pause between beats, synthesize with `--split-paragraphs` and set `--pause-ms`.
- A practical Vietnamese narration default is `--pause-ms 280`. Use roughly `180–250` ms for a tight edit, `280–400` ms for a natural beat, and `450–650` ms for a visibly dramatic pause. Do not apply a long pause globally unless every paragraph should be separated that way.
- Keep short dialogue exchanges in separate paragraphs when each speaker needs a distinct beat. For a precisely timed hesitation, split the utterance into two paragraphs (for example `“Ờ…”` followed by `“Anh bán gì cơ?”`) instead of relying only on punctuation.

### Nhịp đọc ổn định cho bài dài

Khi người dùng muốn một bài đọc dài nghe liền mạch và đều tốc độ, đừng mặc định đưa toàn bộ bài vào một chunk: model có thể tự thay đổi nhịp theo độ dài câu, dấu phẩy, số và tên riêng. “Đọc một mạch” là trải nghiệm nghe, không bắt buộc là một lần sinh duy nhất.

- Chia bài thành các paragraph/beat có độ dài tương đối đồng đều, thường khoảng 180–400 ký tự tiếng Việt; ghép beat cuối quá ngắn vào beat trước khi phù hợp.
- Với đoạn cần một dòng chảy liên tục, dùng `--split-paragraphs --pause-ms 100`. Khoảng nghỉ này đủ để model ổn định nhịp giữa beat nhưng hầu như không được cảm nhận là ngắt chương. Chỉ dùng pause dài hơn khi nội dung thực sự cần nghỉ.
- Dùng `--normalize-chunk-levels --remove-low-volume-islands`; hai tùy chọn này ổn định âm lượng và làm sạch artifact, không thay đổi tốc độ nói.
- Viết số liệu bằng chữ khi cần làm rõ cách đọc và ý nghĩa đã xác định. Ví dụ: `Năm một nghìn bảy trăm tám mươi chín, nước Pháp khánh kiệt.` giữ cấu trúc câu gốc `Năm 1789, nước Pháp khánh kiệt.` Chỉ biên tập lại câu hoặc thêm từ khi người dùng cho phép; không tự tách mọi mốc năm/ngày tháng thành câu riêng.
- Giữ câu ở mức vừa phải và ưu tiên dấu chấm cho ý cần nhấn. Tránh dồn hai ý lớn vào một câu bằng dấu phẩy, chấm phẩy hoặc gạch ngang.
- Nếu người dùng thực sự yêu cầu một chunk duy nhất, làm theo yêu cầu nhưng nói rõ đây không phải lựa chọn tốt để giữ nhịp đồng đều.

Recommended Vietnamese profile command:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py synthesize \
  --text-file jobs/<job_id>/source/narration_tts.txt \
  --language Vietnamese \
  --voice-name Socolive \
  --normalize-linebreaks \
  --split-paragraphs \
  --pause-ms 280 \
  --output jobs/<job_id>/source/voice.wav
```

`--pause-ms` is a feature of this project's wrapper, not a native OmniVoice model argument. It inserts digital silence only between the chunks created by `--split-paragraphs`; it does not create a pause at an arbitrary position inside one chunk.

`--normalize-linebreaks` is also a wrapper feature. It is enabled by default and applied before paragraph splitting. It standardizes formatting; it neither turns every ordinary newline into a new chunk nor replaces internal single newlines with spaces. Prepare the text first as described above, then use blank-line beat separators with `--split-paragraphs`.

## Instruct and fine-grained control

- `--instruct` is not free-form prompting in the installed OmniVoice runtime. It accepts a limited set of preset voice attributes, such as `male`, `female`, `young adult`, `middle-aged`, `moderate pitch`, `low pitch`, `high pitch`, `whisper`, and supported accents.
- Use English preset labels with comma + space, for example `--instruct "male, moderate pitch"`. Do not pass a long English or Vietnamese sentence such as “pause longer after...” because the runtime rejects unsupported instruct items.
- `--instruct` changes voice attributes; it is not a reliable exact pause controller. Use punctuation (`…`) for natural hesitation and paragraph splitting plus `--pause-ms` for measurable silence.
- OmniVoice's native fine-grained controls currently cover supported non-verbal tags and pronunciation overrides. The installed runtime recognizes tags such as `[laughter]`, `[sigh]`, `[question-ah]`, `[question-oh]`, `[surprise-ah]`, `[surprise-oh]`, and `[dissatisfaction-hnn]`.
- Fine-grained control also supports pronunciation correction through bracketed phoneme overrides where the model/language supports them, and pinyin tone markers for Chinese. These controls do not provide a native arbitrary-duration tag such as `<break time="450ms"/>`.
- Do not invent tags such as `[pause=450ms]`; they are not supported by the installed tokenizer. For exact pauses, synthesize separate chunks and concatenate them with `--pause-ms` or edit the WAV afterward.

## Install or repair

`scripts/requirements.txt` pins the official source commit `08be0b4ccbac3e13e374e86fbfead4b4cac343e2` (updated 2026-10-04), with Torch/Torchaudio 2.8.0. Its package version still reports `0.2.1`; inspect the installed distribution's `direct_url.json` to verify the actual commit. This source update does not change the standard generation/newline-handling code and is not a confirmed fix for slurred or repeated speech. When explicitly switching an existing PyPI 0.2.1 installation to this same-version source revision, pip may require `--force-reinstall --no-deps` for the OmniVoice package alone; verify `pip check` and a short synthesis afterward.

Check the isolated environment:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py status
```

If it is absent or broken, run:

```bash
python3.11 skills/omnivoice-tts/scripts/setup_omnivoice.py
```

The setup pins matching Torch and Torchaudio releases before installing OmniVoice. If package or model downloads are blocked, request network permission and repeat the same command.

## Synthesize

Generate Vietnamese speech without cloning:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py synthesize \
  --text "Xin chào. Đây là giọng đọc được tạo bằng OmniVoice." \
  --language Vietnamese \
  --output source/voice.wav
```

Every successful synthesis automatically creates:

```text
source/voice.wav
source/voice_corrected.wav
source/voice_corrected_report.json
```

The requested `--output` remains the original. `$fix-omnivoice` produces the
corrected sibling with two boundary-aware passes at `-50 dBFS` and `-55 dBFS`,
then verifies that no sample outside the detected regions changed. Override the
derived paths with `--corrected-output` and `--fix-report`.

Clone a voice:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py synthesize \
  --text-file jobs/<job_id>/source/narration.txt \
  --language Vietnamese \
  --ref-audio input/reference.wav \
  --ref-text-file input/reference.txt \
  --output jobs/<job_id>/source/voice.wav
```

## Named voice profiles

Create one reusable profile after the user explicitly confirms authorization:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py profile-create \
  --name Socolive \
  --ref-audio input/reference.mp3 \
  --ref-text-file input/reference.txt \
  --source-url "https://example.com/source" \
  --authorization-note "User confirmed authorization in the current task." \
  --authorized
```

The command normalizes the sample to mono 24 kHz WAV and creates:

```text
voice_profiles/omnivoice/socolive/
├── profile.toml
├── reference.txt
└── reference.wav
```

Use the profile by name in future jobs:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py synthesize \
  --voice-name Socolive \
  --text-file jobs/<job_id>/source/narration.txt \
  --output jobs/<job_id>/source/voice.wav
```

When the user asks for **“đọc chất lượng cao”**, **“voice chất lượng cao”**,
or otherwise explicitly requests high-quality OmniVoice output, pass
`--quality high`:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py synthesize \
  --quality high \
  --voice-name Socolive \
  --text-file jobs/<job_id>/source/narration.txt \
  --output jobs/<job_id>/source/voice.wav
```

High-quality mode uses 32 inference steps by default and selects Apple MPS with
OmniVoice/PyTorch's standard accelerator configuration: `float16` and the
default attention implementation. It does not apply the `float32`/eager
attention workaround discussed in `k2-fsa/OmniVoice#172`, and it does not
silently fall back to CPU when MPS is unavailable.

List available profiles:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py profiles
```

Treat the profile directory as the registry and each child folder as one atomic voice record. Keep engine-specific profiles under their own directory so future providers can use sibling registries without mixing incompatible metadata.

Useful options:

- `--device auto|cpu|mps|cuda|xpu`: auto-detect by default.
- `--dtype auto|float32|float16|bfloat16`: `auto` uses float32 on CPU and float16 on accelerators.
- `--quality high`: use 32 steps by default and select MPS with standard `float16` and default attention.
- `--num-step 16`: faster CPU inference; use `32` for the normal quality setting.
- `--speed 1.0`: values greater than one speak faster.
- `--model <id-or-path>`: choose another compatible OmniVoice checkpoint.
- `--offline`: refuse network access and use cached weights only.

The first synthesis downloads about 3.3 GB of published model files. Hugging Face's materialized snapshot and Xet/blob cache can occupy roughly 6.5 GB on disk. Do not claim the model is ready for offline use until that download and one actual generation succeed.

## CPU guidance

- Expect offline/batch speed rather than real-time performance.
- Start with `--device cpu --num-step 16`.
- Supply the reference transcript to avoid loading Whisper.
- Keep one model process alive for several outputs when extending the wrapper; model loading is expensive.
- Recommend at least 16 GB RAM. If memory is tight, close other large applications before loading the model.

## Verify output

After synthesis:

1. Confirm the WAV exists and is non-empty.
2. Confirm the corrected WAV and its JSON audit report exist.
3. Require `verification.valid = true` in the Fix OmniVoice report.
4. Inspect duration, sample rate, and channel count with `ffprobe`.
5. Listen to or play both files when the user requests a quality check.
6. For video subtitle timing, run `$word-timestamps-extractor` on the approved corrected WAV.

## Remove isolated low-volume artifacts

`$fix-omnivoice` is now the default post-processing path. Use the older bundled
cleanup script only for manual diagnostics or backward-compatible tuning. It
only replaces short, bracketed islands with digital silence; it does not gate
continuous speech:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/remove_low_volume_islands.py \
  --input jobs/<job_id>/source/voice.wav \
  --output jobs/<job_id>/source/voice_clean.wav
```

Run with `--dry-run` first when tuning thresholds. Defaults target non-quiet
islands of at most 160 ms bracketed by at least 300 ms of audio below -36 dBFS
on both sides. Prefer this boundary-aware cleanup over a full-track noise gate,
which can remove quiet consonants and natural breath detail.

To audit every audio island whose peak is at most a chosen percentage of the
file-wide peak, regardless of how short the surrounding quiet regions are, use:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/find_relative_volume_islands.py \
  --input jobs/<job_id>/source/voice.wav \
  --min-peak-ratio 0.20 \
  --max-peak-ratio 0.60 \
  --min-quiet-before-ms 100 \
  --min-quiet-after-ms 300 \
  --silence-threshold-db -36 \
  --frame-ms 10 \
  --json-output jobs/<job_id>/source/relative_islands.json \
  --csv-output jobs/<job_id>/source/relative_islands.csv \
  --zero-output jobs/<job_id>/source/voice_islands_zeroed.wav
```

Ratio bounds are exclusive. The example selects islands preceded by at least
100 ms and followed by at least 300 ms of near-silence whose peak is greater
than 20% and less than 60% of the highest absolute sample amplitude in the
entire file. Near-silence is measured in 10 ms frames below -36 dBFS.
`--zero-output` preserves the file length and replaces every reported island
with digital zero without overwriting the input.

For low-volume pre-roll or tail artifacts near a longer spoken sentence, use
the local-context satellite detector instead of comparing against the
file-wide peak:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/find_satellite_noise_islands.py \
  --input jobs/<job_id>/source/voice.wav \
  --merge-gap-ms 200 \
  --main-min-ms 1000 \
  --satellite-min-ms 10 \
  --satellite-max-ms 800 \
  --max-main-gap-ms 1500 \
  --min-peak-ratio 0.20 \
  --max-peak-ratio 0.60 \
  --min-rms-difference-db 4 \
  --min-outer-quiet-ms 100 \
  --json-output jobs/<job_id>/source/satellite_noise.json \
  --csv-output jobs/<job_id>/source/satellite_noise.csv \
  --zero-output jobs/<job_id>/source/voice_satellites_zeroed.wav
```

This merges internal pauses up to 200 ms to define longer main-speech
components, then finds shorter components immediately before or after the
nearest main component. Peak ratios and RMS differences are local to that main
component, not global to the whole file.
`--zero-output` preserves timing and replaces only the detected satellite
component samples with digital zero.

For paragraph-split synthesis where whole chunks have visibly different
amplitudes, use `--normalize-chunk-levels --remove-low-volume-islands` during
synthesis. The first option matches active-speech RMS between chunks with a
bounded gain adjustment; the second removes only short artifacts inside long
pauses:

```bash
.cache/omnivoice-tts/venv/bin/python \
  skills/omnivoice-tts/scripts/omnivoice_tts.py synthesize \
  --quality high \
  --voice-name Socolive \
  --text-file jobs/<job_id>/source/narration.txt \
  --split-paragraphs \
  --normalize-chunk-levels \
  --remove-low-volume-islands \
  --output jobs/<job_id>/source/voice_clean.wav
```
