# Đánh giá thời gian báo trước gió mạnh tại NB1 (Cát Bà)

Ngày: 2026-10-23 (sửa nguồn dữ liệu cùng ngày). Trạng thái: shadow, chỉ để nghiên cứu. Không đẩy cho người nuôi.

Câu hỏi: đường dự báo vận hành (đọc gió dự báo tại điểm lồng bè, không biết tâm bão) báo trước gió mạnh được bao nhiêu ngày?

Mã: `experiments/storm_leadtime.py`. Test: `tests/test_storm_leadtime.py`.
Kết quả hiện hành: `artifacts/experiments/storm-leadtime-20261023d/`. Mỗi cặp (mô hình dự báo, truth) có bộ file riêng, tên `<loại>_<mô hình>_vs_<truth>.csv`: `events_`, `day_contingency_`, `error_wind_by_lead_`, `error_gust_by_lead_`, `error_wind_by_year_`. Cặp chính: `ecmwf_ifs025_vs_era5`. `manifest.json` ghi cặp nào là chính và tỉ lệ lead 0 trùng truth của mọi cặp.

**Đã thay thế (superseded), để nguyên, không dùng:** `storm-leadtime-20261023/` (lần chạy đầu) và `storm-leadtime-20261023b/`. Cả hai dùng "ERA5" là file `era5_nb1_1982_20261020.csv`. File đó tải không có `models=`, nên thực ra là `best_match` của Open-Meteo: ERA5 trước 2017, từ 2017 là ECMWF IFS 9 km (các lần chạy vận hành ghép lại). Lead 0 của Previous Runs `best_match` trùng nó 100 % số giờ. Vậy truth cũ là chính mô hình dự báo ở tầm ngắn (truth vòng tròn), và mọi POD/FAR/CSI của bản cũ là "IFS tầm 1–7 ngày so với IFS tầm 0", không phải so với tái phân tích.

## 1. Dữ liệu và phương pháp

- Dự báo quá khứ: Open-Meteo Previous Runs API, `wind_speed_10m_previous_dayN` (N = 1..7). Giờ phát hành danh định = giờ hiệu lực − 24 h × N. Không biết chu kỳ thật (00/06/12/18 UTC).
- **Mô hình dự báo được ghim** (`models=`), tải ghi một lần ngày 2026-10-23:
  - Chính: `ecmwf_ifs025` → `data/hazards/forecast_runs/previous_runs_ecmwf_ifs025_nb1_20240101_20261022_fetched20261023.csv` (sha256 `29206e25...`).
  - Phụ: `gfs_seamless` → `previous_runs_gfs_seamless_nb1_20240101_20261022_fetched20261023.csv` (`aea72582...`).
  - Phụ: `best_match` (file cũ `previous_runs_nb1_20240101_20261022_fetched20261023.csv`, không có `models=`). Nguồn đổi theo thời gian, chỉ để đối chiếu.
- Có `*_previous_dayN` hay không (thử tại NB1 ngày 2026-10-23):

| Mô hình | Gió d1..7 | Giật d1..7 | Ghi chú |
| --- | --- | --- | --- |
| `ecmwf_ifs025` | có (từ 2024-02-04) | **không** | Giật chỉ có lead 0 và không đủ giờ |
| `gfs_seamless` | có (từ 2024-01-19) | có | |
| `icon_seamless` | d1..6 | d1..6 | không có d7 |
| `ecmwf_ifs` (9 km) | không | không | chỉ lead 0 |
| `best_match` | có | có | ghép nhiều nguồn |

- **Truth:**
  1. **Chính: ERA5 thật** (Open-Meteo archive `models=era5`), `data/hazards/era5/openmeteo_era5_nb1_1982_20261016.csv` (sha256 `0cec3855...`, ô 20.75 N 107.0 E). Tái phân tích 0,25°, độc lập với các mô hình dự báo, đọc thấp lõi bão. ERA5 trễ khoảng 5 ngày: dữ liệu dừng ở 2026-10-16.
  2. **Phụ: "IFS tầm ngắn (không độc lập)"** = archive `best_match` (file cũ `era5_nb1_1982_20261020.csv`). Chỉ để nối với bản cũ. **Không được đọc như kiểm định.**
  3. Gió tại điểm theo best-track (`site_beaufort` trong `storm-hindcast-20261023e/passages.csv`, oracle, một giá trị mỗi cơn). File passages giống hệt bản 20261022d (cùng sha256 `3c21c365...`).
