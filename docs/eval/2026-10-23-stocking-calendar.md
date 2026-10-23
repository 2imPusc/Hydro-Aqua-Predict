# Lịch thả giống cá giò theo lý thuyết (Cát Bà, NB1)

**Ngày:** 23/10/2026. **Trạm:** `06M26042804`. **Trạng thái:** thuần lý thuyết + dữ liệu công khai; shadow, không điều khiển cảnh báo.
**Mã:** `experiments/stocking_calendar.py` (test: `tests/test_stocking_calendar.py`). **Lần chạy:** `artifacts/experiments/stocking-calendar-20261023c/`. **Thay thế** `stocking-calendar-20261023b` (lạnh chỉ là một trọng số; tháng 1 bị xếp "tốt" 0.74) và `stocking-calendar-20261023`.

> **Không có ground truth.** Không có số liệu tăng trưởng hay tỷ lệ sống theo ngày thả. Đây là bảng rủi ro kỳ vọng từ khí hậu quá khứ. Nó không được đánh giá, không phải dự báo và không phải khuyến cáo cho người nuôi.

## 1. Cách làm

- Mỗi tuần ISO thả (1–52) và mỗi chu kỳ nuôi, lấy trung bình trên 35 năm thả 1991–2025 (mọi cửa sổ đều đủ dữ liệu, `n_years = 35`). "10 năm cuối" = 2016–2025.
- **Chu kỳ nuôi: 26 và 39 tuần là kịch bản, chưa có trích dẫn.** Chưa tra tài liệu về thời gian nuôi cá giò lồng ở Việt Nam. Cá giống nhỏ thường cần dài hơn 26 tuần để đạt cỡ thương phẩm. Cần người nuôi xác nhận.
- **Giai đoạn đầu:** 8 tuần đầu sau thả (cá nhỏ, dễ tổn thương nhất). **Không chồng lấp:** các thành phần nóng, lạnh, bão, tăng trưởng tính trên tuần 9 đến hết chu kỳ; 8 tuần đầu chỉ vào thành phần "giai đoạn đầu" (trọng số hiệu dụng đúng bằng 0.20, không cộng đôi).
- **Nhiệt độ:** NOAA OISST ô 20.625 N 107.125 E, cộng độ lệch cảm biến − OISST. Độ lệch gốc +0.30 °C (trung vị 129 ngày hè–thu 2026; p90 +1.18). Độ lệch này chỉ đo vào mùa nóng, nhưng được áp cho cả mùa lạnh. Đó là một giả định.
- **Bão:** các lượt bão IBTrACS (`storm-hindcast-20261023f`), gió tại lồng `site_beaufort` ≥ cấp 8 và ≥ cấp 6. Dữ liệu là best-track (oracle), không phải dự báo. Ngày lấy theo UTC.
- **Ngưỡng:**

| Mục | Ngưỡng | Nguồn |
| --- | --- | --- |
| Nóng (theo dõi / stress) | ≥ 31 / ≥ 33 °C | Sun & Chen 2014; doc 27 |
| Lạnh nặng | < 18 °C | `cobia_thresholds.json` (18 °C → điểm 0.5) |
| Lạnh | < 20 °C | **giả định của nhóm, không có trích dẫn** |
| Ngày phù hợp tăng trưởng | 25–30 °C | `cobia_thresholds.json` (điểm 1.0) |

- **OISST tối đa 31.93 °C.** Với độ lệch +0.30, số ngày ≥ 33 °C bằng 0 ở mọi cửa sổ. Cột "stress" chỉ có nghĩa ở ca độ lệch +1.18.

## 2. Lạnh là ràng buộc, không chỉ là trọng số

