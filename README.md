# VAS — Video Automator Skills (Basic)

> Bộ skill cơ bản, miễn phí, chạy trên máy của bạn để agent chuẩn bị nguyên liệu cho video ngắn: tạo giọng đọc, lấy transcript từng từ, chia subtitle, tải và nén video. Không cần API key trả phí.

VAS Basic không gọi dịch vụ AI tạo ảnh/video. Agent vẫn có thể tự dựng video bằng Remotion nhờ bộ skill Remotion chính thức đi kèm. Công cụ tạo media bằng AI và pipeline dựng video tự động đầy đủ nằm trong **VAS Premium**.

## Cài đặt

### Yêu cầu

- macOS, Windows hoặc Linux.
- Python 3.11 trở lên, Node.js 18 trở lên, `git`, và `ffmpeg` / `ffprobe` có trong PATH. Giọng đọc OmniVoice cần riêng Python 3.11 hoặc 3.12.
- Một AI agent đọc được `AGENTS.md`, ví dụ Claude Code, Codex hoặc Cursor.

### Lấy mã nguồn

```bash
git clone https://github.com/bachdyon/video-automator-skills-basic.git vas
cd vas
```

### Cài phụ thuộc

Chạy tại thư mục gốc của VAS:

```bash
npm install
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/word-timestamps-extractor/scripts/requirements.txt -r skills/supertonic-tts/scripts/requirements.txt yt-dlp Pillow numpy
python3.11 skills/omnivoice-tts/scripts/setup_omnivoice.py
cp env.example .env
```

- `npm install` chỉ chạy một lần ở thư mục gốc; mọi job dùng chung `node_modules` này.
- OmniVoice (giọng đọc mặc định) có môi trường riêng tại `.cache/omnivoice-tts/venv/`. Nếu máy có Python 3.12 thay vì 3.11, dùng `python3.12` cho lệnh này. Model được tải ở lần tạo giọng đầu tiên.
- Trên Windows, thay `.venv/bin/python` bằng `.venv\Scripts\python` và `cp` bằng `copy`.
- `.env` có thể để trống: Basic chạy local, các key trong đó chỉ dùng cho tính năng tùy chọn.

### Kiểm tra

```bash
python3 scripts/vas.py doctor
```

Mọi dòng `FAIL` cần được xử lý trước khi dùng; `WARN` về `.env` có thể bỏ qua.

Xong thì mở thư mục VAS bằng AI agent và nhờ nó làm việc, ví dụ "tạo giọng đọc cho đoạn văn này".

## Phiên bản, tùy biến và nâng cấp

- File `VERSION` cho biết bạn đang dùng **VAS** (basic) hay **VAS Premium**.
- Muốn tạo hoặc sửa skill hoặc tool riêng: nhờ agent làm. Agent sẽ lưu vào `customs/` và ghi một dòng vào `AGENTS.customs.md`. Bản trong `customs/` trùng tên với bản gốc sẽ thay thế bản gốc. Upgrade không bao giờ chạm vào `customs/`, `AGENTS.customs.md`, `jobs/`, `raw_assets/` hay `.env`.
- Nâng cấp lên Premium: đính kèm file ZIP Premium và nhắn agent "upgrade lên premium bằng file zip này". Agent sẽ chạy `python3 scripts/vas.py upgrade <file.zip>`, tự kiểm tra sau khi cài, và có thể hoàn tác bằng `python3 scripts/vas.py upgrade --rollback`.
- Kiểm tra cài đặt bất kỳ lúc nào: `python3 scripts/vas.py doctor`.

## Skills

**Quản lý job**

- `$video-job-manager` — tạo và quản lý job biệt lập, metadata, input, artifact, status và đường dẫn chuẩn.
- `$video-storyboard-contact-sheet` — biến một video đã xong thành một ảnh storyboard/contact sheet có số cảnh, timestamp và metadata.

**Giọng đọc và audio (chạy local)**

- `$omnivoice-tts` — giọng đọc đa ngôn ngữ và voice clone zero-shot bằng OmniVoice; provider giọng đọc mặc định.
- `$fix-omnivoice` — dọn tiếng lạ nhỏ và đuôi âm thừa trong file WAV OmniVoice, giữ nguyên thời lượng.
- `$free-tts` — giọng đọc tiếng Việt miễn phí bằng VieNeu-TTS.
- `$supertonic-tts` — giọng đọc đa ngôn ngữ riêng tư bằng Supertonic, không cần API key hay GPU.
- `$voice-manager` — quản lý kho giọng đã đặt tên (voice profile) dùng chung cho các engine TTS.
- `$word-timestamps-extractor` — trích transcript có timestamp cấp câu và cấp từ.
- `$video-audio-extractor` — tách audio từ video sang WAV/MP3 để làm transcript hoặc nhạc nền.

**Subtitle**

- `$subtitle-screen-splitter` — chia subtitle/transcript thành các trang ngắn vừa màn hình, ngắt theo dấu câu.

**Tải và nén video**

- `$video-downloader` — tải video, audio, thumbnail từ mọi website mà `yt-dlp` hỗ trợ.
- `$youtube-fast-download` — tải nhanh video/Shorts YouTube thành MP4, kèm MP3.
- `$tiktok-downloader` — tải TikTok công khai bằng `yt-dlp`, tự chuyển sang TikWM khi lỗi.
- `$facebook-reel-downloader` — tải Facebook Reel công khai hoặc được phép xem.
- `$video-compress-under-25mb` — nén MP4/MOV xuống dưới khoảng 25 MB, giữ độ phân giải khi có thể.

**Skill Remotion chính thức** (từ `remotion-dev/skills`)

- `$remotion-best-practices` — router bắt buộc cho mọi task Remotion, dẫn tới các skill `remotion-*` chuyên sâu đi kèm.

---

Nếu repo hữu ích cho bạn, hãy cân nhắc [donate](https://vas.bachdyon.com/donate) để dự án có kinh phí tiếp tục dùng AI tools cho phát triển và test tính năng mới.

---

## Đóng góp

Đóng góp được hoan nghênh. Đọc [CONTRIBUTING.md](CONTRIBUTING.md) để biết cách báo bug, đề xuất feature, hoặc viết skill mới.

## License

**PolyForm Noncommercial 1.0.0** — sử dụng cá nhân, học tập, nghiên cứu OK. Mọi mục đích thương mại cần xin phép tác giả ([@bachdyon](https://github.com/bachdyon)). Xem toàn văn: [LICENSE](LICENSE).
