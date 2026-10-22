# Đánh giá kỹ năng phát hiện ngày nóng của sản phẩm SST (Cát Bà, 2026-10-23)

Trạng thái: lý thuyết, shadow. Không dùng cho cảnh báo. Mã: `experiments/heat_skill.py`.
Kết quả hiện hành: `artifacts/experiments/heat-skill-20261023b/` (`metrics.csv` có cột `horizon`, `daily.csv`, `thresholds.csv`, `manifest.json` có `air_source`).

**Đã thay thế (superseded), để nguyên, không dùng:** `heat-skill-20261023/`. Nhiệt độ không khí trong lần chạy đó ghi là "ERA5" nhưng lấy từ file `era5_nb1_1982_20261020.csv`, tải không có `models=`, tức là `best_match` (từ 2017 là ECMWF IFS 9 km). IFS ở ô này ấm hơn ERA5 (cực đại ngày cao nhất 36,7 °C so với 34,6 °C), nên các hàng `lin_air` cũ trông tốt hơn thực tế. Lần chạy đó cũng gọi hàng ngày-0 là "nowcast", trong khi nó dùng trung bình không khí cả ngày đích.

## Câu hỏi

Sản phẩm SST nào, và chỉnh thế nào, thì bắt được ngày nóng đo bằng cảm biến lồng bè 06M26042804? Và SST có thêm gì so với chỉ dùng nhiệt độ không khí?

## Dữ liệu và cách làm

- Sự thật: nhiệt độ trung bình ngày của cảm biến (giờ địa phương, ≥1296 dòng/ngày, 10–40 °C).
- 130 ngày, 2026-05-29 đến 2026-10-21. Sản phẩm SST kết thúc 10-20.
- Ngày nóng = trung bình ngày ≥ 31 °C: **31 ngày**. Nhạy cảm: ≥ 30 °C: 77 ngày. Không có ngày nào ≥ 33 °C.
- `alert_level ≥ 1` của `daily_heat_stress` giống hệt ≥ 31 °C (31 ngày, khớp 100 %). `alert_level ≥ 2` có 0 ngày.
- Sản phẩm: OISST (ô 20.625N 107.125E, ngày UTC) và Open-Meteo marine (trung bình ngày địa phương).
- **Nhiệt độ không khí: ERA5 thật** (Open-Meteo archive `models=era5`, file `data/hazards/era5/openmeteo_era5_nb1_1982_20261016.csv`), trung bình ngày UTC của `temperature_2m`. ERA5 trễ khoảng 5 ngày, dừng ở **2026-10-16**. Vì vậy các hàng dùng không khí có ít ngày hơn (split 68 thay vì 72, LOMO 125 thay vì 129). 4–5 ngày bị bỏ là ngày cuối tháng 10 mát, đều là ngày âm tính, nên so FA/FAR giữa hàng có và không có không khí hơi thiên về hàng có không khí. Mọi bảng dưới ghi `n` và số ngày nóng (`pos`).
- Cách chỉnh, luôn ước lượng ngoài mẫu:
  - `raw`: không chỉnh.
  - `offset`: cộng độ lệch trung vị (cảm biến − sản phẩm) của tập train.
  - `lin`: cảm biến ~ a + b·sản phẩm.
  - `lin_air`: cảm biến ~ a + b·sản phẩm + c·nhiệt độ không khí.
  - **Đường cơ sở chỉ-không-khí** (sản phẩm `air`): coi nhiệt độ không khí ERA5 như "sản phẩm", dùng `raw`/`offset`/`lin` (cảm biến ~ a + b·không khí). Không có `lin_air` cho hàng này.
  - Hậu tố `_tuned`: ngưỡng trên giá trị đã chỉnh được chọn để tối đa CSI trên tập train (lưới 0,1 °C). Không có hậu tố: ngưỡng cố định 31.
