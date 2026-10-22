# Lịch thả giống cá giò theo lý thuyết (Cát Bà, NB1)

**Ngày:** 23/10/2026. **Trạm:** `06M26042804`. **Trạng thái:** thuần lý thuyết + dữ liệu công khai; shadow, không điều khiển cảnh báo.
**Mã:** `experiments/stocking_calendar.py` (test: `tests/test_stocking_calendar.py`). **Lần chạy:** `artifacts/experiments/stocking-calendar-20261023b/` (thay thế `stocking-calendar-20261023`, xem mục 4).

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

## 2. Điểm tổng hợp

Mỗi rủi ro được đưa về 0–1 bằng min–max **qua 52 tuần** (với từng chu kỳ). Điểm = 1 − Σ trọng số × rủi ro. Điểm cao = tuần thả tốt hơn *so với các tuần khác*.

| Thành phần | Định nghĩa | Trọng số gốc |
| --- | --- | --- |
| nóng (tuần 9→hết) | ngày ≥ 31 °C + ngày ≥ 33 °C (ngày ≥ 33 tính đôi) | 0.20 |
| lạnh | ngày < 20 °C + ngày < 18 °C (tính đôi) | 0.20 |
| bão | số lượt ≥ cấp 8 + 0.25 × số lượt cấp 6–7 | 0.25 |
| giai đoạn đầu | trung bình của 3 rủi ro (nóng, lạnh, bão) trong 8 tuần đầu | 0.20 |
| tăng trưởng | 1 − (số ngày 25–30 °C, min–max) | 0.15 |

Trọng số do nhóm chọn, không có cơ sở thực nghiệm. Vì vậy phần 5 kiểm tra độ bền theo trọng số.

**Cách đọc.** Min–max làm 0.54 lượt bão, 12.6 ngày nóng và 38.8 ngày lạnh đều thành 1.0. Điểm là xếp hạng tương đối giữa các tuần, **không phải rủi ro tuyệt đối**. Rủi ro lạnh gần như nhị phân: mọi cửa sổ phủ tháng 12–3 đều chạm 38.8 ngày lạnh.

## 3. Bảng 12 tháng (chữ)

Lớp theo **điểm tuyệt đối** (trung bình các tuần ISO trong tháng; tháng theo ngày Thứ Năm của tuần): **tốt** ≥ 0.55, **thận trọng** 0.40–0.55, **tránh** < 0.40. Mốc 0.5 = tuần có rủi ro trung bình; các mốc là quy ước của nhóm, không có cơ sở thực nghiệm. Không ép 4/4/4. Mỗi chu kỳ có bảng riêng, **không gộp** hai chu kỳ thành một nhãn. Cột "nhóm" = nhóm không phân biệt được: các tháng được nối chuỗi khi điểm liền kề (đã sắp xếp) chênh ≤ 0.03; cùng số nhóm nghĩa là chưa tách được.

| Tháng | Điểm 26 tuần | Lớp 26 | Nhóm 26 | Điểm 39 tuần | Lớp 39 | Nhóm 39 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.74 | tốt | 1 | 0.41 | thận trọng | 4 |
| 2 | 0.67 | tốt | 2 | 0.48 | thận trọng | 3 |
| 3 | 0.60 | tốt | 3 | 0.52 | thận trọng | 2 |
| 4 | 0.53 | thận trọng | 5 | 0.48 | thận trọng | 3 |
| 5 | 0.56 | tốt | 4 | 0.42 | thận trọng | 4 |
| 6 | 0.64 | tốt | 2 | 0.39 | tránh | 4 |
| 7 | 0.72 | tốt | 1 | 0.45 | thận trọng | 4 |
| 8 | 0.72 | tốt | 1 | 0.55 | thận trọng | 2 |
| 9 | 0.66 | tốt | 2 | 0.60 | tốt | 1 |
| 10 | 0.64 | tốt | 2 | 0.55 | thận trọng | 2 |
| 11 | 0.68 | tốt | 2 | 0.44 | thận trọng | 4 |
| 12 | 0.75 | tốt | 1 | 0.39 | tránh | 4 |

Khoảng điểm theo lớp (`class_ranges.csv`):

| Chu kỳ | Lớp | Số tháng | Điểm min–max | Tháng |
| --- | --- | --- | --- | --- |
| 26 tuần | tốt | 11 | 0.564–0.752 | 1–3, 5–12 |
| 26 tuần | thận trọng | 1 | 0.532 | 4 |
| 26 tuần | tránh | 0 | – | – |
| 39 tuần | tốt | 1 | 0.599 | 9 |
| 39 tuần | thận trọng | 9 | 0.409–0.547 | 1–5, 7, 8, 10, 11 |
| 39 tuần | tránh | 2 | 0.385–0.394 | 6, 12 |

Cách đọc:

