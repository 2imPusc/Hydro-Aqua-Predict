# Slide HTML báo cáo tiến độ — 26/09/2026

Mở `index.html` trực tiếp bằng Edge/Chrome/Firefox. File tự chứa CSS, JavaScript và minh họa SVG, không cần Internet hoặc cài thư viện. Có 10 slide chính (~11 phút) và 2 slide dự phòng.

- `←` / `→`, Page Up / Page Down, hoặc nút điều khiển: chuyển slide.
- `N`: mở ghi chú thuyết trình; `Esc`: đóng ghi chú.
- `G`: mục lục, chọn slide bất kỳ. `Home` / `End`: đầu / cuối.
- `F`: toàn màn hình; có thể dùng `F11` của trình duyệt.
- Nút **In / PDF**: in toàn bộ 12 slide, không in ghi chú. Chọn lưu PDF, bật in nền, tắt header/footer của trình duyệt; xem preview trước khi lưu.
- Ghi chú hiện trên chính màn hình trình chiếu khi mở. Nếu đang chia sẻ màn hình, đóng ghi chú trước khi tiếp tục trình bày.

## Phạm vi kết quả

Slide 6 dùng **artifact hồi cứu đã có**, không dùng benchmark vòng sửa của Gemini. Đã đối chiếu ba hàng Temperature/Ridge/B1:

| Chân trời | MAE Ridge | MAE persistence | Giảm MAE |
| --- | ---: | ---: | ---: |
| 15 phút | 0.1437839529 | 0.1798074732 | 20.03% |
| 30 phút | 0.1506474753 | 0.1851544214 | 18.64% |
| 60 phút | 0.1685164469 | 0.2041286509 | 17.45% |

Nguồn: `artifacts/experiments/forecast-v2/detailed-temperature-b1-ridge/detailed_lockbox_overall.csv` và `manifest.json`. Giai đoạn nguồn 29/05–26/07/2026; tập kiểm tra 14 ngày cuối. Kết quả không chứng minh giá trị B5 và cần tái xác nhận sau khi sửa chuẩn hóa dữ liệu.

Slide 4: 80.670 timestamp của `load_cached_history('06M26042804')` đã kiểm tra; cuối dữ liệu `2026-09-04T23:05:55Z` = 05/09/2026 06:05:55 giờ Việt Nam. Không hiểu là 80.670 mẫu độc lập hay chuỗi liên tục. Timeline chỉ là minh họa, đã ghi trên slide.

Slide 8: rà soát artifact `weather-risk-pilot/round3/20260926T014229Z`: 96.144 timestamp trước xuất, 80.723 timestamp phân biệt sau khi cắt mili giây. Hai thời điểm sensor/weather 23:05:55 và 23:06:25 UTC ngày 04/09 là ví dụ cụ thể từ lần kiểm tra, không thay cho đánh giá toàn bộ coverage.

Slide 3, 5, 7: mô tả trạng thái mã nguồn và kết quả kiểm tra trong cuộc trao đổi ngày 26/09; các phần có mã vẫn có thể cần kiểm chứng. Phần risk tổng hợp/B5 chưa nghiệm thu, chưa gửi notification. Không khẳng định hệ thống đã dự báo được tỷ lệ chết hoặc sự phù hợp sinh học.

## Nhịp trình bày gợi ý

1. Mục tiêu (45s); 2. Bài toán (55s); 3. Kiến trúc (70s); 4. Dữ liệu (70s); 5. Tiến độ (50s); 6. Kết quả (85s); 7. Thời tiết (65s); 8. Vấn đề (85s); 9. Kế hoạch (70s); 10. Xin ý kiến (70s). Tổng ~11 phút. Hai slide cuối chỉ dùng khi hỏi đáp.

Các ghi chú thuyết trình đầy đủ nằm trong từng phần `<aside class="notes">` của HTML và có thể mở bằng phím N. Tên tác giả Đỗ Minh Phúc được đối chiếu với nguồn LaTeX sẵn có trong repo; MSSV 20225064.