- **Thời hạn (cột `horizon`):**
  - `same-day hindcast` (hồi cứu cùng ngày): sản phẩm và không khí của chính ngày đích. Trung bình không khí cả ngày chỉ có sau khi ngày kết thúc, nên đây **không phải nowcast** vận hành.
  - `lead k (persistence)`: dùng giá trị của ngày t−k (cả SST và không khí). Đây là mức sàn, không phải dự báo.
- Hai cách chia:
  - **split**: train 05-29..07-31 (57 ngày, 21 ngày nóng), test 08-01..10-21 (10 ngày nóng).
  - **lomo**: bỏ lần lượt từng tháng (tháng 5 gộp vào tháng 6).
- Chỉ số: H = trúng, M = bỏ sót, FA = báo động giả. POD = H/(H+M). FAR = FA/(H+FA). CSI = H/(H+M+FA). bias = (H+FA)/(H+M).

## Phát hiện chính

1. **OISST thô: POD = 0.** OISST cao nhất 30,99 °C trong cả mùa, không chạm 31.
2. **Open-Meteo marine thô bắt được** (POD 0,70–0,81) nhưng báo thừa (FAR 0,50–0,61), vì ấm hơn cảm biến khoảng 0,6 °C.
3. **Phần lớn kỹ năng đến từ nhiệt độ không khí, không phải từ SST.** Chỉ dùng không khí ERA5 + độ lệch (`air offset`) đạt CSI 0,44 ở LOMO, ngang marine + không khí (`lin_air` 0,46, `lin_air_tuned` 0,44). SST thêm khoảng 0,02 CSI ở LOMO. Chỉ split (10 ngày nóng) cho marine + không khí hơn rõ (CSI 0,54 so với 0,31–0,39), nhưng mẫu quá nhỏ.
4. **Với ERA5 thật, các hàng có không khí kém hơn bản cũ.** OISST `lin_air_tuned` LOMO: CSI 0,50 → 0,43. Marine `lin_air_tuned`: 0,50 → 0,44. MAE `lin_air` đổi từ −0,02 đến +0,09 °C (OISST tăng rõ nhất).
5. **Sản phẩm không hơn cảm biến.** Cảm biến hôm qua (persistence) cho CSI 0,50 (split) và 0,66 (LOMO), cao hơn mọi sản phẩm.
6. **Mẫu rất nhỏ.** Split chỉ có 10 ngày nóng ở test. Chênh lệch dưới ~0,15 giữa các hàng không đáng tin.

## Hồi cứu cùng ngày (same-day hindcast), ngày nóng ≥ 31 °C

### Split (train Jun–Jul, test Aug–Oct, 10 ngày nóng)

| Sản phẩm | Cách chỉnh | n | H | M | FA | POD | FAR | CSI | MAE °C | RMSE °C | r |
|---|---|---|---|---|---|---|---|---|---|---|---|
| OISST | raw | 72 | 0 | 10 | 0 | 0,00 | – | 0,00 | 0,99 | 1,21 | 0,28 |
| OISST | lin | 72 | 0 | 10 | 0 | 0,00 | – | 0,00 | 0,98 | 1,33 | 0,28 |
| OISST | raw_tuned | 72 | 5 | 5 | 13 | 0,50 | 0,72 | 0,22 | 0,99 | 1,21 | 0,28 |
| OISST | lin_air | 68 | 1 | 9 | 2 | 0,10 | 0,67 | 0,08 | 0,96 | 1,20 | 0,79 |
| OISST | lin_air_tuned | 68 | 7 | 3 | 7 | 0,70 | 0,50 | 0,41 | 0,96 | 1,20 | 0,79 |
| marine | raw | 72 | 7 | 3 | 11 | 0,70 | 0,61 | 0,33 | 1,06 | 1,29 | 0,54 |
| marine | offset | 72 | 7 | 3 | 3 | 0,70 | 0,30 | 0,54 | 0,88 | 1,11 | 0,54 |
| marine | lin | 72 | 7 | 3 | 3 | 0,70 | 0,30 | 0,54 | 0,86 | 1,10 | 0,54 |
| marine | lin_air | 68 | 7 | 3 | 3 | 0,70 | 0,30 | 0,54 | 0,68 | 0,87 | 0,72 |
| marine | lin_air_tuned | 68 | 7 | 3 | 3 | 0,70 | 0,30 | 0,54 | 0,68 | 0,87 | 0,72 |
| **không khí** | raw_tuned | 68 | 7 | 3 | 8 | 0,70 | 0,53 | 0,39 | 1,12 | 1,33 | 0,79 |
| **không khí** | offset | 68 | 4 | 6 | 3 | 0,40 | 0,43 | 0,31 | 0,64 | 0,82 | 0,79 |
| **không khí** | lin | 68 | 1 | 9 | 1 | 0,10 | 0,50 | 0,09 | 0,90 | 1,14 | 0,79 |
| **không khí** | lin_tuned | 68 | 6 | 4 | 8 | 0,60 | 0,57 | 0,33 | 0,90 | 1,14 | 0,79 |
| cảm biến hôm qua | persistence | 69 | 6 | 3 | 3 | 0,67 | 0,33 | 0,50 | 0,45 | 0,63 | 0,87 |

