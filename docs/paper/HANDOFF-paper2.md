# Bàn giao phiên mới — Bài báo 2 (dạng nhẹ): dự báo khi thiết bị gặp sự cố

Ngày: 28/10/2026. Làm song song, nhẹ, dùng chung dữ liệu và mô hình với bài báo 1. Chỉ **thử nghiệm**, chưa viết bài.

## Đọc trước

1. `AGENTS.md`; `docs/paper/2026-10-27-sota-and-plan.md` (đề tài 2).
2. `docs/research-log.md`: RL-13 / RL-17 (pH trôi, QC pH), RL-57, RL-58, RL-64 (mô hình cây không ngoại suy),
   RL-66, RL-68, **RL-72** (bước nhảy thiết bị 31/07 NH4 ÷20 + TSS; 12/08 gián đoạn + COD; 16/09 NH4 ×6,7 + COD),
   RL-70 (đơn vị NH4).
3. Mã: `experiments/nh4_step_0731.py` (phát hiện bậc, chu kỳ thiết bị), `experiments/forecast_sensor_v2.py`,
   `experiments/transfer_forecast.py` (nạp NERRS), `experiments/foundation_zero_shot.py`.

## Câu hỏi nghiên cứu

Khi cảm biến ven biển gặp sự cố thật (trôi chậm, đổi thang đột ngột, bám bẩn, kẹt giá trị), cách nào giữ dự
báo và khoảng tin cậy đáng tin nhất: (a) bỏ qua, (b) đánh dấu thiếu + mặt nạ QC, (c) khởi động lại ngữ cảnh tại
điểm đổi chế độ, (d) thích nghi lúc chạy (FSNet / TAFAS / cập nhật online), (e) ACI cho khoảng tin cậy?

## Thiết kế (đăng ký trước)

- **Sự cố mẫu lấy từ NB1 (có thật):** đổi thang ÷20 tức thì (31/07), ×6,7 (16/09), trôi chậm pH (từ 19/09),
  bám bẩn TSS (07/06–31/07, mức tăng dần), kẹt 0 / kẹt trần (COD 0,0 và 558,8).
- **Chèn sự cố vào NERRS** (dữ liệu sạch, cờ `<0>`), vị trí ngẫu nhiên có hạt giống cố định, nhiều trạm → có
  "đáp án đúng" để chấm. NB1 dùng làm minh họa thật.
- **Chỉ số:** MAE / RMSE trong 0–24 h và 1–7 ngày sau sự cố, thời gian hồi phục (giờ tới khi sai số về mức
  trước sự cố), độ phủ PI80 sau sự cố, tỷ lệ phát hiện sự cố.
- **Mô hình:** ridge B4D, Chronos-Bolt / Chronos-2 (dùng chung với bài 1), có / không các cơ chế (a)–(e).
- **Luật "có ích":** giảm sai số 0–24 h ≥ 30 % so với (a) ở ≥ 2/3 loại sự cố, CI bootstrap theo sự cố không chứa 0;
  độ phủ PI80 về [0,75; 0,85] trong ≤ 24 h.

## Kế hoạch thử nghiệm

- **F1:** thư viện chèn sự cố + test (tái tạo đúng hình dạng 3 sự cố NB1 về biên độ / thời gian).
- **F2:** bộ phát hiện đổi chế độ (theo RL-72) + mặt nạ QC; chấm phát hiện trên sự cố chèn.
- **F3:** so (a)–(e) trên NERRS; sau đó áp lên NB1 thật.
- Thư mục chạy `paper2-<bước>-<YYYYMMDD>/`, NOTES.md, manifest; một dòng RESULTS, một mục RL mỗi bước.

## Quy tắc phối hợp

- Nhánh `paper/sensor-faults` (tạo từ `h1-ph-drift-followup`). Không push khi chưa được phép.
- Mã chỉ ở `experiments/paper2_*.py`, `tests/test_paper2_*.py`. Không sửa `core/`, `research-map/`, task Windows.
- Dùng lại mô hình / dữ liệu của bài 1 bằng cách import, không sao chép; không sửa file của bài 1 khi phiên đó đang chạy.
- CPU tối đa 1–2 lõi. Đưa vào runtime chỉ qua quyết định mới do chủ dự án duyệt.

## Câu mở đầu cho phiên mới (dán vào)

> Đọc `docs/paper/HANDOFF-paper2.md` và các tài liệu nó liệt kê. Tạo nhánh `paper/sensor-faults` từ
> `h1-ph-drift-followup`, rồi thực hiện bước F1 theo đúng quy tắc trong file. Báo cáo bằng tiếng Việt.
