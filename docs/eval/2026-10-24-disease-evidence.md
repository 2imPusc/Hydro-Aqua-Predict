# Bằng chứng công khai về bệnh / cá chết hàng loạt (cá biển lồng, miền Bắc) — đánh giá 2026-10-24

**Trạng thái:** bổ sung dữ liệu cho `docs/eval/2026-10-23-disease-risk.md`. Chỉ số vẫn là lý thuyết, shadow, `used_by_alerts: False`. **Nguồn:** `docs/references/disease-sources.md`. **Dữ liệu:** `experiments/disease_events.csv` (12 dòng, thêm 6). **Run:** `artifacts/experiments/disease-hindcast-20261024/` (chạy lại `experiments/disease_hindcast.py --stamp 20261024`, cùng ERA5 thật và OISST như run `20261023b`).

## 1. Kết luận ngắn

- Thu thêm **6 sự kiện** từ báo chí (không có số liệu chính thức). Tổng 12 sự kiện, 11 được chấm (Phù Long 2026 vẫn loại: nghi nước thải).
- Sự kiện có **tên mầm bệnh + độ chính xác ngày ≤ 2 tuần: 1** (Cái Chiên 2025, VNN có phiếu xét nghiệm, cửa sổ ước tính ~16 ngày). Thêm Lan Hạ 2018 nếu coi "nấm mang" là tên (cửa sổ ~7 ngày ước tính) thì 2. Còn thiếu so với ngưỡng 5 (`MIN_EVENTS`).
- **Kết luận chỉ số không đổi:** `no_skill_over_climatology` (trúng mức "cao" 8/11 = 0.727, kỳ vọng theo khí hậu 0.789), giờ với n = 11 thay vì 5. Dịch ±1 °C cho cùng 8/11 và cùng kết luận (`robust_to_shift_1c: true`; run trước là không bền). Phần "bệnh có tác nhân" vẫn `insufficient_evidence`.
- Lý do kết luận không đổi: 8 sự kiện trúng đều ở mùa ấm (T6-T11), khi xác suất khí hậu trong cửa sổ ≈ 1 → "trúng" không có thông tin. Ba sự kiện không trúng mức "cao" (rét 2008, rét Thái Bình 2016, Cái Chiên 2025) đều là rét / giao mùa và đều có tín hiệu nhóm lạnh (0.60 / 0.25 / 0.57 trên OISST; 1.0 / 0.60 / 0.60 trên ERA5 không khí) — ba mẫu, không đủ khẳng định.

## 2. Bảng sự kiện (12)

| Sự kiện | Tỉnh | Thời gian | Độ chính xác | Nhóm nguyên nhân | Mầm bệnh nêu tên | T nước OISST trong cửa sổ (°C) | Mức max | P khí hậu "cao" |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cold-north-2008 | miền Bắc | T1-T2/2008 | tháng | rét + nấm/vi khuẩn thứ phát | chung chung | 17.4-22.9 | 1 | 0.273 |
| nghison-2011 (mới) | Thanh Hóa | 25/7-30/9/2011 | tháng | mầm bệnh | Vibrio spp, sán lá đơn chủ | 28.3-30.9 | 2 | 1.0 |
| lachbang-2013 (mới) | Thanh Hóa | 24/7/2013 | ngày | độ mặn giảm (xả lũ) | không | 29.7-30.1 | 2 | 0.977 |
| cold-thaibinh-2016 | Thái Bình | 22-27/1/2016 | ngày | rét | không | 20.2-21.5 | 1 | 0.023 |
| campha-bendo-2016 | Quảng Ninh | 9-15/8/2016 (nguồn mới: 11-13/8) | ngày | thiếu ô xy | không | 30.0-31.9 | 2 | 1.0 |
| nghison-2016 (mới) | Thanh Hóa | 8/9/2016 | ngày | tảo nở hoa | không | 30.4-31.8 | 2 | 1.0 |
| lanha-2018 | Hải Phòng | 17-24/10/2018 | ~1 tuần | nấm mang + giao mùa | chung chung | 26.7-29.0 | 2 | 1.0 |
| catba-2024 (mới) | Hải Phòng | T12/2023-30/3/2024 | tháng | mầm bệnh (sơ bộ) | Vibrio (sơ bộ) | 18.2-26.2 | 2 (đầu cửa sổ) | 0.955 |
| baitulong-2024 (mới) | Quảng Ninh | ~5/10-15/11/2024 | tháng | bệnh ghép | không (ký sinh trùng, VK, virus chung) | 25.9-29.6 | 2 | 1.0 |
| caichien-2025 (mới) | Quảng Ninh | ~28/3-12/4/2025 | ~2 tuần | mầm bệnh (xét nghiệm) | VNN | 18.0-22.8 | 1 | 0.455 |
| vandon-2025 | Quảng Ninh | T10/2025 (nguồn mới: từ 13/10) | tháng | độ mặn giảm | không | 27.5-30.3 | 2 | 1.0 |
| phulong-2026 (không chấm) | Hải Phòng | 21/6-10/7/2026 | ~tuần | nghi nước thải | không | 30.0-30.9 | 2 | 1.0 |

Nhiệt độ ngày cụ thể (OISST, ô Cát Bà): Nghi Sơn 25/7/2011 30.3; Lạch Bạng 24/7/2013 29.7; Nghi Sơn 8/9/2016 31.0 (trên vai trên, mức 1); Cát Bà 1/12/2023 24.7 và 28/3/2024 21.7; Cái Chiên 5/4/2025 20.5; Bái Tử Long 20/10/2024 28.4.

