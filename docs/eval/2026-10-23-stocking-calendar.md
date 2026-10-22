# Lịch thả giống cá giò theo lý thuyết (Cát Bà, NB1)

**Ngày:** 23/10/2026. **Trạm:** `06M26042804`. **Trạng thái:** thuần lý thuyết + dữ liệu công khai; shadow, không điều khiển cảnh báo.
**Mã:** `experiments/stocking_calendar.py` (test: `tests/test_stocking_calendar.py`). **Lần chạy:** `artifacts/experiments/stocking-calendar-20261023/`.

> **Không có ground truth.** Không có số liệu tăng trưởng hay tỷ lệ sống theo ngày thả. Đây là bảng rủi ro kỳ vọng từ khí hậu quá khứ. Nó không được đánh giá, không phải dự báo và không phải khuyến cáo cho người nuôi.

## 1. Cách làm

- Mỗi tuần ISO thả (1–52) và mỗi chu kỳ nuôi, lấy trung bình trên 35 năm thả 1991–2025 (mọi cửa sổ đều đủ dữ liệu, `n_years = 35`). "10 năm cuối" = 2016–2025.
- **Chu kỳ nuôi: 26 và 39 tuần là kịch bản, chưa có trích dẫn.** Chưa tra tài liệu về thời gian nuôi cá giò lồng ở Việt Nam. Cá giống nhỏ thường cần dài hơn 26 tuần để đạt cỡ thương phẩm. Cần người nuôi xác nhận.
- **Giai đoạn đầu:** 8 tuần đầu sau thả (cá nhỏ, dễ tổn thương nhất).
- **Nhiệt độ:** NOAA OISST ô 20.625 N 107.125 E, cộng độ lệch cảm biến − OISST. Độ lệch gốc +0.30 °C (trung vị 129 ngày hè–thu 2026; p90 +1.18). Độ lệch này chỉ đo vào mùa nóng, nhưng được áp cho cả mùa lạnh. Đó là một giả định.
- **Bão:** các lượt bão IBTrACS (`storm-hindcast-20261022d`), gió tại lồng `site_beaufort` ≥ cấp 8 và ≥ cấp 6. Dữ liệu là best-track (oracle), không phải dự báo. Ngày lấy theo UTC.
- **Ngưỡng:**

| Mục | Ngưỡng | Nguồn |
| --- | --- | --- |
| Nóng (theo dõi / stress) | ≥ 31 / ≥ 33 °C | Sun & Chen 2014; doc 27 |
| Lạnh nặng | < 18 °C | `cobia_thresholds.json` (18 °C → điểm 0.5) |
| Lạnh | < 20 °C | **giả định của nhóm, không có trích dẫn** |
| Ngày phù hợp tăng trưởng | 25–30 °C | `cobia_thresholds.json` (điểm 1.0) |

- **OISST tối đa 31.93 °C.** Với độ lệch +0.30, số ngày ≥ 33 °C bằng 0 ở mọi cửa sổ. Cột "stress" chỉ có nghĩa ở ca độ lệch +1.18.

## 2. Điểm tổng hợp

Mỗi rủi ro được đưa về 0–1 bằng min–max **qua 52 tuần** (với từng chu kỳ). Điểm = 1 − Σ trọng số × rủi ro. Điểm cao = tuần thả tốt hơn *so với các tuần khác*.

| Thành phần | Định nghĩa | Trọng số gốc |
| --- | --- | --- |
| nóng | ngày ≥ 31 °C + ngày ≥ 33 °C (ngày ≥ 33 tính đôi) | 0.20 |
| lạnh | ngày < 20 °C + ngày < 18 °C (tính đôi) | 0.20 |
| bão | số lượt ≥ cấp 8 + 0.25 × số lượt cấp 6–7 | 0.25 |
| giai đoạn đầu | trung bình của 3 rủi ro (nóng, lạnh, bão) trong 8 tuần đầu | 0.20 |
| tăng trưởng | 1 − (số ngày 25–30 °C, min–max) | 0.15 |

Trọng số do nhóm chọn, không có cơ sở thực nghiệm. Vì vậy phần 5 kiểm tra độ bền theo trọng số.

**Cách đọc.** Min–max làm 0.54 lượt bão, 12.6 ngày nóng và 38.8 ngày lạnh đều thành 1.0. Điểm là xếp hạng tương đối giữa các tuần, **không phải rủi ro tuyệt đối**. Rủi ro lạnh gần như nhị phân: mọi cửa sổ phủ tháng 12–3 đều chạm 38.8 ngày lạnh.

## 3. Bảng 12 tháng (chữ)

