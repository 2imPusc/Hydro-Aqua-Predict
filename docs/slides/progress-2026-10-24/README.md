# Slide báo cáo tiến độ tuần — 24/10/2026

Mở `index.html` bằng Edge/Chrome/Firefox. 19 slide, khổ 1920×1080, tự co theo cửa sổ. Giao diện lấy từ
template `docs/slides/seminar-2026-10/` (Swiss Modern, font Archivo + Nunito; offline thì hiện bằng font hệ thống).

- `←` / `→`, Page Up / Page Down, Space, cuộn chuột, vuốt: chuyển slide; `Home` / `End`: đầu / cuối; `#5` trên URL mở slide 5.
- `E` (hoặc góc trên-trái): sửa chữ trực tiếp; `Ctrl+S` lưu vào trình duyệt.
- In / PDF: Ctrl+P, bật in nền, mỗi slide một trang.

## Nội dung

Mở đầu → kế hoạch 7 luồng song song → mô hình dự báo (H1 chạy lại, thời tiết và pH, mưa → cảm biến, xác suất
sự kiện nhiệt, mô hình nền) → chạy thật (shadow runner, bảng chấm điểm, lỗi mô hình 15 phút cũ) → giao diện
(bản đồ mặc định, 6 lớp thời tiết – thủy văn, nguồn dữ liệu, độ sâu và tô bóng đáy, độ phủ bản tin, nhật ký sự
kiện) → chất lượng dữ liệu sensor → mốc thời gian → tổng kết → tuần tới và việc cần quyết định.
Mỗi slide tính năng theo bố cục Vấn đề · Giải pháp · Kết quả · Còn lại · Hướng tiếp; chân slide ghi mã RL / decisions.

Số liệu lấy từ `docs/research-log.md` (RL-48 → RL-60), `docs/decisions.md` (#23 – #26), `experiments/RESULTS.md`
và kiểm tra mô hình runtime 15 phút ngày 24/10 (slide 7, chưa có RL riêng). Slide 9 (mô hình nền, luồng B) ghi
“đang tổng hợp”: cập nhật khi có kết quả.

## Ảnh demo (`assets/`)

Chụp từ research-map chạy Docker đầy đủ (api, worker, Postgres, frontend :8083) lúc ~14:40, 24/10/2026, dữ liệu live
(GreenLab, Open-Meteo, Copernicus Marine), Playwright 1440×900 ×1,5.

| Ảnh | Nội dung |
| --- | --- |
| `map-default.jpg` | Bản đồ giám sát mặc định: vùng HSI + hiện trạng, độ sâu GEBCO, thẻ cảm biến |
| `f-wind/wave/current/sea/sst/air.jpg` | Sáu lớp thời tiết – thủy văn (tắt dải độ sâu để thấy màu) |
| `map-depth-shade.jpg` | Dải độ sâu + đường đẳng sâu + tô bóng địa hình đáy |
| `page-forecast.jpg`, `page-scorecard.jpg` | Trang H1: dự báo shadow trực tiếp, bảng chấm điểm (0 dự báo đã chấm lúc chụp) |
| `page-weather.jpg` | Trang H2: độ phủ bản tin 7 ngày, thẻ đủ dữ liệu B5 |
| `page-events.jpg` | Trang Nhật ký sự kiện (chưa có sự kiện) |

## Tệp

- `index.html` — trình chiếu độc lập (CSS/JS nội tuyến), dựng bằng `source/build.py`.
- `source/slides.html` — nội dung 19 slide; `source/extra.css` — CSS thêm (ảnh, biểu đồ skill, lưới 6 lớp).
- Sửa xong chạy lại: `.venv\Scripts\python docs\slides\progress-2026-10-24\source\build.py`.
