---
name: video-downloader
description: Download public video, audio, and extractor-provided thumbnails from any site supported by yt-dlp into the video pipeline.
---

# Video Downloader

## Quy tắc đầu ra (BẮT BUỘC)

- Mọi ghi chú do AI/LLM sinh ra cho user hoặc report ngắn phải viết bằng tiếng Việt CÓ DẤU khi context là tiếng Việt.
- URL, CLI flag, file path, enum (`video`, `images`, `audio`, `all`) giữ nguyên tiếng Anh.
- Không in direct media URL có token ngắn hạn; chỉ báo file path local và metadata cần thiết.

## Mục tiêu

Tải nội dung công khai từ mọi website mà `yt-dlp` đang hỗ trợ thành asset local để pipeline dùng như footage thật. Script dùng binary `yt-dlp` trong `.venv/bin/yt-dlp` của repository trước, sau đó mới tìm binary trong PATH; có thể override bằng biến môi trường `YTDLP_BIN`.

## Khi nào dùng

- User đưa URL video hoặc audio mà `yt-dlp` hỗ trợ và muốn tải về làm raw asset.
- Pipeline cần đưa TikTok clip vào `raw_assets/videos/downloaded/` hoặc `jobs/<id>/input/raw_assets/videos/downloaded/`.
- Cần lấy audio đã tách hoặc thumbnail do extractor của `yt-dlp` cung cấp.

## Quy tắc pháp lý / quyền sử dụng

- Chỉ tải nội dung khi user có quyền dùng nội dung đó hoặc nội dung được phép sử dụng cho mục đích hiện tại.
- Không dùng skill này để né paywall, truy cập nội dung riêng tư, hoặc bypass cơ chế bảo vệ trái phép.
- Nếu user định dùng thương mại, nhắc họ xác nhận quyền sử dụng footage/audio trước khi render final.

## Đầu vào

- `--url`: 1 URL public mà `yt-dlp` hỗ trợ.
- `--urls-file`: file text chứa nhiều URL, mỗi dòng 1 URL; dòng trống và dòng bắt đầu bằng `#` bị bỏ qua.
- `--job jobs/<id>`: nếu có, output mặc định vào `jobs/<id>/input/raw_assets/...`.
- `--output-dir`: override thư mục lưu video; thư mục `images`/`audio` tương ứng được suy ra khi cần.
- `--mode video|images|audio|all`: mặc định `video`.
- `--hd`: chọn format video tốt nhất có sẵn (`bv*+ba/b`) và remux sang MP4 khi có `ffmpeg`.
- `--cookies-from-browser chrome`: truyền browser profile cho `yt-dlp` khi TikTok yêu cầu đăng nhập hoặc challenge.
- `--extractor-args`: truyền extractor arguments nguyên dạng cho `yt-dlp` khi cần.
- `--proxy`: truyền proxy URL cho `yt-dlp` khi user đã cấu hình proxy hợp lệ.
- `--report-toml`: mặc định `download_report.toml` trong `output-dir`, hoặc `jobs/<id>/source/download_report.toml` khi có `--job`.

## Đầu ra

```text
raw_assets/videos/downloaded/<id>_<slug>.<ext>
raw_assets/audio/downloaded/<id>_<slug>.mp3
raw_assets/images/downloaded/<id>_<slug>.<ext>
```

Report TOML ghi lại URL nguồn, provider, asset path, title, author, media type, byte size, duration/dimensions nếu `ffprobe` có sẵn. Provider trong report là `yt-dlp`.

`video` là media video do `yt-dlp` tải. `audio` dùng post-processing `--extract-audio --audio-format mp3` và cần `ffmpeg`. `images` dùng `--write-all-thumbnails` và chuyển sang JPG khi có `ffmpeg`; đây là các thumbnail mà extractor cung cấp, không cam kết là ảnh slideshow gốc của TikTok.

## Script tiện ích

```bash
# Tải 1 video từ website được yt-dlp hỗ trợ vào global raw_assets pool
python skills/video-downloader/scripts/download_video.py \
  --url "https://example.com/video" \
  --hd

# Tải bằng cookie của Chrome khi website yêu cầu session
python skills/video-downloader/scripts/download_video.py \
  --url "https://www.tiktok.com/@user/video/123" \
  --cookies-from-browser chrome

# Tải vào job hiện có để watcher asset-index pickup
python skills/video-downloader/scripts/download_video.py \
  --url "https://www.tiktok.com/@user/video/123" \
  --job jobs/<id> \
  --hd

# Batch nhiều URL
python skills/video-downloader/scripts/download_video.py \
  --urls-file urls.txt \
  --job jobs/<id> \
  --mode all
```

## Quy trình

1. Xác nhận user có quyền dùng nội dung nếu mục đích không rõ.
2. Kiểm tra `.venv/bin/yt-dlp` hoặc cài/cập nhật `yt-dlp` trong shared venv; không chạy `npm install` hay tạo dependency riêng trong job.
3. Chạy script với `--url` hoặc `--urls-file`; dùng `--job` khi đây là asset cho một video job cụ thể.
4. Kiểm tra report TOML, số file và metadata bằng `ffprobe` nếu cần.

## Ghi chú triển khai

- Script dùng `--no-playlist` để mỗi URL chỉ tạo asset của một TikTok post.
- File name ổn định theo `id` và title metadata; rerun sẽ skip file đã tồn tại trừ khi truyền `--overwrite`.
- Website có thể chặn extractor hoặc yêu cầu đăng nhập. Khi đó báo lỗi `yt-dlp` nguyên nhân và thử `--cookies-from-browser` hoặc `--proxy` chỉ khi user có quyền truy cập. Với TikTok, dùng `$tiktok-downloader` khi cần fallback TikWM được user cho phép.