Lý do sửa: ở bản `b`, tháng 1 (26 tuần) được 0.74 "tốt" vì lạnh 8 tuần đầu chỉ đóng góp ≤ ≈ 0.07 vào điểm tương đối. Với cá giống, thả vào nước lạnh là trường hợp xấu nhất. Căn cứ (Nhu et al. 2011, *Aquaculture* 315:20–25, cá giò lồng miền Bắc VN): cá ngừng ăn < 18 °C, ngừng lớn < 22 °C; ≥ 5 tuần ở ~15 °C gây chết hàng loạt (tháng 1–2/2008); lạnh > 2 tuần dẫn đến nhiễm nấm/vi khuẩn. Ba ngưỡng này (18/22/15 °C) và quy tắc 14 ngày là cơ sở của ba bước dưới đây; ngưỡng 20 °C của bản `b` vẫn là giả định của nhóm.

1. **Cổng khả thi lúc thả.** Tuần thả là *khả thi* nếu nhiệt độ trung bình 8 tuần đầu ≥ 22 °C trong ≥ 80 % số năm (tham số `--gate-share`, mặc định 0.80). Không khả thi → không có điểm; tháng có < 50 % tuần khả thi có lớp **"tránh (lạnh lúc thả)"** (`avoid_cold`).
2. **Cờ tử vong do lạnh theo chu kỳ.** Chu kỳ bị gắn cờ nếu trong *toàn bộ* thời gian nuôi có ≥ 14 ngày liên tiếp < 18 °C **hoặc** có một ngày ≤ 15 °C. Báo cáo là tỷ lệ năm bị gắn cờ (`cold_flag_share`). **Phạt: điểm −= 0.5 × `cold_flag_share`** (nặng: điểm tương đối của các tuần khả thi trải khoảng 0.3, nên một chu kỳ bị gắn cờ ở mọi năm bị đẩy ra khỏi nhóm đầu). Mức 0.5 là quy ước của nhóm, không hiệu chỉnh.
3. **Điểm tương đối chỉ cho tuần khả thi.** Min–max và trọng số (mục 3) chỉ tính trên tuần qua cổng. Điểm cuối = điểm tổng hợp − phạt cờ. Độ bền theo trọng số (mục 6) cũng áp cổng và phạt.

Ca nhạy cảm `winter_-1.5`: OISST (ô 0.25° ngoài khơi) **đánh giá thấp độ lạnh trong vịnh** — nó không thấy nước 15 °C năm 2008 và < 10 °C năm 2016 đã ghi nhận. Ca này trừ thêm 1.5 °C vào tháng 12–3 (giả định, chưa đo). Ca gốc không có hiệu chỉnh này nên cờ lạnh gần như không bao giờ bật (xem 4.2).

## 3. Điểm tổng hợp (tuần khả thi)

Mỗi rủi ro được đưa về 0–1 bằng min–max **qua các tuần khả thi** (tuần ISO 11–47; với từng chu kỳ). Điểm = 1 − Σ trọng số × rủi ro − 0.5 × cờ lạnh. Điểm cao = tuần thả tốt hơn *so với các tuần khả thi khác*.

| Thành phần | Định nghĩa | Trọng số gốc |
| --- | --- | --- |
| nóng (tuần 9→hết) | ngày ≥ 31 °C + ngày ≥ 33 °C (ngày ≥ 33 tính đôi) | 0.20 |
| lạnh | ngày < 20 °C + ngày < 18 °C (tính đôi) | 0.20 |
| bão | số lượt ≥ cấp 8 + 0.25 × số lượt cấp 6–7 | 0.25 |
| giai đoạn đầu | trung bình của 3 rủi ro (nóng, lạnh, bão) trong 8 tuần đầu | 0.20 |
| tăng trưởng | 1 − (số ngày 25–30 °C, min–max) | 0.15 |

Trọng số do nhóm chọn, không có cơ sở thực nghiệm; mục 6 kiểm tra độ bền. Điểm là xếp hạng tương đối, **không phải rủi ro tuyệt đối**. Phần "lạnh" của điểm tổng hợp giờ chỉ phân biệt trong tập tuần khả thi; việc loại trừ lạnh nằm ở cổng và cờ.