### Leave-one-month-out (31 ngày nóng)

| Sản phẩm | Cách chỉnh | n | H | M | FA | POD | FAR | CSI | MAE °C | RMSE °C | r |
|---|---|---|---|---|---|---|---|---|---|---|---|
| OISST | raw | 129 | 0 | 31 | 0 | 0,00 | – | 0,00 | 0,82 | 1,02 | 0,44 |
| OISST | offset | 129 | 4 | 27 | 4 | 0,13 | 0,50 | 0,11 | 0,78 | 1,02 | 0,44 |
| OISST | raw_tuned | 129 | 21 | 10 | 29 | 0,68 | 0,58 | 0,35 | 0,82 | 1,02 | 0,44 |
| OISST | lin_air | 125 | 15 | 16 | 10 | 0,48 | 0,40 | 0,37 | 0,69 | 0,84 | 0,68 |
| OISST | lin_air_tuned | 125 | 23 | 8 | 22 | 0,74 | 0,49 | 0,43 | 0,69 | 0,84 | 0,68 |
| marine | raw | 129 | 25 | 6 | 25 | 0,81 | 0,50 | 0,45 | 0,88 | 1,10 | 0,62 |
| marine | offset | 129 | 8 | 23 | 9 | 0,26 | 0,53 | 0,20 | 0,76 | 0,97 | 0,59 |
| marine | lin | 129 | 7 | 24 | 3 | 0,23 | 0,30 | 0,21 | 0,73 | 0,94 | 0,56 |
| marine | lin_air | 125 | 18 | 13 | 8 | 0,58 | 0,31 | 0,46 | 0,58 | 0,74 | 0,77 |
| marine | lin_air_tuned | 125 | 23 | 8 | 21 | 0,74 | 0,48 | 0,44 | 0,58 | 0,74 | 0,77 |
| **không khí** | raw_tuned | 125 | 22 | 9 | 20 | 0,71 | 0,48 | 0,43 | 1,08 | 1,29 | 0,76 |
| **không khí** | offset | 125 | 20 | 11 | 14 | 0,65 | 0,41 | 0,44 | 0,70 | 0,92 | 0,75 |
| **không khí** | lin | 125 | 14 | 17 | 11 | 0,45 | 0,44 | 0,33 | 0,66 | 0,81 | 0,71 |
| **không khí** | lin_tuned | 125 | 22 | 9 | 22 | 0,71 | 0,50 | 0,42 | 0,66 | 0,81 | 0,71 |
| cảm biến hôm qua | persistence | 123 | 23 | 5 | 7 | 0,82 | 0,23 | 0,66 | 0,38 | 0,54 | 0,88 |

Nhận xét:

- `offset` và `lin` làm POD của marine **giảm** (0,81 xuống 0,26 và 0,23): các tháng nóng có độ lệch nhỏ hơn trung vị cả mùa, và hồi quy kéo về trung bình.
- Chọn ngưỡng theo train (`_tuned`) cứu OISST (POD 0 lên 0,68–0,74) nhưng FAR 0,49–0,58.
- Không khí một mình đã cho r 0,75–0,79 với cảm biến, cao hơn OISST (0,28–0,44) và marine (0,54–0,62). Thêm SST vào không khí không tăng CSI rõ ràng ở LOMO.

## Ngưỡng 30 °C (nhạy cảm, 77 ngày)

LOMO.

| Sản phẩm | Cách chỉnh | n | pos | H | M | FA | POD | FAR | CSI |
|---|---|---|---|---|---|---|---|---|---|
| OISST | raw | 129 | 77 | 53 | 24 | 21 | 0,69 | 0,28 | 0,54 |
| OISST | lin_air | 125 | 73 | 53 | 20 | 12 | 0,73 | 0,19 | 0,62 |
| OISST | lin_air_tuned | 125 | 73 | 62 | 11 | 34 | 0,85 | 0,35 | 0,58 |
| marine | raw | 129 | 77 | 65 | 12 | 32 | 0,84 | 0,33 | 0,60 |
| marine | offset | 129 | 77 | 51 | 26 | 7 | 0,66 | 0,12 | 0,61 |
| marine | lin_air | 125 | 73 | 56 | 17 | 11 | 0,77 | 0,16 | 0,67 |
| marine | lin_air_tuned | 125 | 73 | 60 | 13 | 21 | 0,82 | 0,26 | 0,64 |
| không khí | offset | 125 | 73 | 53 | 20 | 11 | 0,73 | 0,17 | 0,63 |
| cảm biến hôm qua | persistence | 123 | 72 | 64 | 8 | 9 | 0,89 | 0,12 | 0,79 |

Ở 30 °C, OISST thô đã dùng được. Không khí một mình (CSI 0,63) ngang các tổ hợp SST + không khí (0,58–0,67).

## Theo thời hạn (lead 1–3 ngày, persistence)

**Không có dự báo SST lưu trữ.** Đã thử ngày 2026-10-23:

- `marine-api.open-meteo.com` với `sea_surface_temperature_previous_dayN` (N = 1..7): toàn bộ null cho 2026-05..10.
- `previous-runs-api.open-meteo.com/v1/marine`: lỗi 404.
- `previous-runs-api.open-meteo.com/v1/forecast`: chỉ có SST ngày 0, các `_previous_dayN` null. Giá trị ngày 0 (trung bình 27,1 °C) là sản phẩm khác, lạnh hơn cảm biến 3 °C, không dùng.
- `historical-forecast-api` có SST ngày 0 nhưng không có phiên bản theo thời hạn. Chưa đánh giá.

Thay thế: **persistence**. Dự đoán ngày t bằng giá trị ngày t−k của SST và của không khí ERA5 (không dùng không khí ngày t, để không rò rỉ). Đây là mức sàn, không phải dự báo.

LOMO, ≥ 31 °C:

| Thời hạn | Sản phẩm | Cách chỉnh | n | H | M | FA | POD | FAR | CSI | MAE °C |
|---|---|---|---|---|---|---|---|---|---|---|
| cùng ngày (hồi cứu) | marine | lin_air_tuned | 125 | 23 | 8 | 21 | 0,74 | 0,48 | 0,44 | 0,58 |
| cùng ngày (hồi cứu) | không khí | offset | 125 | 20 | 11 | 14 | 0,65 | 0,41 | 0,44 | 0,70 |
| 1 | marine | raw | 130 | 24 | 7 | 26 | 0,77 | 0,52 | 0,42 | 0,95 |
| 1 | marine | lin_air_tuned | 126 | 26 | 5 | 21 | 0,84 | 0,45 | 0,50 | 0,64 |
| 1 | OISST | lin_air_tuned | 126 | 27 | 4 | 22 | 0,87 | 0,45 | 0,51 | 0,69 |
| 1 | không khí | lin_tuned | 126 | 23 | 8 | 24 | 0,74 | 0,51 | 0,42 | 0,66 |
| 2 | marine | raw | 130 | 21 | 10 | 29 | 0,68 | 0,58 | 0,35 | 1,02 |
| 2 | marine | lin_air_tuned | 127 | 25 | 6 | 26 | 0,81 | 0,51 | 0,44 | 0,71 |
| 2 | không khí | lin_tuned | 127 | 25 | 6 | 28 | 0,81 | 0,53 | 0,42 | 0,71 |
| 3 | marine | raw | 130 | 19 | 12 | 32 | 0,61 | 0,63 | 0,30 | 1,09 |
| 3 | marine | lin_air_tuned | 128 | 22 | 9 | 36 | 0,71 | 0,62 | 0,33 | 0,78 |
| 3 | không khí | lin_tuned | 128 | 24 | 7 | 39 | 0,77 | 0,62 | 0,34 | 0,77 |
| 1–3 | OISST | raw | 130 | 0 | 31 | 0 | 0,00 | – | 0,00 | 0,87–0,99 |

Nhận xét: lead 1 gần bằng hồi cứu cùng ngày vì nhiệt độ đổi chậm. Từ lead 2, FAR 0,5–0,6. Ở mọi lead, không khí một mình nằm trong khoảng ±0,08 CSI của SST + không khí. `_tuned` đạt POD cao bằng cách báo thừa (bias 1,4–2,0). Split cho cùng xu hướng nhưng nhiễu hơn, xem `metrics.csv`.

## Ý nghĩa cho cảnh báo nhiệt

1. **Không dùng OISST thô cho ngưỡng 31 °C** (POD = 0). Dùng được cho khí hậu dài hạn.
2. **Không chọn được sản phẩm SST vận hành ở cỡ mẫu này.** Marine + hồi quy không khí và không khí một mình cho CSI ngang nhau (LOMO 0,44–0,46). Lựa chọn hợp lý nhất hiện nay là đơn giản: nhiệt độ không khí (dự báo) + độ lệch, hoặc marine + không khí; cần thêm mùa để phân biệt.
3. **Kỳ vọng hồi cứu cùng ngày** (≥ 31 °C): POD khoảng 0,65–0,75, FAR khoảng 0,3–0,5, CSI khoảng 0,45. Đây là cận trên cho nowcast thật, vì nowcast không có trung bình không khí cả ngày.
4. **Lead 1 ngày**: tương tự (CSI 0,42–0,51). **Lead 2–3 ngày**: FAR 0,5–0,6, chỉ nên là "chú ý".
5. **Chỉ mức "theo dõi (≥31 °C)".** Cảm biến chưa bao giờ đo tới 33 °C.
6. Nơi có cảm biến sống, dùng **cảm biến hôm qua** cho lead 1 (CSI 0,50–0,66).
7. Giữ nhãn lý thuyết, không đẩy tới nông dân (shadow-mode).

## Hạn chế

- Một mùa (2026-05..10), 31 ngày nóng, 10 ngày nóng trong test split. Không có khoảng tin cậy.
- Hàng có không khí có ít ngày hơn (ERA5 dừng 10-16); các ngày bị bỏ đều mát.
- Tháng 10 hầu như không có ngày nóng. LOMO huấn luyện trên tháng sau để dự đoán tháng trước.
- Ngưỡng `_tuned` phụ thuộc vào tỷ lệ ngày nóng của tập train (37 % ở Jun–Jul).
- Không khí là ERA5 (tái phân tích, ô 0,25°), không phải dự báo. Vận hành cần dự báo không khí; ở lead k dùng giá trị ngày phát hành (persistence).
- OISST và ERA5 dùng ngày UTC, cảm biến dùng ngày địa phương.
- Sự thật là một cảm biến lồng bè, chưa kiểm chéo.
- Cần lưu snapshot dự báo marine và dự báo không khí theo giờ phát hành để đánh giá dự báo thật.
