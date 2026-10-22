# Đánh giá kỹ năng phát hiện ngày nóng của sản phẩm SST (Cát Bà, 2026-10-23)

Trạng thái: lý thuyết, shadow. Không dùng cho cảnh báo. Mã: `experiments/heat_skill.py`.
Kết quả: `artifacts/experiments/heat-skill-20261023/` (`metrics.csv`, `daily.csv`, `thresholds.csv`, `manifest.json`).

## Câu hỏi

Sản phẩm SST nào, và chỉnh thế nào, thì bắt được ngày nóng đo bằng cảm biến lồng bè 06M26042804?

## Dữ liệu và cách làm

- Sự thật: nhiệt độ trung bình ngày của cảm biến (giờ địa phương, ≥1296 dòng/ngày, 10–40 °C).
- 130 ngày, 2026-05-29 đến 2026-10-21. Sản phẩm kết thúc 10-20 nên mỗi phép so có 129 ngày hoặc ít hơn.
- Ngày nóng = trung bình ngày ≥ 31 °C: **31 ngày**. Nhạy cảm: ≥ 30 °C: 77 ngày. Không có ngày nào ≥ 33 °C.
- `alert_level ≥ 1` của `daily_heat_stress` giống hệt ≥ 31 °C (đã kiểm: 31 ngày, khớp 100%). `alert_level ≥ 2` có 0 ngày. Vì vậy không có bảng riêng.
- Sản phẩm: OISST (ô 20.625N 107.125E, ngày UTC) và Open-Meteo marine (trung bình ngày địa phương). Khí tượng: nhiệt độ không khí ERA5 trung bình ngày.
- Cách chỉnh, luôn ước lượng ngoài mẫu:
  - `raw`: không chỉnh.
  - `offset`: cộng độ lệch trung vị (cảm biến − sản phẩm) của tập train.
  - `lin`: cảm biến ~ a + b·sản phẩm.
  - `lin_air`: cảm biến ~ a + b·sản phẩm + c·nhiệt độ không khí.
  - Hậu tố `_tuned`: ngưỡng trên giá trị đã chỉnh được chọn để tối đa CSI trên tập train (lưới 0,1 °C). Không có hậu tố: ngưỡng cố định 31.
- Hai cách chia:
  - **split**: train 05-29..07-31 (57 ngày, 21 ngày nóng), test 08-01..10-21 (73 ngày, 10 ngày nóng, còn 72 ngày có sản phẩm).
  - **lomo**: bỏ lần lượt từng tháng (tháng 5 gộp vào tháng 6). Cả 129 ngày được dự đoán ngoài mẫu, 31 ngày nóng.
- Chỉ số: H = trúng, M = bỏ sót, FA = báo động giả. POD = H/(H+M). FAR = FA/(H+FA). CSI = H/(H+M+FA). bias = (H+FA)/(H+M), 1,0 là báo đúng tần suất.

## Phát hiện chính

1. **OISST thô: POD = 0.** Trong cả mùa, OISST cao nhất 30,99 °C. Nó không bao giờ chạm 31, nên không báo ngày nào. Cộng độ lệch trung vị hoặc hồi quy tuyến tính chỉ không đủ (POD 0,00–0,16).
2. **Open-Meteo marine thô bắt được** (POD 0,70–0,81) nhưng báo thừa nhiều (FAR 0,50–0,61), vì nó ấm hơn cảm biến khoảng 0,6 °C.
3. **Bắt ngày nóng cần đặc trưng theo ngày**, không chỉ độ lệch. Cảm biến đo trong vịnh kín, nóng theo nắng và không khí. Thêm nhiệt độ không khí đưa r từ 0,28–0,62 lên 0,75–0,82 và giảm MAE còn 0,57–0,87 °C.
4. **Tốt nhất: marine + hồi quy với nhiệt độ không khí.** Nhưng chỉ ở thời điểm hiện tại (nowcast).
5. **Sản phẩm không hơn cảm biến.** Dùng chính cảm biến hôm qua (persistence) cho CSI 0,50–0,66, cao hơn mọi sản phẩm. Sản phẩm chỉ có ích ở nơi không có cảm biến.
6. **Mẫu rất nhỏ.** Split chỉ có 10 ngày nóng ở test: lệch 1–2 ngày là POD đổi 0,1–0,2. Mọi số bên dưới chưa có khoảng tin cậy.