## 4. Kết quả

Tuần ISO khả thi: **11–47** (tuần 11: 86 % năm đạt, tuần 47: 83 %; tuần 10: 51 %, tuần 48: 60 %). Tuần 1–10 và 48–52 bị loại ở cả hai chu kỳ (cổng chỉ phụ thuộc 8 tuần đầu).

### 4.1 Bảng 12 tháng (theo từng chu kỳ)

Lớp: **tốt** ≥ 0.55, **thận trọng** 0.40–0.55, **tránh** < 0.40 (điểm tuyệt đối, trung bình tuần khả thi trong tháng); **tránh (lạnh lúc thả)** = < 50 % tuần khả thi. "Khả thi" = tỷ lệ tuần của tháng qua cổng. "Cờ" = trung bình `cold_flag_share` các tuần trong tháng (ca gốc, OISST + 0.30 °C). Mốc là quy ước của nhóm.

| Tháng | Khả thi | 26 tuần: điểm | lớp | cờ | 39 tuần: điểm | lớp | cờ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 % | – | tránh (lạnh lúc thả) | 0.03 | – | tránh (lạnh lúc thả) | 0.03 |
| 2 | 0 % | – | tránh (lạnh lúc thả) | 0.01 | – | tránh (lạnh lúc thả) | 0.01 |
| 3 | 60 % | 0.545 | thận trọng | 0.00 | 0.499 | thận trọng | 0.00 |
| 4 | 100 % | 0.532 | thận trọng | 0.00 | 0.488 | thận trọng | 0.00 |
| 5 | 100 % | 0.565 | tốt | 0.00 | 0.423 | thận trọng | 0.01 |
| 6 | 100 % | 0.642 | tốt | 0.00 | 0.383 | tránh | 0.03 |
| 7 | 100 % | 0.716 | tốt | 0.00 | 0.434 | thận trọng | 0.03 |
| 8 | 100 % | 0.710 | tốt | 0.01 | 0.533 | thận trọng | 0.03 |
| 9 | 100 % | 0.643 | tốt | 0.03 | 0.585 | tốt | 0.03 |
| 10 | 100 % | 0.625 | tốt | 0.03 | 0.534 | thận trọng | 0.03 |
| 11 | 80 % | 0.645 | tốt | 0.03 | 0.426 | thận trọng | 0.03 |
| 12 | 0 % | – | tránh (lạnh lúc thả) | 0.03 | – | tránh (lạnh lúc thả) | 0.03 |

Tháng 1 giờ là "tránh (lạnh lúc thả)" thay vì "tốt 0.74". Tháng 3 và 11 là tháng biên (3: chỉ tuần 11–13 qua cổng; 11: tuần 47 qua, tuần 48 trượt); không nên thả vào các tuần biên nếu không có kiểm chứng tại chỗ.

Khoảng điểm theo lớp (`class_ranges.csv`): 26 tuần: tốt 7 tháng (0.565–0.716; tháng 5–11), thận trọng 2 (0.532–0.545; tháng 3, 4), tránh_lạnh 3 (tháng 12, 1, 2). 39 tuần: tốt 1 (tháng 9, 0.585), thận trọng 7 (0.423–0.534), tránh 1 (tháng 6, 0.383), tránh_lạnh 3.

Cách đọc:

- **26 tuần:** trong các tháng khả thi, điểm cao nhất ở tháng 7–8 (0.71–0.72), giảm dần về tháng 4. Chu kỳ này thả giữa hè và kết thúc vào mùa đông.
- **39 tuần:** chỉ tháng 9 "tốt" (0.585); tháng 8 và 10 (0.53) sát mốc 0.55; tháng 6 "tránh" vì chu kỳ qua mùa bão rồi mùa đông.
- Hình dạng các tháng 4–11 gần như giữ nguyên bản `b` (thang min–max đổi nhẹ vì chỉ tính trên tuần khả thi); thay đổi cốt lõi là loại tháng 12–2.