Lớp **tương đối**: mỗi chu kỳ chia cố định 4 tháng "tốt" / 4 "thận trọng" / 4 "tránh" theo điểm trung bình các tuần trong tháng (tháng theo ngày Thứ Năm của tuần ISO). Cột chung lấy lớp xấu hơn của hai chu kỳ. Không có tháng nào "an toàn" tuyệt đối.

| Tháng | Điểm 26 tuần | Lớp 26 tuần | Điểm 39 tuần | Lớp 39 tuần | Chung |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.55 | thận trọng | 0.25 | tránh | **tránh** |
| 2 | 0.52 | tránh | 0.36 | thận trọng | **tránh** |
| 3 | 0.54 | thận trọng | 0.51 | tốt | thận trọng |
| 4 | 0.55 | thận trọng | 0.53 | tốt | thận trọng |
| 5 | 0.52 | tránh | 0.41 | thận trọng | **tránh** |
| 6 | 0.43 | tránh | 0.21 | tránh | **tránh** |
| 7 | 0.47 | tránh | 0.23 | tránh | **tránh** |
| 8 | 0.55 | thận trọng | 0.45 | thận trọng | thận trọng |
| 9 | 0.61 | tốt | 0.64 | tốt | tốt* |
| 10 | 0.64 | tốt | 0.62 | tốt | tốt* |
| 11 | 0.64 | tốt | 0.45 | thận trọng | thận trọng |
| 12 | 0.62 | tốt | 0.29 | tránh | **tránh** |

\* **"Tốt" ở đây nghĩa là ít bão và ít nóng, không phải cá lớn tốt** (xem 4.1). Tháng 6–7 "tránh" vì bão (đỉnh T7–T9 rơi vào chu kỳ) cộng nóng giữa hè và bão trong 8 tuần đầu.

## 4. Kết quả chính

### 4.1 Cửa sổ "ít rủi ro bão/nóng" nhưng tăng trưởng kém

- **26 tuần: tuần 40–49 là một bình nguyên, không phải bảng xếp hạng.** 10 tuần (40–49) đều có điểm 0.64 (cách nhau < 0.01; điểm tối đa 0.644). Thứ hạng trong nhóm này (tuần 46 đứng nhất) chỉ do cách phá hòa (`method="first"`), là nhiễu. Không nói "thả tuần 46".
- Các tuần này có `risk_growth` ≈ 0.75–1.0. Cá nuôi qua đông: chỉ 28–52 ngày 25–30 °C trên 182 ngày, và khoảng 39 ngày < 20 °C (4.9 ngày < 18 °C). Chúng thắng vì tránh được bão và nóng, trong khi tăng trưởng chỉ nặng 0.15. Gọi đúng tên: **an toàn về bão/nóng, nghèo tăng trưởng**. Đây là đánh đổi mà điểm tổng hợp che đi.
- **39 tuần: tuần 38–40 (cuối tháng 9) dẫn đầu** (điểm 0.66, bình nguyên 3 tuần). Chúng thả sau mùa bão chính (0.14 lượt ≥ cấp 8, 1.5 ngày nóng) và đi qua mùa đông ở tuổi ~3 tháng (38.8 ngày < 20 °C), với 107 ngày phù hợp tăng trưởng.

### 4.2 Cửa sổ ưu tiên tăng trưởng (mùa xuân)

| Tuần thả | Chu kỳ | Ngày 25–30 °C | Ngày ≥ 31 °C | Lượt ≥ cấp 8 / ≥ cấp 6 | Ngày < 20 °C | Điểm |
| --- | --- | --- | --- | --- | --- | --- |
| 13–15 | 39 tuần | 154 | 12.6 | 0.54 / 2.57 | 1–2 | 0.54 |
| 16–19 | 26 tuần | 114–125 | 12.6 | 0.49–0.51 / 2.4–2.5 | ~0 | 0.53–0.55 |

- Thả từ cuối tháng 3 đến tháng 5 tránh gần hết mùa đông trong chu kỳ, và cá có 114–154 ngày tăng trưởng tốt. Trả giá: gần như mọi cửa sổ chứa đỉnh nóng (12.6 ngày ≥ 31 °C) và mùa bão (0.5 lượt ≥ cấp 8, 2.5 lượt ≥ cấp 6 mỗi chu kỳ).
- Ở 26 tuần, tuần 16–19 có độ bền cao nhất theo trọng số (top-5 trong 32–44% bộ trọng số). Tuần 17: 44%.
- **10 năm cuối nóng hơn rõ:** cửa sổ 39 tuần thả tuần 5–21 có trung bình 28.5 ngày ≥ 31 °C (cả kỳ 1991–2025: 12.6). Lượt bão ≥ cấp 8 mỗi chu kỳ là 0.2 so với 0.5 (khoảng 2 lượt trong 10 năm). Mẫu quá nhỏ để kết luận xu hướng bão.
- **8 tuần đầu:** thả tuần 23–29 (đầu tháng 6 đến giữa tháng 7) có 0.23 lượt ≥ cấp 8 và 1.0–1.3 lượt ≥ cấp 6 ngay trong 8 tuần đầu, cao nhất năm. Thả tuần 1–10 thì cá nhỏ gặp 9–29 ngày < 20 °C trong 8 tuần đầu.

