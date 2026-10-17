# Slide báo cáo tiến độ 4 hướng — 17/10/2026

Mở `index.html` bằng Edge/Chrome/Firefox. 16 slide, khổ 1920×1080, tự co theo cửa sổ.

- `←` / `→`, Page Up / Page Down, Space: chuyển slide; `Home` / `End`: đầu / cuối; `#5` trên URL mở slide 5.
- `N`: ghi chú thuyết trình; `G`: mục lục; `F`: toàn màn hình; `Esc`: đóng ghi chú, mục lục.
- Nút **In / PDF**: in mỗi slide một trang (bật in nền, tắt header/footer của trình duyệt).
- Font Be Vietnam Pro tải từ Google Fonts; khi offline chữ hiển thị bằng Arial.

## Cấu trúc

Mở đầu (kế hoạch 1 → 2 ‖ 3 → 4, 6 thuật ngữ, danh sách công việc) → 10 slide công việc, mỗi slide cùng bố cục
**1 Vấn đề · 2 Giải pháp · 3 Kết quả · 4 Vấn đề còn lại · 5 Hướng tiếp** → bảng tổng kết → hướng triển khai và việc cần hỗ trợ.

Số liệu lấy từ `docs/research-log.md` (RL-01 → RL-28) và `experiments/RESULTS.md`; chân mỗi slide ghi mã RL.
Đã gồm kết quả H4.6 (thang ngày, lớp ngưỡng, RL-27) và IRLON (RL-28).

## Tệp

- `index.html` — trình chiếu độc lập (CSS/JS nội tuyến).
- `assets/` — 2 ảnh chụp research-map (trang H4 Việt Nam, H4 kiểm chứng quốc tế · USGS San Francisco).
- `source/` — bản nguồn dạng Slides artifact (`deck.json` + `slides/<id>.html`), dùng để sửa rồi dựng lại.