- **Chu kỳ 26 tuần gần như không phân biệt tháng:** toàn dải điểm 0.53–0.75, 11/12 tháng "tốt", chỉ tháng 4 hơi thấp. Tháng 7/8/12/1 (0.72–0.75) cùng nhóm 1, tức không tách được. Vì vậy không có lý do dùng bảng 26 tuần để loại tháng nào.
- **Chu kỳ 39 tuần phân biệt hơn:** chỉ tháng 9 "tốt" (0.60); tháng 6 và 12 "tránh" (0.39, 0.385; chênh nhau < 0.01, không tách được); tháng 8 và 10 (0.547–0.55) nằm sát mốc 0.55 nên nhãn "thận trọng" mong manh.
- Điểm vẫn là tương đối (min–max qua 52 tuần): "tốt" nghĩa là ít bão/nóng/lạnh hơn các tuần khác theo các trọng số này, không phải cá lớn tốt (xem 4.1).
- **Lưu ý thiết kế (hạn chế mới):** rủi ro giai đoạn đầu là trung bình 3 rủi ro, nên 26 ngày lạnh trong 8 tuần đầu (thả tuần 1–3) chỉ đóng góp tối đa ≈ 0.07 vào điểm; điểm tháng 1 cao (0.74) một phần do vậy. Cá giống nhỏ lẽ ra nhạy với lạnh hơn cá lớn, nên điểm 26 tuần của mùa đông có thể bị đánh giá thừa.

## 4. Kết quả chính

Phiên bản này **tách cửa sổ không chồng lấp**: các chỉ số "cả chu kỳ" tính trên tuần 9 đến hết chu kỳ, 8 tuần đầu chỉ vào thành phần "giai đoạn đầu". Bản chạy trước (`stocking-calendar-20261023`) cho "giai đoạn đầu" tính hai lần (nằm trong cả cửa sổ đầy đủ), nên **bị thay thế** bởi `stocking-calendar-20261023b`. Top-3 cũ (26 tuần: 46, 47, 41; 39 tuần: 40, 39, 38) không còn dùng.

### 4.1 Cửa sổ dẫn đầu

Tuần cùng nhóm = điểm cách đỉnh ≤ 0.03; xếp hạng bên trong nhóm là nhiễu.

- **39 tuần: nhóm tuần 35–39 (điểm 0.585–0.606; đỉnh tuần 38 0.606, kế tiếp 37: 0.604, 36: 0.598), thả cuối tháng 8 đến cuối tháng 9.** Sau mùa bão chính: 0.00–0.06 lượt ≥ cấp 8 trong phần sau, 0.1–0.2 lượt ≥ cấp 8 và 0.6–0.9 lượt ≥ cấp 6 trong 8 tuần đầu; 0.0–1.3 ngày ≥ 31 °C; đi qua mùa đông ở tuổi ~3 tháng (38.8 ngày < 20 °C); 56–62 ngày 25–30 °C ở phần sau cộng 40–51 ở 8 tuần đầu.
- **26 tuần: nhóm tuần 50–2 (điểm 0.75–0.765; đỉnh tuần 51 và 52 ≈ 0.76, tuần 1 0.76), thả giữa tháng 12 đến đầu tháng 1.** Tuần 50, 51, 52, 1, 2 không tách được (chênh ≤ 0.015). Rủi ro bão/nóng thấp (≤ 0.14 lượt ≥ cấp 8, ≤ 2.3 ngày nóng), nhưng 8 tuần đầu gặp 15–28 ngày < 20 °C (xem lưu ý diluted ở mục 3) và `risk_growth` 0.33–0.53.
- Cả hai bảng chỉ cho thấy cửa sổ "ít bão và nóng"; **tăng trưởng không phải điểm mạnh** (tuần 38 thả 39 tuần có 108 ngày 25–30 °C, so với 154 ở tuần 14–15).

### 4.2 Cửa sổ ưu tiên tăng trưởng (mùa xuân)

| Tuần thả | Chu kỳ | Ngày 25–30 °C (8 tuần đầu + phần sau) | Ngày ≥ 31 °C | Lượt ≥ cấp 8 / ≥ cấp 6 | Điểm |
| --- | --- | --- | --- | --- | --- |
| 14–15 | 39 tuần | 154 | 12.6 | 0.54 / 2.6 | 0.49–0.50 |
| 17–19 | 26 tuần | 120–125 | 12.6 | 0.5 / 2.4–2.5 | 0.53–0.56 |

- Thả cuối tháng 3 đến tháng 5 tránh gần hết mùa đông và có 120–154 ngày tăng trưởng tốt, đổi lại gần như mọi cửa sổ chứa đỉnh nóng (12.6 ngày ≥ 31 °C) và mùa bão.
- **10 năm cuối nóng hơn rõ:** thả tuần 14–15 (39 tuần) có 28 ngày ≥ 31 °C trên phần sau (cả kỳ 1991–2025: 12.6); tuần 17–19 (26 tuần) 25–26 ngày so với 11–12 (cả kỳ). Lượt bão ≥ cấp 8 mỗi chu kỳ 0.2 so với 0.5; mẫu quá nhỏ để kết luận xu hướng bão.
- **8 tuần đầu:** thả tuần 25–28 (cuối tháng 6 đến đầu tháng 7) có 0.20–0.23 lượt ≥ cấp 8 và 1.1–1.3 lượt ≥ cấp 6 ngay trong 8 tuần đầu, cùng 8–9 ngày ≥ 31 °C; thả tuần 1–10 thì 9–29 ngày < 20 °C.

