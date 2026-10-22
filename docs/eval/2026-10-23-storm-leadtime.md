# Đánh giá thời gian báo trước gió mạnh tại NB1 (Cát Bà)

Ngày: 2026-10-23. Trạng thái: shadow, chỉ để nghiên cứu. Không đẩy cho người nuôi.

Câu hỏi: đường dự báo vận hành (đọc gió dự báo tại điểm lồng bè, không biết tâm bão) báo trước gió mạnh được bao nhiêu ngày?

Mã: `experiments/storm_leadtime.py`. Test: `tests/test_storm_leadtime.py`.
Kết quả: `artifacts/experiments/storm-leadtime-20261023b/` (`events.csv`, `day_contingency.csv`, `error_wind_by_lead.csv`, `error_gust_by_lead.csv`, `error_wind_by_year.csv`, `manifest.json`).
Thư mục `storm-leadtime-20261023/` là lần chạy đầu, thiếu bảng theo năm. Để nguyên, không dùng.

## 1. Dữ liệu và phương pháp

- Dự báo quá khứ: Open-Meteo Previous Runs API, `wind_speed_10m_previous_dayN` (N = 1..7) và `wind_gusts_10m_previous_dayN`. Giá trị này là dự báo cho giờ hiệu lực, từ lần chạy phát hành N ngày trước.
- Giờ phát hành là giờ danh định: giờ hiệu lực trừ 24 h x N. Không biết chu kỳ mô hình (00/06/12/18 UTC).
- File: `data/hazards/forecast_runs/previous_runs_nb1_20240101_20261022_fetched20261023.csv` (ghi một lần, có manifest, sha256 `03fde38b...`).
- Vị trí NB1: 20.7189 N, 107.0426 E. Mô hình: mặc định `best_match` của Open-Meteo. Không chọn mô hình cố định.
- Lead 1 có từ 2024-01-19, lead 7 có từ 2024-01-25. Trước đó là null. Kỳ phân tích chung: 2024-01-25 12:00 UTC đến 2026-10-20 23:00 UTC (23 988 giờ, 999 ngày UTC đủ 24 h). Kết thúc ở 10-20 vì ERA5 dừng ở đó.
- Sự thật (truth):
  1. ERA5 theo giờ tại NB1 (`wind_speed_10m`). Là tái phân tích lưới thô, đọc thấp gió bão.
  2. Gió tại điểm theo best-track (`site_beaufort` trong `passages.csv`, oracle, một giá trị cho mỗi cơn).
- Ngưỡng: cấp Beaufort 6, 8, 10 (`core.storm_advisory.BEAUFORT_LOWER_MS`: 10.8, 17.2, 24.5 m/s). Gió theo giờ coi như gió duy trì 10 phút.
- Sự kiện: 19 cơn có `peak_time` trong kỳ phân tích. Cửa sổ = peak_time +- 24 h.
- Lead hours = 24 x N + (giờ truth vượt ngưỡng đầu tiên - giờ dự báo vượt ngưỡng đầu tiên). N là lead dài nhất có dự báo chạm ngưỡng trong cửa sổ.
- Lead 0 (`wind_speed_10m` không hậu tố) trùng ERA5 tuyệt đối (MAE = 0, tương quan 1). Nó không phải dự báo, nên loại khỏi mọi kết luận. Bảng CSV vẫn giữ làm đối chứng.

## 2. Phát hiện quan trọng về chất lượng dữ liệu dự báo

Chuỗi dự báo không đồng nhất theo thời gian và theo lead. Bảng dưới là sai số trung bình (dự báo - ERA5), m/s, theo năm.

| Năm | ERA5 trung bình | Lead 1 | Lead 3 | Lead 6 | Lead 7 |
| --- | --- | --- | --- | --- | --- |
| 2024 | 3.98 | -1.98 | -1.94 | -1.89 | -0.13 |
| 2025 | 3.74 | -1.26 | -1.25 | -1.35 | -0.12 |
| 2026 | 3.73 | +0.11 | 0.00 | -0.18 | -0.07 |

- Lead 1 đến 6 đọc thấp khoảng 2 m/s năm 2024, 1.3 m/s năm 2025. Năm 2026 hết lệch. Có thể do mô hình `best_match` đổi nguồn. Chưa xác minh.
- Lead 7 có trung bình gần ERA5 cả ba năm, khác hẳn lead 1..6. Nhiều khả năng lead 7 lấy từ nguồn khác. Lead 7 có nhiều báo động giả (xem mục 4). Coi lead 7 là không so sánh được. Kết luận chính dùng lead 1..6, lead 7 ghi riêng.
- Hệ quả: POD thấp ở 2024-2025 một phần do lệch thấp có hệ thống, không chỉ do khó dự báo.

