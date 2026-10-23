# Slide báo cáo tiến độ Phase 1 — 23/10/2026

Mở `index.html` bằng Edge/Chrome/Firefox. 17 slide, khổ 1920×1080, tự co theo cửa sổ. Giao diện lấy từ
template `docs/slides/seminar-2026-10/` (Swiss Modern, font Archivo + Nunito; offline thì hiện bằng font hệ thống).

- `←` / `→`, Page Up / Page Down, Space, cuộn chuột, vuốt: chuyển slide; `Home` / `End`: đầu / cuối; `#5` trên URL mở slide 5.
- `E` (hoặc góc trên-trái): sửa chữ trực tiếp; `Ctrl+S` lưu vào trình duyệt.
- In / PDF: Ctrl+P, bật in nền, mỗi slide một trang.

## Nội dung

Mở đầu → bối cảnh (yêu cầu → đã làm, luồng xử lý) → cảnh báo theo trạm (demo trang cảnh báo, phát lại Yagi, trang
cấu hình admin, bảng ngưỡng mặc định) → bão (toàn vùng, thiệt hại, phơi nhiễm theo điểm) → nhiệt / rét / dịch bệnh,
lịch thả giống → bản đồ và dữ liệu (GEBCO, H3 mượt, Copernicus Marine) → tổng kết mức kiểm chứng → bước tiếp.
Mỗi slide tính năng theo bố cục Vấn đề · Giải pháp · Kết quả · Còn mở; chân slide ghi mã RL / decisions.

Số liệu lấy từ `docs/research-log.md` (RL-29 → RL-47), `docs/decisions.md` (#20 – #22) và `experiments/RESULTS.md`.

## Ảnh demo (`assets/`)

| Ảnh | Nguồn |
| --- | --- |
| `alerts-live.png`, `admin-default.png`, `exposure-roses.jpg`, `h3-after-smooth.jpg` | Chạy thật 23/10/2026 17:17: ECMWF Open Data 00 UTC + hazard runner với Open-Meteo, ghi vào runtime tạm (không phải `runtime/`); research-map chạy local không có Postgres nên ô sensor báo “không khả dụng”. |
| `alerts-replay-yagi.png` | Phát lại bão Yagi 2024 (dữ liệu tái phân tích dùng như dự báo), giao diện gắn nhãn “Phát lại / Bão DEMO”. |
| `admin-history.png` | Lịch sử phiên bản trong lần kiểm thử đầu-cuối (RL-47), ngưỡng thử, không phải mặc định. |
| `depth-before-sdb.jpg`, `depth-after-gebco.jpg`, `h3-before-grid.jpg` | Ảnh chụp trước / sau trong quá trình làm Track E (23/10/2026). |

## Tệp

- `index.html` — trình chiếu độc lập (CSS/JS nội tuyến), dựng bằng `source/build.py`.
- `source/slides.html` — nội dung 17 slide; `source/extra.css` — CSS thêm cho ảnh, bậc cảnh báo, lịch tháng.
- Sửa xong chạy lại: `.venv\Scripts\python docs\slides\progress-2026-10-23\source\build.py`.
