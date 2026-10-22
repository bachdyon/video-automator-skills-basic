# VAS — Video Automator Skills (Basic)

> **Biến AI agent trên máy bạn thành một ekip làm video ngắn. Miễn phí, không giới hạn, không cần API key.**

Bạn chỉ cần nói, agent sẽ làm: tải video từ khắp nơi, đọc lời thoại bằng giọng như người thật, bóc phụ đề chính xác từng chữ, dựng thành video và nén sẵn để đăng. Mọi thứ chạy ngay trên máy bạn, không tính tiền theo lượt, không giới hạn số video.

### Làm được ngay sau khi cài

- 🎙️ **Giọng đọc miễn phí, dùng bao nhiêu cũng được.** Ba engine giọng đọc chạy offline đọc tiếng Việt tự nhiên. Nhân bản giọng của chính bạn (hoặc giọng bạn được phép dùng) chỉ từ một đoạn ghi âm mẫu, lưu thành thư viện giọng để dùng lại mãi.
- ⬇️ **Tải video đa nền tảng chỉ bằng một đường link.** YouTube, TikTok, Facebook Reels và hàng nghìn trang khác: dán link là video và audio về thẳng thư mục làm việc.
- 📝 **Phụ đề chuẩn đến từng chữ.** Tự bóc lời thoại kèm mốc thời gian của từng từ, chia thành từng dòng vừa màn hình điện thoại, ngắt đúng dấu câu, sẵn sàng cho kiểu phụ đề chạy theo giọng nói.
- 🎬 **Dựng video bằng lời nói.** Đi kèm trọn bộ skill Remotion chính thức: mô tả video bạn muốn, agent tự viết code, ghép giọng đọc, phụ đề, hình ảnh rồi xuất ra MP4.
- 📦 **Sẵn sàng để đăng.** Nén video xuống dưới 25 MB mà vẫn giữ độ nét, xuất một ảnh storyboard tóm tắt cả video để duyệt trong vài giây.
- 📱 **Giao việc từ xa.** Dùng cùng một AI agent có điều khiển từ điện thoại (ví dụ Remote Control của Claude Code), bạn ra lệnh khi đang ở ngoài, về nhà là có kết quả.
- 🧩 **Càng dùng càng hợp với bạn.** Muốn thêm một kỹ năng riêng, chỉ cần nhờ agent tạo. Kỹ năng đó được giữ nguyên qua mọi lần cập nhật.

### Muốn đi xa hơn? VAS Premium

Khi đã quen tay, **VAS Premium** đưa bạn từ "làm từng bước" sang "giao ý tưởng, nhận video": pipeline tự động từ ý tưởng tới video hoàn chỉnh, tạo ảnh và video bằng AI (Veo, Seedance, Grok Imagine…), avatar nói chuyện khớp khẩu hình, lồng tiếng Việt cho video nước ngoài, tìm footage theo nội dung và quản lý lịch đăng bài. Nâng cấp chỉ bằng một tin nhắn cho agent, mọi giọng đọc, job và kỹ năng riêng của bạn được giữ nguyên.

## Cài đặt

Bạn không cần biết lập trình. Một AI agent sẽ cài giúp bạn, bạn chỉ cần dán một tin nhắn.

**Bước 1.** Cài một AI agent trên máy tính, ví dụ [Claude Code](https://claude.com/claude-code), Codex hoặc Cursor.

**Bước 2.** Tạo một thư mục trống, ví dụ thư mục `VAS` trong Documents, rồi mở thư mục đó bằng AI agent.

**Bước 3.** Dán nguyên văn tin nhắn này cho agent:

> Cài đặt VAS Basic cho tôi vào thư mục này, lấy từ https://github.com/bachdyon/video-automator-skills-basic. Sau khi tải về, làm theo mục "Installation Rule" trong file AGENTS.md. Khi bạn đã kiểm tra và đảm bảo mọi thứ chạy được, trả lời: Sẵn sàng.

**Bước 4.** Agent sẽ tự tải và cài những gì còn thiếu. Thỉnh thoảng nó sẽ hỏi bạn cho phép chạy lệnh hoặc cài phần mềm (như Python, Node.js, ffmpeg): hãy đồng ý. Nếu máy hỏi mật khẩu, bạn tự nhập, đừng gửi mật khẩu cho agent.

**Bước 5.** Khi agent trả lời **Sẵn sàng** là xong. Hãy thử nhờ nó làm việc, ví dụ: "Tạo giọng đọc cho đoạn văn này: …". Nếu agent báo còn lỗi, nó sẽ giải thích bạn cần làm gì tiếp.

Mọi tính năng của Basic chạy ngay trên máy bạn, không cần API key.

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