## 3. Phân bố

- **Theo nhóm nguyên nhân (12):** mầm bệnh có tên 3 (Nghi Sơn 2011, Cát Bà 2024, Cái Chiên 2025); bệnh/nhiễm nêu chung chung 3 (rét 2008, Lan Hạ 2018, Bái Tử Long 2024); môi trường 5 (rét 1, thiếu ô xy 1, độ mặn 2, tảo nở hoa 1); nghi ô nhiễm 1. Trong ba sự kiện có tên mầm bệnh, chỉ Cái Chiên có phiếu xét nghiệm ghi trong bài.
- **Theo tỉnh:** Quảng Ninh 4, Hải Phòng 3, Thanh Hóa 3, Thái Bình 1, "miền Bắc" 1. **Theo năm:** 2008, 2011, 2013, 2016 (×3), 2018, 2023/24, 2024, 2025 (×2), 2026.
- **Theo tháng (tháng bắt đầu):** T1 (2), T3-T4 (2: Cát Bà cuối cửa sổ, Cái Chiên), T6-T9 (5), T10-T11 (3). Mùa ấm T6-T11 chiếm 8/12 — nhưng đây cũng là mùa luôn "cao" theo chỉ số, và thiên lệch báo chí (cá chết ồ ạt vào mùa bán cá, ít người đưa tin dịch lẻ tẻ).
- **Nhiệt độ:** hầu hết sự kiện mùa ấm xảy ra ở 28-31 °C (phù hợp nhóm vibrio/streptococcus). Bài *S. iniae* trên cá dìa (Hoai et al. 2026, 46 trại Quảng Ninh/Hải Phòng) đo 28,2-33,2 °C lúc lấy mẫu, cùng khoảng nhiệt. Hai sự kiện có mầm bệnh nêu tên lại ở nước mát: Cát Bà 2024 (~22-25 °C) và Cái Chiên 2025 (~18-23 °C, VNN); sensor Cát Bà chưa có mùa đông nên chưa kiểm được.

## 4. Chạy lại hindcast

`disease_hindcast.py` đọc `disease_events.csv` cố định (không có tham số tệp sự kiện), nên chỉ cần `--stamp 20261024`; ghi vào thư mục mới, không đụng run cũ. Hai hằng số trong script (`PATHOGEN_ATTRIBUTED`, `NON_ENVIRONMENTAL`) chưa cập nhật nên `n_pathogen_attributed` vẫn 2, và `lachbang-2013` (cửa sông) không bị loại. Số "mầm bệnh có tên" ở trên là đếm tay. Nếu muốn kết quả máy đọc: thêm `nghison-2011`, `catba-2024`, `caichien-2025` vào `PATHOGEN_ATTRIBUTED` (script không thuộc phạm vi lần này). Cột mới trong CSV (`pathogen_named`, `cause_class`, `date_precision`) cho phép lọc thay vì hằng số.

## 5. Hạn chế

- Tất cả là báo chí hoặc bài đăng lại; chỉ Cái Chiên có phiếu xét nghiệm, Cát Bà là kết quả sơ bộ, Nghi Sơn 2011 là kết luận Sở NN&PTNT. Không có số liệu Cục Thú y/Tổng cục Thủy sản/RIA1 (không mở được).
- Ngày: 5/12 sự kiện chính xác tới ngày hoặc khoảng tuần (Thái Bình, Bến Do, Lạch Bạng, Nghi Sơn 2016, Lan Hạ), 5 chỉ tới tháng, Cái Chiên ~2 tuần, Phù Long ~3 tuần. Các ngày bắt đầu của Cái Chiên, Bái Tử Long, Cát Bà là ước tính từ cụm từ.
- OISST ô Cát Bà (20.625 N 107.125 E) dùng cho cả Thanh Hóa (~1.3° vĩ độ về phía nam; vụng kín như vụng Ngọc có thể lệch nhiệt, chưa đo) và Cái Chiên (~0.9° về phía bắc). Cần OISST đúng ô trước khi dùng các hàng này để hiệu chỉnh.
- Chọn mẫu: chỉ những vụ báo chí đưa tin; không có sự kiện nào làm mẫu đối chứng (ngày không có dịch). Hindcast "trúng" không thể cho thấy kỹ năng khi nền xác suất ≈ 1.
- Lạch Bạng 2013 xảy ra ở âu thuyền cửa sông (độ mặn), không tiêu biểu cho vùng nuôi vịnh mở.
- Tìm kiếm không đầy đủ (xem `docs/references/disease-sources.md` mục 4).

## 6. Việc tiếp theo

1. Xin bản tin dịch bệnh / phiếu xét nghiệm từ Trạm Chẩn đoán bệnh động thực vật Quảng Ninh và Trung tâm Quan trắc môi trường và Bệnh thủy sản miền Bắc (chủ sở hữu có thể liên hệ; công khai không có).
2. Chọn thêm ngày đối chứng (không có dịch) từ nhật ký trại, nếu không chỉ số không thể đánh giá.
3. Cập nhật `PATHOGEN_ATTRIBUTED` / `NON_ENVIRONMENTAL` trong `disease_hindcast.py` và thêm một dòng `experiments/RESULTS.md` cho run `20261024` (chưa ghi theo yêu cầu nhiệm vụ).
4. Hiệu chỉnh OISST theo ô Thanh Hóa / Cái Chiên hoặc dùng ERA5 không khí đã hiệu chỉnh cho nhóm lạnh.