### 4.2 Cờ tử vong do lạnh

- **Ca gốc: cờ gần như không bật.** `cold_flag_share` ≤ 0.03 ở mọi tuần (= 1/35 năm). OISST + 0.30 °C hiếm khi giữ < 18 °C trong 14 ngày và không bao giờ ≤ 15 °C (min toàn chuỗi 16.05 °C ngày 21/02/2012). Vì vậy ở ca gốc phạt cờ chỉ ≈ 0.015 và **cổng khả thi mới là cơ chế loại tháng 12–2**.
- **Ca `winter_-1.5`:** `cold_flag_share` = 0.54 cho mọi chu kỳ bao trùm tháng 12–3 (26 tuần: thả tháng 9–12; 39 tuần: thả tháng 6–12), 0.31–0.32 (26 tuần thả tháng 2 hoặc tháng 8), 0.07 (26 tuần thả tháng 3); số theo tháng ở `cold_by_month.csv`. Tức nếu vịnh lạnh hơn OISST 1.5 °C, **hơn một nửa số năm** có ≥ 14 ngày < 18 °C hoặc ngày ≤ 15 °C trong mùa đông, và phạt ≈ 0.27 điểm.
- Hệ quả: với 39 tuần, mọi tháng thả từ tháng 6 đến 12 đi qua mùa đông và bị gắn cờ ≈ 0.54 trong ca nhạy cảm; top-3 chuyển sang tuần 13–15 (thả cuối tháng 3 đến đầu tháng 4). Với 26 tuần, top-3 chuyển sang tuần 28–30 (kết thúc trước tháng 2).

### 4.3 Cửa sổ dẫn đầu (ca gốc)

Tuần cùng nhóm = điểm cách đỉnh ≤ 0.03; xếp hạng bên trong nhóm là nhiễu.

- **26 tuần: nhóm tuần 28–33 (điểm 0.711–0.737; đỉnh tuần 31 0.737, 30: 0.732, 32: 0.732), thả cuối tháng 7 đến giữa tháng 8.** Cuối chu kỳ rơi vào tháng 1–2, cờ lạnh 0.00–0.03. Khác bản `b` (tuần 50–2, thả mùa đông).
- **39 tuần: nhóm tuần 35–40 (điểm 0.564–0.593; đỉnh tuần 38 0.593, 37: 0.590, 36: 0.584), thả giữa tháng 9.** Giống bản `b` (thả sau mùa bão chính, trong vùng qua cổng).
- Tăng trưởng không phải điểm mạnh (39 tuần: tuần 38 có ≈ 108 ngày 25–30 °C; 26 tuần: tuần 31 có ≈ 85 ngày). Cửa sổ xuân (tuần 14–15, 39 tuần, 154 ngày 25–30 °C) có điểm 0.51, thấp hơn do nóng và bão.

## 5. Độ nhạy

| Ca | Top-3 (26 tuần) | Top-3 (39 tuần) |
| --- | --- | --- |
| gốc (+0.30) | 31, 30, 32 | 38, 37, 36 |
| offset 0 | 31, 30, 29 | 38, 37, 36 |
| offset +1.18 | 31, 32, 30 | 37, 36, 38 |
| ngưỡng −0.5 | 31, 32, 30 | 37, 36, 38 |
| ngưỡng +0.5 | 32, 31, 29 | 38, 37, 39 |
| 10 năm cuối | 31, 32, 30 | 37, 36, 35 |
| gió bão 0.88 | 31, 30, 32 | 38, 37, 36 |
| **mùa đông −1.5 °C** | **30, 28, 29** | **14, 13, 15** |

