---
name: tiktok-downloader
description: Download public TikTok videos into the video pipeline, using yt-dlp first and automatic TikWM fallback when the extractor fails.
---

# TikTok Downloader

## Mục tiêu

Tải video TikTok công khai vào raw assets của dự án. Skill ưu tiên `$video-downloader` (yt-dlp) và chỉ dùng TikWM khi extractor TikTok của yt-dlp thất bại.

## Quyền sử dụng

Chỉ tải nội dung khi người dùng có quyền sử dụng hoặc nội dung được phép dùng cho mục đích hiện tại. Không dùng cho video riêng tư, paywall, hoặc để vượt cơ chế kiểm soát truy cập. Với video dùng thương mại, nhắc người dùng xác nhận quyền với footage và âm thanh.

## Cách dùng

```bash
python skills/tiktok-downloader/scripts/download_tiktok.py \
  --url "https://www.tiktok.com/@user/video/123" \
  --job jobs/<job_id> \
  --hd
```

Đầu ra mặc định là `jobs/<job_id>/input/raw_assets/videos/downloaded/` khi có `--job`; nếu không, là `raw_assets/videos/downloaded/`. Report được ghi tại `source/tiktok_download_report.toml` trong job hoặc cạnh output directory.

## Fallback TikWM

Script gửi URL TikTok công khai tới TikWM để tạo task, polling kết quả trong thời gian giới hạn, sau đó tải direct media URL được trả về. URL CDN tạm thời không được ghi vào report; report chỉ lưu URL TikTok ban đầu cùng metadata và đường dẫn file local.

TikWM là fallback tự động của skill: khi yt-dlp lỗi, script gửi URL TikTok công khai tới TikWM mà không hỏi lại. Gọi `--skip-tikwm-fallback` để chỉ thử yt-dlp. Nếu TikWM không trả URL media trước timeout, dừng với lỗi rõ ràng và không thử dịch vụ khác.

## Tham số

- `--hd`: yêu cầu chất lượng tốt nhất khi yt-dlp tải được.
- `--overwrite`: cho phép ghi đè file đã có.
- `--fallback-timeout`: số giây tối đa polling TikWM, mặc định `90`.
- `--skip-tikwm-fallback`: không dùng TikWM khi yt-dlp lỗi.

Sau khi tải xong, kiểm tra report và metadata video.