## 3. Theo từng cơn bão (cấp 6)

Cột `ERA5` là cấp lớn nhất của ERA5 trong cửa sổ. Cột d1..d7 là cấp lớn nhất của dự báo lead N trong cửa sổ. `Track` là cấp gió tại điểm theo best-track (oracle).

| Tên | Ngày (UTC) | Cách NB1 (km) | Track | ERA5 | d1 | d2 | d3 | d4 | d5 | d6 | d7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MALIKSI | 2024-05-31 | 453 | 4 | 3 | 2 | 3 | 2 | 3 | 2 | 2 | 3 |
| (không tên) | 2024-07-15 | 328 | 4 | 5 | 3 | 3 | 3 | 3 | 3 | 3 | 6 |
| PRAPIROON | 2024-07-22 | 56 | 7 | 6 | 4 | 5 | 5 | 4 | 3 | 3 | 4 |
| YAGI | 2024-09-07 | 21 | 11 | 11 | 9 | 9 | 10 | 9 | 8 | 8 | 8 |
| SOULIK | 2024-09-19 | 405 | 5 | 4 | 2 | 3 | 3 | 3 | 2 | 2 | 3 |
| TRAMI | 2024-10-27 | 482 | 5 | 4 | 4 | 4 | 5 | 4 | 4 | 4 | 6 |
| WUTIP | 2025-06-13 | 209 | 7 | 5 | 4 | 4 | 4 | 3 | 2 | 3 | 3 |
| (không tên) | 2025-06-26 | 276 | 4 | 3 | 3 | 3 | 3 | 2 | 2 | 2 | 3 |
| WIPHA | 2025-07-21 | 17 | 7 | 7 | 6 | 6 | 8 | 6 | 5 | 6 | 4 |
| (không tên) | 2025-08-18 | 41 | 6 | 4 | 3 | 3 | 2 | 3 | 3 | 2 | 6 |
| KAJIKI | 2025-08-25 | 260 | 6 | 7 | 5 | 4 | 5 | 4 | 3 | 2 | 4 |
| NONGFA | 2025-08-30 | 303 | 5 | 6 | 4 | 4 | 3 | 2 | 2 | 2 | 5 |
| RAGASA | 2025-09-24 | 128 | 7 | 5 | 4 | 4 | 4 | 4 | 4 | 4 | 6 |
| BUALOI | 2025-09-28 | 292 | 6 | 7 | 4 | 4 | 6 | 4 | 4 | 5 | 10 |
| MATMO | 2025-10-05 | 134 | 7 | 5 | 6 | 5 | 8 | 5 | 6 | 4 | 6 |
| FENGSHEN | 2025-10-22 | 493 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 |
| MAYSAK | 2026-07-04 | 74 | 7 | 6 | 5 | 6 | 5 | 5 | 5 | 4 | 4 |
| NARRA | 2026-08-23 | 74 | 7 | 6 | 6 | 5 | 6 | 7 | 5 | 2 | 2 |
| SAUDEL | 2026-08-31 | 356 | 3 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 |

Chú ý:
- Lead 0 không in vì trùng ERA5.
- Hàng Bualoi lead 7 cấp 10 (25.5 m/s) là báo động giả theo ERA5 (ERA5 cấp 7).
- Yagi: ERA5 29.6 m/s, dự báo lead 1 chỉ 22.9 m/s (cấp 9). Dự báo đọc thấp 1 đến 3 cấp so với ERA5 ở bão trực tiếp.

### 3.1. Lead báo trước theo ngưỡng (chỉ cơn mà truth chạm ngưỡng)

Lead hours tính tới lần vượt ngưỡng đầu tiên của truth. "N tối đa" là lead dài nhất có dự báo chạm ngưỡng. Cột "N<=6" bỏ lead 7 vì lead 7 không đáng tin (mục 2).

Cấp 6, truth = ERA5:

| Cơn | N tối đa (1..7) | Lead hours | N tối đa (1..6) | Lead hours | Các N có chạm |
| --- | --- | --- | --- | --- | --- |
| YAGI | 7 | 140 | 6 | 136 | 1-7 |
| WIPHA | 6 | 120 | 6 | 120 | 1,2,3,4,6 |
| BUALOI | 7 | 160 | 3 | 57 | 3,7 |
| MAYSAK | 2 | 48 | 2 | 48 | 2 |
| NARRA | 4 | 89 | 4 | 89 | 1,3,4 |
| PRAPIROON | bỏ lỡ | - | bỏ lỡ | - | - |
| KAJIKI | bỏ lỡ | - | bỏ lỡ | - | - |
| NONGFA | bỏ lỡ | - | bỏ lỡ | - | - |

Cấp 6, truth = best-track (oracle): 11 cơn có gió điểm >= cấp 6.