- **Chốt chặn độc lập:** nếu lead 0 của bất kỳ mô hình nào trùng truth chính (sai khác ≤ 0,005 m/s) quá 50 % số giờ, mã dừng với lỗi. Kết quả: `ecmwf_ifs025` 0,5 %, `best_match` 0,5 %, `gfs_seamless` 0,3 %. Với truth phụ: `best_match` **100 %** (bằng chứng truth cũ là vòng tròn), `ecmwf_ifs025` 0,7 %.
- **Kỳ phân tích chung:** 2024-02-10 00:00 đến 2026-10-16 23:00 UTC (23 520 giờ, 980 ngày UTC đủ 24 h). Đầu kỳ dời từ 01-25 sang 02-10 vì `ecmwf_ifs025` lead 7 bắt đầu 2024-02-10. Cuối kỳ dời từ 10-20 về 10-16 vì ERA5 thật dừng ở đó. Vẫn 19 cơn có `peak_time` trong kỳ.
- Ngưỡng: Beaufort 6, 8, 10 (10,8 / 17,2 / 24,5 m/s). Gió theo giờ coi như gió duy trì 10 phút.
- Sự kiện: cửa sổ = `peak_time` ± 24 h.
- **Lead báo trước (đã sửa):**
  - `consistent_N` = N dài nhất mà **mọi** lead 1..N đều chạm ngưỡng trong cửa sổ (cảnh báo liền mạch từ N ngày trước).
  - `any_N` = lead dài nhất có chạm, cho phép lỗ hổng (định nghĩa cũ, lạc quan).
  - Lead hours = 24 × N + (giờ truth vượt ngưỡng đầu tiên − giờ dự báo vượt ngưỡng đầu tiên). **Giá trị âm** = dự báo chạm ngưỡng sau truth: trúng trong cửa sổ nhưng không báo trước. Không tính là cảnh báo.
  - `consistent_N`/`any_N` cũng được ghi cho cơn mà truth không chạm ngưỡng. Khi đó chúng là **báo động giả mức sự kiện**.
- Lead 0 là phân tích/tầm 0 của mô hình, không phải dự báo. Bảng giữ làm đối chứng.

## 2. Số ngày vượt ngưỡng theo truth (980 ngày)

| Truth | Ngày ≥ cấp 6 | Ngày ≥ cấp 8 | Ngày ≥ cấp 10 | Gió TB (m/s) |
| --- | --- | --- | --- | --- |
| ERA5 thật | **23** | 1 (Yagi) | **0** | 4,4–4,6 |
| IFS tầm ngắn (best_match) | 15 | 1 | 1 | 3,7–4,0 |

ERA5 thật nhiều gió hơn ở mức trung bình (ô lưới khác, 20.75/107.0 so với 20.77/107.02), nhưng thấp hơn nhiều ở lõi bão: **Yagi ERA5 tối đa 18,86 m/s (cấp 8), giật 35,3 m/s**, so với 29,56 m/s của best_match. ERA5 không có ngày cấp 10 nào, nên **cấp 10 chỉ chấm được bằng best-track**.

## 3. Bảng chéo theo ngày (UTC), mô hình ghim `ecmwf_ifs025`, truth = ERA5 thật

Cấp 6 (23 ngày sự kiện):

| Lead N | Hit | Miss | FA | POD | FAR | CSI | Bias tần suất |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 (đối chứng) | 17 | 6 | 0 | 0,74 | 0,00 | 0,74 | 0,74 |
| 1 | 14 | 9 | 1 | 0,61 | 0,07 | 0,58 | 0,65 |
| 2 | 11 | 12 | 1 | 0,48 | 0,08 | 0,46 | 0,52 |
| 3 | 12 | 11 | 2 | 0,52 | 0,14 | 0,48 | 0,61 |
| 4 | 11 | 12 | 2 | 0,48 | 0,15 | 0,44 | 0,57 |
| 5 | 8 | 15 | 2 | 0,35 | 0,20 | 0,32 | 0,43 |
| 6 | 4 | 19 | 3 | 0,17 | 0,43 | 0,15 | 0,30 |
| 7 | 1 | 22 | 1 | 0,04 | 0,50 | 0,04 | 0,09 |