## Nowcast, ngày nóng ≥ 31 °C

### Split (train Jun–Jul, test Aug–Oct, 10 ngày nóng)

| Sản phẩm | Cách chỉnh | H | M | FA | POD | FAR | CSI | MAE °C | RMSE °C | r |
|---|---|---|---|---|---|---|---|---|---|---|
| OISST | raw | 0 | 10 | 0 | 0,00 | – | 0,00 | 0,99 | 1,21 | 0,28 |
| OISST | offset | 0 | 10 | 0 | 0,00 | – | 0,00 | 0,97 | 1,24 | 0,28 |
| OISST | lin | 0 | 10 | 0 | 0,00 | – | 0,00 | 0,98 | 1,33 | 0,28 |
| OISST | lin_air | 4 | 6 | 2 | 0,40 | 0,33 | 0,33 | 0,87 | 1,10 | 0,82 |
| OISST | raw_tuned (ngưỡng 30,1) | 5 | 5 | 13 | 0,50 | 0,72 | 0,22 | 0,99 | 1,21 | 0,28 |
| OISST | lin_air_tuned (30,7) | 7 | 3 | 6 | 0,70 | 0,46 | 0,44 | 0,87 | 1,10 | 0,82 |
| marine | raw | 7 | 3 | 11 | 0,70 | 0,61 | 0,33 | 1,06 | 1,29 | 0,54 |
| marine | offset | 7 | 3 | 3 | 0,70 | 0,30 | 0,54 | 0,88 | 1,10 | 0,54 |
| marine | lin | 7 | 3 | 3 | 0,70 | 0,30 | 0,54 | 0,86 | 1,10 | 0,54 |
| marine | lin_air | 7 | 3 | 2 | 0,70 | 0,22 | 0,58 | 0,69 | 0,84 | 0,73 |
| marine | raw_tuned (31,0) | 7 | 3 | 11 | 0,70 | 0,61 | 0,33 | 1,06 | 1,29 | 0,54 |
| marine | lin_air_tuned (30,7) | 7 | 3 | 3 | 0,70 | 0,30 | 0,54 | 0,69 | 0,84 | 0,73 |
| cảm biến hôm qua | persistence | 6 | 3 | 3 | 0,67 | 0,33 | 0,50 | 0,45 | 0,63 | 0,87 |

### Leave-one-month-out (129 ngày, 31 ngày nóng)

| Sản phẩm | Cách chỉnh | H | M | FA | POD | FAR | CSI | MAE °C | RMSE °C | r |
|---|---|---|---|---|---|---|---|---|---|---|
| OISST | raw | 0 | 31 | 0 | 0,00 | – | 0,00 | 0,82 | 1,02 | 0,44 |
| OISST | offset | 5 | 26 | 4 | 0,16 | 0,44 | 0,14 | 0,78 | 1,02 | 0,44 |
| OISST | lin | 0 | 31 | 0 | 0,00 | – | 0,00 | 0,81 | 1,03 | 0,39 |
| OISST | lin_air | 13 | 18 | 9 | 0,42 | 0,41 | 0,33 | 0,62 | 0,75 | 0,75 |
| OISST | raw_tuned | 21 | 10 | 29 | 0,68 | 0,58 | 0,35 | 0,82 | 1,02 | 0,44 |
| OISST | lin_air_tuned | 24 | 7 | 17 | 0,77 | 0,41 | 0,50 | 0,62 | 0,75 | 0,75 |
| marine | raw | 25 | 6 | 25 | 0,81 | 0,50 | 0,45 | 0,88 | 1,10 | 0,62 |
| marine | offset | 10 | 21 | 11 | 0,32 | 0,52 | 0,24 | 0,78 | 0,99 | 0,57 |
| marine | lin | 7 | 24 | 3 | 0,23 | 0,30 | 0,21 | 0,72 | 0,93 | 0,57 |
| marine | lin_air | 19 | 12 | 9 | 0,61 | 0,32 | 0,47 | 0,57 | 0,69 | 0,79 |
| marine | raw_tuned | 20 | 11 | 28 | 0,65 | 0,58 | 0,34 | 0,88 | 1,10 | 0,62 |
| marine | lin_air_tuned | 22 | 9 | 13 | 0,71 | 0,37 | 0,50 | 0,57 | 0,69 | 0,79 |
| cảm biến hôm qua | persistence | 23 | 5 | 7 | 0,82 | 0,23 | 0,66 | 0,38 | 0,54 | 0,88 |