- Ở mọi ca không phải mùa đông, top-3 nằm trong tuần 29–33 (26 tuần) và 35–39 (39 tuần).
- **Ca `winter_-1.5` đổi kết luận 39 tuần** (top-3 chuyển từ cuối hè sang tuần 13–15, trùng 0/3 với gốc). Với 26 tuần, trùng 1/3 nhưng vẫn trong 2 tuần của top-3 gốc. Kết luận 39 tuần **phụ thuộc vào việc OISST có đánh giá thấp độ lạnh trong vịnh hay không**; chưa có dữ liệu để quyết định.

## 6. Độ bền theo trọng số

7 bộ trọng số gọi tên + 1,000 bộ Dirichlet(1), seed 20261023, áp cổng và phạt cờ.

- **Không có tuần nào đạt ngưỡng "bền" (top-5 trong ≥ 80 % bộ trọng số).** `robust_weeks` rỗng cho cả hai chu kỳ.
- Chia sẻ top-5 lớn nhất: 26 tuần: 0.40 (tuần 29), 0.37 (tuần 30), 0.34 (tuần 31). 39 tuần: 0.52 (tuần 13), 0.51 (tuần 14), 0.49 (tuần 15), 0.47 (tuần 12) — cửa sổ xuân thắng nhiều bộ trọng số nhưng không phải ở trọng số gốc (0.42 cho tuần 37, 0.41 cho tuần 36/38).
- Kết luận: thứ hạng từng tuần do trọng số quyết định; chỉ nói về nhóm tuần (mùa).

## 7. Hạn chế

1. **Không có ground truth** (tăng trưởng, tỷ lệ sống, nhật ký thả). Không có đánh giá.
2. **OISST đánh giá thấp lạnh trong vịnh** (bỏ sót 15 °C năm 2008 và < 10 °C năm 2016). Ca gốc vì thế gần như không bật cờ; ca `winter_-1.5` (−1.5 °C là giả định, không đo) bật cờ ở 54 % năm. Kết luận về mùa đông và chu kỳ 39 tuần nhạy với hiệu chỉnh này.
3. Cổng 22 °C và quy tắc cờ 14 ngày / 18 °C / 15 °C lấy từ Nhu et al. 2011 (một nghiên cứu, một vùng), áp cho SST ngày trung bình ô 0.25°. Ngưỡng 20 °C của điểm "lạnh", hệ số phạt 0.5 và cổng 80 % là quy ước của nhóm.
4. Chu kỳ 26/39 tuần là kịch bản, chưa trích dẫn. Cỡ giống và thời gian ra thị trường chưa tra.
5. Độ lệch +0.30 °C chỉ từ một mùa hè–thu 2026, áp cho mùa đông.
6. Bão: best-track oracle; chỉ 0.62 lượt ≥ cấp 8 mỗi năm nên trung bình theo tuần rất thưa. Gió tại lồng là cận dưới.
7. Min–max + trọng số tự chọn: điểm tương đối, nhạy trọng số (mục 6). Mốc lớp 0.55/0.40 và dung sai 0.03 là quy ước.
8. Chưa xét độ mặn, DO, bệnh cụ thể, sóng, mưa lớn, giá giống/bán, thị trường. Cờ lạnh chỉ là chỉ báo, không phải tỷ lệ chết.
9. Không dùng cho khuyến cáo thật. Cần người nuôi và chuyên gia xem lại.

## 8. Tệp đầu ra

`ranking_26w.csv`, `ranking_39w.csv` (chỉ số kỳ vọng, rủi ro, điểm, hạng, chia sẻ top-3/top-5, cột `last10_*`; cột `early_*` = 8 tuần đầu, cột không tiền tố = tuần 9 đến hết chu kỳ), `month_classes.csv` (kèm `feasible_frac_*`), `class_ranges.csv`, `sensitivity_top3.csv`, `cold_by_month.csv` (cổng, cờ, tỷ lệ khả thi theo tháng cho mọi ca), cột `feasible` trong ranking, `manifest.json` (tham số, hash đầu vào, trọng số, độ ổn định).