| Cơn | N tối đa (1..7) | Lead hours | N tối đa (1..6) | Lead hours |
| --- | --- | --- | --- | --- |
| YAGI | 7 | 150 | 6 | 146 |
| WIPHA | 6 | 131 | 6 | 131 |
| (không tên) 2025-08 | 7 | 164 | bỏ lỡ | - |
| RAGASA | 7 | 163 | bỏ lỡ | - |
| BUALOI | 7 | 168 | 3 | 65 |
| MATMO | 7 | 146 | 5 | 99 |
| MAYSAK | 2 | 38 | 2 | 38 |
| NARRA | 4 | 83 | 4 | 83 |
| PRAPIROON, WUTIP, KAJIKI | bỏ lỡ | - | bỏ lỡ | - |

Cấp 8: chỉ có một cơn có truth >= cấp 8 trong kỳ (Yagi), cả ERA5 và best-track. Dự báo chạm cấp 8 ở mọi lead 1..7. Lead hours: 144 h (ERA5, N=7) hoặc 140 h (N<=6); 148 h / 144 h theo best-track. WIPHA, BUALOI, MATMO có dự báo chạm cấp 8 ở một lead (3 hoặc 7) nhưng truth không chạm: coi là báo động giả.

Cấp 10: chỉ Yagi. Dự báo chạm cấp 10 chỉ ở lead 3 (lead hours 75). Lead 1, 2, 4, 5, 6 đều chỉ đến cấp 9 trở xuống. Lead 7 của BUALOI chạm cấp 10 nhưng là báo động giả.

Với n = 1 cơn cấp 8 và cấp 10, không có thống kê. Chỉ là một ví dụ.

## 4. Bảng chéo theo ngày (UTC), truth = ERA5

Ngày "có sự kiện" = giá trị lớn nhất trong ngày của ERA5 >= ngưỡng. 999 ngày. Số ngày ERA5 vượt: cấp 6 = 15 ngày, cấp 8 = 1 ngày, cấp 10 = 1 ngày.

Cấp 6 (10.8 m/s):

| Lead N | Hit | Miss | FA | POD | FAR | CSI | Bias tần suất |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 4 | 11 | 1 | 0.27 | 0.20 | 0.25 | 0.33 |
| 2 | 4 | 11 | 0 | 0.27 | 0.00 | 0.27 | 0.27 |
| 3 | 5 | 10 | 3 | 0.33 | 0.38 | 0.28 | 0.53 |
| 4 | 4 | 11 | 0 | 0.27 | 0.00 | 0.27 | 0.27 |
| 5 | 3 | 12 | 2 | 0.20 | 0.40 | 0.18 | 0.33 |
| 6 | 2 | 13 | 1 | 0.13 | 0.33 | 0.13 | 0.20 |
| 7 | 2 | 13 | 13 | 0.13 | 0.87 | 0.07 | 1.00 |

Cấp 8 (17.2 m/s), chỉ 1 ngày có sự kiện (Yagi):

| Lead N | Hit | Miss | FA | POD | FAR | CSI |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 0 | 0 | 1.00 | 0.00 | 1.00 |
| 2 | 1 | 0 | 0 | 1.00 | 0.00 | 1.00 |
| 3 | 1 | 0 | 3 | 1.00 | 0.75 | 0.25 |
| 4 | 1 | 0 | 0 | 1.00 | 0.00 | 1.00 |
| 5 | 1 | 0 | 0 | 1.00 | 0.00 | 1.00 |
| 6 | 1 | 0 | 0 | 1.00 | 0.00 | 1.00 |
| 7 | 0 | 1 | 4 | 0.00 | 1.00 | 0.00 |

Cấp 10 (24.5 m/s), chỉ 1 ngày: chỉ lead 3 bắt được (hit 1). Lead 1, 2, 4, 5, 6 bỏ lỡ. Lead 7 bỏ lỡ và 2 báo động giả. Các số này không có ý nghĩa thống kê.

### 4.1. Sai số gió theo lead (dự báo - ERA5, toàn kỳ, m/s)

| Lead | Bias gió | MAE gió | RMSE gió | Tương quan | Bias giật | MAE giật |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | -1.10 | 1.54 | 2.05 | 0.54 | -4.33 | 4.40 |
| 2 | -1.13 | 1.58 | 2.08 | 0.51 | -4.32 | 4.39 |
| 3 | -1.12 | 1.62 | 2.15 | 0.47 | -4.29 | 4.40 |
| 4 | -1.17 | 1.68 | 2.22 | 0.43 | -4.32 | 4.42 |
| 5 | -1.14 | 1.69 | 2.24 | 0.40 | -4.34 | 4.44 |
| 6 | -1.19 | 1.75 | 2.32 | 0.35 | -4.31 | 4.46 |
| 7 | -0.11 | 1.52 | 2.12 | 0.35 | -2.77 | 3.60 |