Nhận xét:

- `offset` và `lin` làm POD của marine **giảm** (0,81 xuống 0,32 và 0,23). Lý do: các tháng nóng có độ lệch nhỏ hơn trung vị cả mùa, và hồi quy kéo giá trị về trung bình. Chỉnh bằng một số hạng không đủ cho việc bắt đỉnh.
- Chọn ngưỡng theo train (`_tuned`) cứu OISST (POD 0 lên 0,68–0,77) nhưng FAR vẫn 0,41–0,58.
- `lin_air` cố định 31 là bảo thủ (bias tần suất 0,7–0,9). `lin_air_tuned` cân bằng hơn (bias 1,1–1,3).

## Ngưỡng 30 °C (nhạy cảm, 77 ngày)

LOMO. Đây là ngưỡng dễ hơn, nên mọi sản phẩm khá hơn.

| Sản phẩm | Cách chỉnh | H | M | FA | POD | FAR | CSI |
|---|---|---|---|---|---|---|---|
| OISST | raw | 53 | 24 | 21 | 0,69 | 0,28 | 0,54 |
| OISST | lin_air | 55 | 22 | 13 | 0,71 | 0,19 | 0,61 |
| OISST | lin_air_tuned | 68 | 9 | 23 | 0,88 | 0,25 | 0,68 |
| marine | raw | 65 | 12 | 32 | 0,84 | 0,33 | 0,60 |
| marine | offset | 52 | 25 | 9 | 0,68 | 0,15 | 0,60 |
| marine | lin_air | 56 | 21 | 12 | 0,73 | 0,18 | 0,63 |
| marine | lin_air_tuned | 62 | 15 | 25 | 0,81 | 0,29 | 0,61 |

Ở 30 °C, OISST đã dùng được. Vấn đề của OISST là riêng ở ngưỡng 31 vì nó bị nén ở đỉnh (std 0,61 so với 1,12 của cảm biến).

## Dự báo theo thời hạn (lead 1–3 ngày)

**Không có dự báo SST lưu trữ.** Đã thử ngày 2026-10-23:

- `marine-api.open-meteo.com` với `sea_surface_temperature_previous_dayN` (N = 1..7): toàn bộ null cho 2026-05..10.
- `previous-runs-api.open-meteo.com/v1/marine`: lỗi 404.
- `previous-runs-api.open-meteo.com/v1/forecast`: chỉ có SST ngày 0, các `_previous_dayN` null. Giá trị ngày 0 (trung bình 27,1 °C) là một sản phẩm khác, lạnh hơn cảm biến 3 °C, không dùng.
- `historical-forecast-api` có SST ngày 0 (trung bình 30,7 °C, 2026-05..10 đầy đủ) nhưng không có phiên bản theo thời hạn. Chưa đánh giá ở đây; có thể là ứng viên cho lần sau.

Thay thế: **persistence của sản phẩm**. Dự đoán ngày t bằng giá trị sản phẩm ngày t−k. Với `lin_air` dùng nhiệt độ không khí ERA5 của ngày t−k (không dùng của ngày t, để không rò rỉ). Đây là mức sàn, không phải mô hình dự báo. Một dự báo tốt hơn persistence cần dự báo SST thật, hiện chưa có lưu trữ.

LOMO, ≥ 31 °C:

| Lead | Sản phẩm | Cách chỉnh | H | M | FA | POD | FAR | CSI | MAE °C |
|---|---|---|---|---|---|---|---|---|---|
| 0 | marine | lin_air_tuned | 22 | 9 | 13 | 0,71 | 0,37 | 0,50 | 0,57 |
| 1 | marine | raw | 24 | 7 | 26 | 0,77 | 0,52 | 0,42 | 0,95 |
| 1 | marine | lin_air_tuned | 26 | 5 | 14 | 0,84 | 0,35 | 0,58 | 0,59 |
| 1 | OISST | lin_air_tuned | 26 | 5 | 14 | 0,84 | 0,35 | 0,58 | 0,59 |
| 2 | marine | raw | 21 | 10 | 29 | 0,68 | 0,58 | 0,35 | 1,02 |
| 2 | marine | lin_air_tuned | 26 | 5 | 27 | 0,84 | 0,51 | 0,45 | 0,65 |
| 3 | marine | raw | 19 | 12 | 32 | 0,61 | 0,63 | 0,30 | 1,09 |
| 3 | marine | lin_air_tuned | 26 | 5 | 39 | 0,84 | 0,60 | 0,37 | 0,76 |
| 1–3 | OISST | raw | 0 | 31 | 0 | 0,00 | – | 0,00 | 0,87–0,98 |