Cấp 8 (1 ngày, Yagi): trúng ở lead 0–4 và 6, trượt ở lead 5 và 7. Báo động giả: lead 3 có 4, lead 4 có 3, lead 5 có 2, lead 6 có 1. Với n = 1 không có thống kê.

Cấp 10: ERA5 không có ngày nào; mọi lần dự báo chạm cấp 10 đều là "báo động giả" theo ERA5. Không có nghĩa.

### 3.1. So sánh mô hình, cấp 6, truth = ERA5 thật (CSI)

| Lead | `ecmwf_ifs025` (ghim) | `gfs_seamless` | `best_match` |
| --- | --- | --- | --- |
| 1 | **0,58** (POD 0,61, FAR 0,07) | 0,45 (POD 0,61, FAR 0,36) | 0,22 (POD 0,22, FAR 0,00) |
| 2 | 0,46 | 0,33 | 0,17 |
| 3 | 0,48 | 0,31 | 0,29 |
| 4 | 0,44 | 0,24 | 0,17 |
| 5 | 0,32 | 0,12 | 0,17 |
| 6 | 0,15 | 0,16 | 0,08 |
| 7 | 0,04 | 0,14 (FAR 0,72) | 0,15 (FAR 0,67) |

`ecmwf_ifs025` tốt nhất ở lead 1–5. GFS bắt được tương tự ở lead 1 nhưng báo thừa nhiều. `best_match` kém nhất vì lead 1–6 của nó đọc thấp có hệ thống ở 2024–2025 (mục 4).

### 3.2. Sai số gió theo lead (`ecmwf_ifs025` − ERA5, toàn kỳ, m/s)

| Lead | Bias | MAE | RMSE | Tương quan |
| --- | --- | --- | --- | --- |
| 0 | −0,32 | 0,82 | 1,11 | 0,85 |
| 1 | −0,22 | 0,90 | 1,23 | 0,82 |
| 2 | −0,23 | 1,01 | 1,35 | 0,77 |
| 3 | −0,24 | 1,09 | 1,48 | 0,73 |
| 4 | −0,27 | 1,17 | 1,59 | 0,68 |
| 5 | −0,32 | 1,26 | 1,72 | 0,62 |
| 6 | −0,37 | 1,38 | 1,91 | 0,53 |
| 7 | −0,42 | 1,47 | 2,04 | 0,44 |

MAE tăng đều theo lead, tương quan giảm đều. Không có bước nhảy ở lead 7. Gió giật theo lead: **không có** cho `ecmwf_ifs025` (API không trả `wind_gusts_10m_previous_dayN`). GFS giật lead 1: bias −1,27, MAE 2,13 m/s.

## 4. Sai số theo năm (dự báo − ERA5 thật, m/s)

| Năm | ERA5 TB | ifs025 d1 | d3 | d6 | d7 | best_match d1 | d3 | d6 | d7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 4,61 | −0,23 | −0,29 | −0,35 | −0,45 | −2,60 | −2,56 | −2,52 | −0,73 |
| 2025 | 4,40 | −0,30 | −0,26 | −0,40 | −0,48 | −1,92 | −1,91 | −2,02 | −0,78 |
| 2026 | 4,37 | −0,13 | −0,16 | −0,34 | −0,31 | −0,52 | −0,63 | −0,82 | −0,71 |

- Mô hình ghim **đồng nhất theo thời gian** (bias −0,1 đến −0,5 m/s mọi năm, mọi lead).
- `best_match` lead 1–6 đọc thấp 2–2,6 m/s năm 2024, 1,9 m/s năm 2025, rồi gần hết năm 2026; lead 7 khác hẳn. "Lead 7 khác nguồn" trong bản cũ là đặc điểm của `best_match`, không phải của dự báo nói chung. Không dùng `best_match` cho đánh giá theo lead.
- GFS: bias −0,5 đến −0,8 m/s, cũng đồng nhất.

## 5. Theo từng cơn bão, `ecmwf_ifs025`

Cột ERA5 là cấp lớn nhất của ERA5 thật trong cửa sổ. d1..d7 là cấp lớn nhất của dự báo lead N. Track là cấp tại điểm theo best-track.