## 5. Độ bền

### Theo trọng số (7 bộ trọng số gọi tên + 1,000 bộ Dirichlet(1), seed 20261023)

- **Không có tuần nào đạt ngưỡng "bền" (top-5 trong ≥ 80% bộ trọng số).** `robust_weeks` rỗng cho cả 26 và 39 tuần.
- Chia sẻ top-5 lớn nhất: 26 tuần: 0.44 (tuần 17), 0.37 (tuần 18), 0.34 (tuần 46). 39 tuần: 0.55 (tuần 40), 0.53 (tuần 39), 0.50 (tuần 14 và 38).
- Kết luận: **thứ hạng từng tuần do trọng số quyết định.** Chỉ nên nói về nhóm tuần (mùa), không nói tuần cụ thể.
- Hai họ cửa sổ cạnh tranh: "cuối hè–thu" (hazard-safe) và "xuân" (growth-first). Trọng số quyết định họ nào thắng.

### Theo độ nhạy (offset 0 / +0.30 / +1.18; ngưỡng ±0.5 °C; 10 năm cuối; gió bão hệ số 0.88)

| Ca | Top-3 (26 tuần) | Top-3 (39 tuần) |
| --- | --- | --- |
| gốc (+0.30) | 46, 47, 41 | 40, 39, 38 |
| offset 0 | 46, 48, 47 | 40, 38, 39 |
| offset +1.18 | 41, 40, 42 | 40, 39, 38 |
| ngưỡng −0.5 | 41, 40, 46 | 40, 39, 38 |
| ngưỡng +0.5 | 46, 44, 48 | 40, 39, 38 |
| 10 năm cuối | 43, 44, 41 | 40, 39, 41 |
| gió bão 0.88 | 46, 47, 41 | 40, 39, 38 |

- **39 tuần: top-3 (38–40) giữ nguyên ở 6/7 ca; ca 10 năm cuối thay tuần 38 bằng 41.** Ổn định.
- **26 tuần: không ổn định.** Trùng top-3 với ca gốc chỉ 1–3 trên 3 (offset +1.18: 1; 10 năm cuối: 1; ngưỡng +0.5: 1). Nhưng cả 3 tuần gốc vẫn nằm trong top-5 ở 6/7 ca (10 năm cuối: 2/3). Dải đúng là "nửa sau tháng 10 đến giữa tháng 12" (tuần 40–49), không phải một tuần.
- Độ ổn định này chỉ cho thấy kết luận ít đổi với tham số, **không** chứng minh đúng với thực tế.

## 6. Hạn chế

1. **Không có ground truth** (tăng trưởng, tỷ lệ sống, nhật ký thả). Không có đánh giá.
2. Chu kỳ 26/39 tuần là kịch bản, chưa trích dẫn. Cỡ giống và thời gian ra thị trường chưa tra.
3. Ngưỡng lạnh 20 °C là giả định. 18 °C từ `cobia_thresholds.json`. Ngưỡng chết do lạnh chưa đặt.
4. Độ lệch +0.30 °C chỉ từ một mùa hè–thu 2026, áp cho mùa đông. Ô OISST 0.25° ngoài khơi có thể sai khác lồng nhiều hơn cả độ lệch.
5. Bão: best-track oracle; chỉ 0.62 lượt ≥ cấp 8 mỗi năm nên trung bình theo tuần rất thưa (35 năm, phần lớn cửa sổ có 0–20 sự kiện). Gió tại lồng là cận dưới, không có cấp ≥ 12.
6. Min–max + trọng số tự chọn: điểm tương đối, nhạy với trọng số (phần 5). Không có hệ số tử vong hay chi phí.
7. Chưa xét độ mặn, DO, bệnh (Vibrio, Streptococcus), sóng, mưa lớn, giá giống, giá bán, rủi ro thị trường.
8. Lớp 4/4/4 tháng là tương đối, bị ép cân bằng. Không đọc "tốt" là an toàn.
9. Không dùng cho khuyến cáo thật. Cần người nuôi và chuyên gia xem lại.

## 7. Tệp đầu ra

`ranking_26w.csv`, `ranking_39w.csv` (chỉ số kỳ vọng, rủi ro, điểm, hạng, chia sẻ top-3/top-5, cột `last10_*`), `month_classes.csv`, `sensitivity_top3.csv`, `manifest.json` (tham số, hash đầu vào, trọng số, độ ổn định).