Nhận xét: lead 1 gần bằng nowcast vì SST đổi chậm. Từ lead 2, FAR tăng lên 0,5–0,6 (CSI giảm còn 0,37–0,45). `lin_air_tuned` đạt POD cao bằng cách báo thừa (bias tần suất 1,7–2,1). Split (10 ngày nóng) cho cùng xu hướng nhưng nhiễu hơn, xem `metrics.csv`.

## Ý nghĩa cho cảnh báo nhiệt

1. **Không dùng OISST thô cho ngưỡng 31 °C.** POD = 0, vì sản phẩm không vượt 31 trong cả mùa. Có thể dùng cho khí hậu dài hạn (xu hướng, lịch), không dùng cho báo ngày nóng.
2. **Sản phẩm vận hành: Open-Meteo marine trung bình ngày**, cộng hồi quy `cảm biến ~ a + b·SST + c·nhiệt độ không khí`, ngưỡng trên giá trị đã chỉnh khoảng 30,7 °C (chọn trên train).
3. **Kỳ vọng nowcast** (≥ 31 °C): POD khoảng 0,7, FAR khoảng 0,3–0,4, CSI khoảng 0,5. Khoảng bất định lớn vì chỉ 31 ngày nóng của một mùa.
4. **Kỳ vọng lead 1 ngày**: tương tự nowcast (POD 0,7–0,8, FAR 0,35). **Lead 2–3 ngày**: FAR 0,5–0,6, chỉ nên là "chú ý", không phải "báo".
5. **Cảnh báo ở mức "theo dõi (≥31 °C)" thôi.** Không có dữ liệu cho mức stress (≥33 °C), vì cảm biến chưa bao giờ đo tới 33 °C.
6. Nơi có cảm biến sống, dùng **cảm biến hôm qua** cho lead 1: tốt hơn mọi sản phẩm (CSI 0,50–0,66). Sản phẩm là phương án cho các điểm không có cảm biến, với giả định hiệu chuẩn Cát Bà áp dụng được (chưa kiểm).
7. Báo cáo hiển thị độ chưa chắc: ghi POD, FAR kèm số ngày mẫu. Giữ nhãn lý thuyết, không đẩy tới nông dân (quy tắc shadow-mode).

## Hạn chế

- Một mùa (2026-05..10), 31 ngày nóng, 10 ngày nóng trong test của split. Không có khoảng tin cậy; chênh lệch dưới ~0,15 giữa các hàng không đáng tin.
- Tháng 10 mát và hầu như không có ngày nóng, nên phần lớn "hit" nằm ở tháng 6–9. LOMO huấn luyện trên các tháng sau để dự đoán tháng trước (không phải dự báo thời gian thực đúng nghĩa). Split là cách gần thực tế hơn nhưng nhỏ hơn.
- Ngưỡng `_tuned` chọn theo CSI trên train, rồi chấm trên test. Ngưỡng này phụ thuộc vào tỷ lệ ngày nóng của tập train (37% ở Jun–Jul).
- Nhiệt độ không khí là ERA5 (tái phân tích), không phải dự báo. Ở lead thực tế cần dự báo nhiệt độ không khí; ở đây dùng giá trị ngày phát hành (persistence), là mức sàn.
- OISST dùng ngày UTC, cảm biến dùng ngày địa phương; lệch giờ chưa hiệu chỉnh. Ô OISST cách cảm biến khoảng 0,1–0,2 độ.
- Sự thật là trung bình ngày của một cảm biến lồng bè. Cảm biến có thể trôi (COD đã hỏng); nhiệt độ chưa kiểm chéo với thiết bị khác.
- Chưa có dự báo SST lưu trữ, nên "lead" chỉ là persistence. Cần bắt đầu lưu snapshot dự báo marine theo giờ phát hành (tương tự `HAP-WeatherSnapshot`) để đánh giá dự báo thật sau vài tháng.