## 5. Độ bền

### Theo trọng số (7 bộ trọng số gọi tên + 1,000 bộ Dirichlet(1), seed 20261023)

- **Không có tuần nào đạt ngưỡng "bền" (top-5 trong ≥ 80% bộ trọng số).** `robust_weeks` rỗng cho cả 26 và 39 tuần.
- Chia sẻ top-5 lớn nhất: 26 tuần: 0.30 (tuần 51), 0.28 (tuần 50); 39 tuần: 0.52 (tuần 11), 0.41 (tuần 37, 38), 0.40 (tuần 36).
- Kết luận: **thứ hạng từng tuần do trọng số quyết định.** Chỉ nên nói về nhóm tuần (mùa), không nói tuần cụ thể.

### Theo độ nhạy (offset 0 / +0.30 / +1.18; ngưỡng ±0.5 °C; 10 năm cuối; gió bão hệ số 0.88)

| Ca | Top-3 (26 tuần) | Top-3 (39 tuần) |
| --- | --- | --- |
| gốc (+0.30) | 51, 1, 52 | 38, 37, 36 |
| offset 0 | 51, 1, 52 | 38, 37, 36 |
| offset +1.18 | 51, 50, 52 | 37, 36, 38 |
| ngưỡng −0.5 | 51, 1, 52 | 37, 36, 38 |
| ngưỡng +0.5 | 1, 51, 52 | 38, 37, 39 |
| 10 năm cuối | 52, 51, 50 | 37, 36, 35 |
| gió bão 0.88 | 51, 1, 52 | 38, 37, 36 |

- **39 tuần:** top-3 nằm trong tuần 35–39 ở mọi ca; trùng top-3 gốc 2–3/3, và cả 3 tuần gốc luôn trong ±2 tuần của top-3 ca khác.
- **26 tuần:** top-3 nằm trong tuần 50–52 và 1 ở mọi ca (trùng 2–3/3). Ổn định theo tham số nhưng do cùng một cơ chế (mùa đông ít bão/nóng, lạnh bị pha loãng); không chứng minh đúng thực tế.
- Độ ổn định này chỉ cho thấy kết luận ít đổi với tham số, **không** chứng minh đúng với thực tế.

## 6. Hạn chế

1. **Không có ground truth** (tăng trưởng, tỷ lệ sống, nhật ký thả). Không có đánh giá.
2. Chu kỳ 26/39 tuần là kịch bản, chưa trích dẫn. Cỡ giống và thời gian ra thị trường chưa tra.
3. Ngưỡng lạnh 20 °C là giả định. 18 °C từ `cobia_thresholds.json`. Ngưỡng chết do lạnh chưa đặt.
4. Độ lệch +0.30 °C chỉ từ một mùa hè–thu 2026, áp cho mùa đông. Ô OISST 0.25° ngoài khơi có thể sai khác lồng nhiều hơn cả độ lệch.
5. Bão: best-track oracle; chỉ 0.62 lượt ≥ cấp 8 mỗi năm nên trung bình theo tuần rất thưa. Gió tại lồng là cận dưới, không có cấp ≥ 12.
6. Min–max + trọng số tự chọn: điểm tương đối, nhạy với trọng số (phần 5). Không có hệ số tử vong hay chi phí.
7. Chưa xét độ mặn, DO, bệnh (Vibrio, Streptococcus), sóng, mưa lớn, giá giống, giá bán, rủi ro thị trường.
8. Mốc lớp 0.55/0.40 và dung sai 0.03 là quy ước; bảng 26 tuần hầu như không phân lớp. Không đọc "tốt" là an toàn.
9. Rủi ro giai đoạn đầu (trung bình 3 rủi ro, trọng số 0.20) làm loãng tác động của lạnh lên cá giống; xem mục 3.
10. Không dùng cho khuyến cáo thật. Cần người nuôi và chuyên gia xem lại.

## 7. Tệp đầu ra

`ranking_26w.csv`, `ranking_39w.csv` (chỉ số kỳ vọng, rủi ro, điểm, hạng, chia sẻ top-3/top-5, cột `last10_*`; cột `early_*` = 8 tuần đầu, cột không tiền tố = tuần 9 đến hết chu kỳ), `month_classes.csv`, `class_ranges.csv`, `sensitivity_top3.csv`, `manifest.json` (tham số, hash đầu vào, trọng số, độ ổn định).