| Tên | Ngày (UTC) | Cách NB1 (km) | Track | ERA5 | d1 | d2 | d3 | d4 | d5 | d6 | d7 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MALIKSI | 2024-05-31 | 453 | 4 | 4 | 3 | 3 | 3 | 3 | 3 | 3 | 3 |
| (không tên) | 2024-07-15 | 328 | 4 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 4 |
| PRAPIROON | 2024-07-22 | 56 | 7 | 6 | 5 | 5 | 5 | 5 | 4 | 4 | 4 |
| YAGI | 2024-09-07 | 21 | 11 | 8 | 12 | 10 | 10 | 9 | 7 | 12 | 4 |
| SOULIK | 2024-09-19 | 405 | 5 | 4 | 4 | 4 | 5 | 4 | 3 | 3 | 3 |
| TRAMI | 2024-10-27 | 482 | 5 | 6 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| WUTIP | 2025-06-13 | 209 | 7 | 5 | 4 | 5 | 4 | 4 | 3 | 3 | 3 |
| (không tên) | 2025-06-26 | 276 | 4 | 3 | 3 | 3 | 4 | 4 | 4 | 4 | 4 |
| WIPHA | 2025-07-21 | 17 | 7 | 7 | 7 | 7 | 9 | 6 | 8 | 6 | 7 |
| (không tên) | 2025-08-18 | 41 | 6 | 5 | 4 | 4 | 4 | 4 | 3 | 3 | 3 |
| KAJIKI | 2025-08-25 | 260 | 6 | 7 | 7 | 6 | 6 | 6 | 7 | 5 | 3 |
| NONGFA | 2025-08-30 | 303 | 5 | 6 | 6 | 5 | 5 | 5 | 4 | 4 | 5 |
| RAGASA | 2025-09-24 | 128 | 7 | 4 | 5 | 6 | 5 | 9 | 9 | 6 | 4 |
| BUALOI | 2025-09-28 | 292 | 6 | 7 | 7 | 7 | 7 | 8 | 7 | 6 | 4 |
| MATMO | 2025-10-05 | 134 | 7 | 6 | 6 | 5 | 8 | 6 | 6 | 5 | 5 |
| FENGSHEN | 2025-10-22 | 493 | 4 | 5 | 4 | 4 | 4 | 4 | 4 | 4 | 4 |
| MAYSAK | 2026-07-04 | 74 | 7 | 6 | 6 | 6 | 5 | 5 | 5 | 4 | 4 |
| NARRA | 2026-08-23 | 74 | 7 | 6 | 6 | 5 | 6 | 7 | 5 | 2 | 2 |
| SAUDEL | 2026-08-31 | 356 | 3 | 4 | 4 | 4 | 4 | 5 | 4 | 4 | 4 |

Yagi: ERA5 thật chỉ cấp 8 (18,9 m/s), trong khi dự báo lead 1 và 6 lên cấp 12. Ở bão đổ bộ gần, mô hình 0,25° có thể cao hơn ERA5; ERA5 là cận dưới.

### 5.1. Lead báo trước, cấp 6, truth = ERA5 thật (10 cơn chạm cấp 6)

| Cơn | Consistent N | Lead hours | Any-lead N | Lead hours | Lead có chạm |
| --- | --- | --- | --- | --- | --- |
| WIPHA | 7 | 134 | 7 | 134 | 1–7 |
| YAGI | 6 | 115 | 6 | 115 | 1–6 |
| BUALOI | 6 | 111 | 6 | 111 | 1–6 |
| KAJIKI | 5 | 100 | 5 | 100 | 1–5 |
| MAYSAK | 2 | 49 | 2 | 49 | 1, 2 |
| MATMO | 1 | 30 | 5 | 119 | 1, 3, 4, 5 |
| NONGFA | 1 | 21 | 1 | 21 | 1 |
| NARRA | 1 | −8 (trễ, không báo trước) | 4 | 69 | 1, 3, 4 |
| PRAPIROON | bỏ lỡ | – | bỏ lỡ | – | – |
| TRAMI (482 km) | bỏ lỡ | – | bỏ lỡ | – | – |

Báo động giả mức sự kiện, cấp 6: RAGASA (ERA5 cấp 4; dự báo chạm ở lead 2, 4, 5, 6).

Truth = best-track (11 cơn có gió điểm ≥ cấp 6): consistent N / lead hours: WIPHA 7 / 151, YAGI 6 / 127, BUALOI 6 / 120, KAJIKI 5 / 117, MAYSAK 2 / 41, MATMO 1 / 11 (any 5 / 100), NARRA 1 / 6 (any 4 / 83), RAGASA không liền mạch (any 6 / 130). Bỏ lỡ: PRAPIROON, WUTIP, (không tên) 2025-08-18.