MAE tăng chậm theo lead (1.54 đến 1.75 m/s). Tương quan giảm từ 0.54 xuống 0.35. Lead 7 có MAE thấp nhất vì nguồn khác, không vì tốt hơn.

## 5. Ý nghĩa cho câu "báo trước được mấy ngày?"

Đọc kỹ giới hạn mẫu trước khi dùng.

- Bão đổ bộ gần, mạnh (Yagi, cách 21 km): dự báo gió tại điểm chạm cấp 8 và cấp 6 ở mọi lead 1..7. Lead dài nhất tin được (N=6) báo trước khoảng 136 đến 144 h (hơn 5 ngày). Nhưng cấp 10 chỉ thấy ở một lead (3 ngày, 75 h), còn lại dừng cấp 9 hoặc thấp hơn. Cường độ bị đọc thấp.
- Bão vừa (cấp 6-7): bắt được 5/8 cơn theo ERA5 và 6/11 theo best-track (với N<=6). Lead hữu ích thường 2 đến 4 ngày (48 đến 89 h), tối đa khoảng 5 ngày (Wipha 120 h, Yagi 136 h). Các lead dài còn thất thường: có cơn chỉ chạm ở một lead (Bualoi lead 3 và 7, Maysak lead 2).
- Bỏ lỡ: Prapiroon (56 km, cấp 7 theo best-track), Kajiki, Nongfa, Wutip. Dự báo gió điểm không thấy chúng ở bất kỳ lead nào.
- Ngày cấp 6 theo ERA5: POD chỉ 0.27 ở lead 1-4, giảm còn 0.13 ở lead 6. FAR thấp (0-0.4) với lead 1-6. Vậy khi đã có báo động thì phần lớn đúng, nhưng bỏ lỡ nhiều hơn 2/3 số ngày.
- Lead 7: FAR 0.87, không dùng.
- Kết luận thận trọng: với đường vận hành chỉ đọc gió điểm, mức "theo dõi" (cấp 6) có thể cảnh báo sớm khoảng 2 đến 3 ngày, nhưng mới bắt được khoảng một phần ba số ngày. Mức "chuẩn bị" (cấp 8) và cao hơn chưa đủ mẫu (1 cơn), chưa nên khẳng định số ngày. Không dùng kết quả này để nói "báo trước 5-7 ngày".
- Để báo sớm hơn và ổn định hơn cần thông tin tâm bão (vị trí, cường độ dự báo từ JTWC/JMA), tức là theo hướng của `core/storm_advisory.py` kết hợp track dự báo. Đường gió điểm một mình không đủ.

## 6. Hạn chế

1. Truth ERA5 đọc thấp gió bão (lưới thô). Yagi ERA5 29.6 m/s, best-track điểm cấp 11 (28.5-32.6 m/s). Độ "hit" theo ERA5 là cận dưới của cường độ thực.
2. Best-track là oracle sau sự kiện, một giá trị tại giờ cực gần (`peak_time`), không có chuỗi giờ. Lead hours theo best-track tính tới `peak_time` (lúc bão gần nhất), không phải lần vượt ngưỡng đầu, nên không so trực tiếp với cột ERA5.
3. Giờ phát hành là danh định (-24 h x N). Chu kỳ thật 00/06/12/18 UTC nên sai số tới +-12 h.
4. Chuỗi Previous Runs là `best_match`, nguồn mô hình có thể đổi theo thời gian. Bias thay đổi từ -2 m/s (2024) sang 0 (2026). Lead 7 khác nguồn. Chưa xác minh nguồn mô hình thật.
5. Mẫu nhỏ: 19 cơn, 15 ngày cấp 6, 1 ngày cấp 8, 1 ngày cấp 10 trong 2.7 năm. Không có khoảng tin cậy. Mọi tỉ lệ chỉ để mô tả.
6. Ngày tính theo UTC, đủ 24 giờ. Ngày địa phương (UTC+7) sẽ đổi vài số liệu nhỏ.
7. Chỉ dùng gió trung bình theo giờ. Chưa dùng gió giật để đặt ngưỡng; giật dự báo đọc thấp 4 m/s so với ERA5.
8. Chưa hiệu chỉnh bias (ví dụ ánh xạ phân vị) và chưa thử mô hình cố định (ECMWF IFS, GFS). Đó là bước tiếp theo.
9. Cơn có bão cách xa (> 300 km) nhưng gió mùa Đông Bắc mạnh có thể tạo ngày cấp 6 mà không có cơn nào. 15 ngày cấp 6 gồm cả các ngày này. Chưa tách.