So sánh nhanh (cấp 6, ERA5, consistent N): `best_match` chỉ có YAGI 7, WIPHA 4, MATMO 1, NARRA 1 (trễ); bỏ lỡ PRAPIROON, KAJIKI, NONGFA. `gfs_seamless`: YAGI 7, BUALOI 7, WIPHA 4, KAJIKI 4, TRAMI 3, NONGFA 3, PRAPIROON 2, NARRA 1; bỏ lỡ MAYSAK; MATMO không liền mạch.

### 5.2. Cấp 8 và cấp 10

- Cấp 8, ERA5: chỉ YAGI là sự kiện. **Consistent 4 ngày (92 h)**, any-lead 6 (123 h); lead 5 trượt (chỉ cấp 7). Báo động giả mức sự kiện: WIPHA (lead 3, 5), RAGASA (4, 5), BUALOI (4), MATMO (3).
- Cấp 10: ERA5 không có. Theo best-track chỉ YAGI: **consistent 3 ngày (73 h)**, any-lead 6 (126 h).
- n = 1 cơn. Chỉ là ví dụ, không có thống kê.

## 6. Ý nghĩa cho câu "báo trước được mấy ngày?"

- Truth cũ (best_match) làm kết quả trông tệ hơn thực tế: CSI cấp 6 lead 1 là 0,25 trong bản cũ, nay 0,58 với mô hình ghim và ERA5 thật. Phần lớn chênh lệch đến từ việc `best_match` lead 1–6 đọc thấp 2 m/s năm 2024–2025, không phải từ độ khó dự báo.
- Với `ecmwf_ifs025`, mức "theo dõi" (cấp 6, theo ERA5): lead 1 bắt 61 % số ngày với FAR 0,07; lead 2–4 khoảng 50 % với FAR ≤ 0,15; lead 5 còn 35 %; lead 6–7 gần như mất.
- Theo cơn: các cơn đổ bộ gần hoặc rộng (Wipha, Yagi, Bualoi, Kajiki) được cảnh báo liền mạch 5–7 ngày (100–134 h). Cơn yếu/xa hơn thường chỉ 1–2 ngày (Maysak, Nongfa, Matmo), Narra chỉ chạm sau khi gió đã lên. Bỏ lỡ 2/10 cơn (Prapiroon, Trami).
- Mức "chuẩn bị" (cấp 8) và cao hơn: 1 cơn. Yagi liền mạch 4 ngày ở cấp 8 và 3 ngày ở cấp 10 (best-track). Chưa được nói "báo trước 5–7 ngày" cho bão mạnh.
- Kết luận thận trọng: đọc gió điểm từ một mô hình ghim (`ecmwf_ifs025`) đủ cho mức "theo dõi" 2–4 ngày trước. Mức cao hơn vẫn cần thông tin tâm bão (track/cường độ dự báo), theo hướng `core/storm_advisory.py`.

## 7. Hạn chế

1. ERA5 0,25° đọc thấp lõi bão (Yagi 18,9 m/s so với best-track cấp 11). "Hit" theo ERA5 là cận dưới của cường độ thật; cấp 10 không chấm được bằng ERA5.
2. ERA5 và mô hình dự báo dùng ô lưới khác nhau; ERA5 nhiều gió hơn ở mức nền (TB 4,4–4,6 so với 3,7–4,0 m/s của best_match), nên số ngày cấp 6 (23) cao hơn bản cũ (15). Một phần "bỏ lỡ" có thể là gió mùa nền mà mô hình 0,25° đọc thấp, không phải bão.
3. Best-track là oracle, một giá trị tại `peak_time`. Lead hours theo best-track tính tới `peak_time`, không so trực tiếp với cột ERA5.
4. Giờ phát hành là danh định (−24 h × N); sai số tới ±12 h.
5. Mẫu nhỏ: 19 cơn, 23 ngày cấp 6, 1 ngày cấp 8 trong 2,7 năm. Không có khoảng tin cậy.
6. Ngày tính theo UTC, đủ 24 giờ.
7. Gió giật theo lead không có cho mô hình ghim. Chưa hiệu chỉnh bias (ví dụ ánh xạ phân vị).
8. Chưa tách ngày cấp 6 do gió mùa Đông Bắc khỏi ngày có bão.
