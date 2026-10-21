# 27. Cảnh báo bão và nắng nóng theo lý thuyết + dữ liệu công khai

**Ngày lập:** 22/10/2026. **Trạm:** `06M26042804` (Cát Bà, neo NB1). **Trạng thái:** hồi cứu và shadow; không điều khiển cảnh báo, không gửi thông báo. Quyết định gốc: `docs/decisions.md` #17. Kết quả: `docs/research-log.md` RL-29 (bão), RL-30 (nắng nóng).

## 1. Mục đích

Cảm biến và lấy mẫu nước khó mở rộng. Vì vậy hai chỉ báo nguy cơ dưới đây chỉ dùng lý thuyết, quy định và dữ liệu công khai:

- **A. Bão:** mức phơi nhiễm gió tại lồng NB1 và cấp độ rủi ro tham khảo.
- **B. Nắng nóng:** mức stress nhiệt của cá giò theo nhiệt độ nước mặt (SST).

Mỗi phần gồm một module `core/` thuần (không mạng, có test) và một script `experiments/` tải dữ liệu công khai (ghi một lần vào `data/hazards/`) rồi ghi thư mục chạy trong `artifacts/experiments/`. Mọi đầu ra cảnh báo (advisory) mang `used_by_alerts: False`, `notification_eligible: False`, `basis: "theory_only_unvalidated"` và thẻ `source`; file hindcast (passages, manifest) chỉ mang thẻ `source`.

## 2. Đường dữ liệu: dữ liệu nào được dùng cho việc gì

| Đường | Dữ liệu | Được dùng để | Thẻ `source` |
| --- | --- | --- | --- |
| Vận hành (as-issued) | Open-Meteo dự báo `wind_speed_10m` (+ `wind_gusts_10m`); Open-Meteo marine `sea_surface_temperature`, `wave_height` | Cảnh báo shadow | `forecast` |
| Phơi nhiễm hồi cứu | IBTrACS v04r01 best track | "Lồng đã chịu gì", khí hậu. **Không** dùng cho độ chính xác dự báo hay thời gian báo trước | `best_track_oracle` |
| Thời tiết / SST hồi cứu | ERA5 (Open-Meteo archive); NOAA OISST v2.1 theo ngày | Khí hậu, kiểm chéo Yagi | `reanalysis` |
| Sự thật mặt đất (có sẵn) | Sensor `Temperature` 2026-05-29 → 10-20 | Sai lệch SST so với lồng; mô tả phản ứng khi có bão (n = 2) | `sensor` |

## 3. Ngưỡng và nguồn

| Mục | Giá trị | Nguồn | Trạng thái |
| --- | --- | --- | --- |
| Cấp Beaufort (cận dưới, m/s) | cấp 6 10.8, 7 13.9, 8 17.2, 9 20.8, 10 24.5, 11 28.5, 12 32.7, 13 37.0, 14 41.5, 15 46.2, 16 51.0, 17 56.1 | thang Beaufort dùng trong QĐ 18/2021/QĐ-TTg | quy định |
| Loại bão | ATNĐ 6–7; bão 8–9; bão mạnh 10–11; bão rất mạnh 12–15; siêu bão ≥ 16 | QĐ 18/2021/QĐ-TTg | quy định |
| Cấp độ rủi ro (bão trên vùng biển ven bờ / Đông Bắc Bộ) | ATNĐ, 8–11 → cấp 3; 12–15 → 4; ≥ 16 → 5 | QĐ 18/2021/QĐ-TTg Điều 42 (từ bản tóm tắt thứ cấp) | **cần đối chiếu bản .doc gốc**; chỉ để tham khảo |
| Gió 1 phút → 10 phút | 0.93 (trên biển); độ nhạy 0.88 | Harper et al. 2010, WMO/TD-1555 | cần kiểm bảng trước khi dùng trong luận văn |
| Bậc hành động tại lồng (cấp 6/8/10/12) | `SITE_ACTIONS_VI` | đề xuất của nhóm | **cần chuyên gia / người nuôi xem lại** |
| Ngưỡng sóng cho lồng | chưa có | không tìm thấy nguồn | **chưa đặt**; chỉ báo chiều cao sóng làm ngữ cảnh |
| Theo dõi nhiệt | 31 °C (trung bình ngày) | Sun & Chen 2014: nhiệt độ tối ưu hệ số chuyển đổi thức ăn 31 °C | tài liệu |
| Stress nhiệt | 33 °C | Sun & Chen 2014: tối ưu tăng trưởng 33 °C, giảm ở 35 °C; `cobia_thresholds.json` 33 → 0.5 | tài liệu |
| Nhiệt nặng | 34 °C | Le et al. 2024 (doi:10.3389/faquc.2024.1476881): tăng trưởng −36 % ở 34 so với 30 °C | tài liệu |
| Độ bền | mức 2–3 chỉ tính khi đã có ≥ 3 ngày liên tiếp ≥ 31 °C (nếu không hạ về mức 1) | tự chọn (kiểu DHW) | tham số |
| Cờ nóng + lặng | khí nhiệt tối đa ≥ 35 °C và gió trung bình ngày < 3 m/s | giả thuyết phân tầng → DO thấp | **giả thuyết**, không có DO để kiểm |

Tài liệu mâu thuẫn về nhiệt độ tối ưu của cá giò (27–29 °C cho cá ~22 g trong Le et al. 2024; 33 °C trong Sun & Chen 2014). Vì vậy mức nhiệt là **rủi ro tăng trưởng/stress, không phải tử vong**. `cobia_thresholds.json` không bị sửa.

## 4. Phương pháp

**Bão (`core/storm_advisory.py`)**

1. Lấy các lượt bão IBTrACS trong 500 km quanh NB1, nội suy đường đi mỗi 30 phút (không làm đầy giá trị NaN gốc).
2. Cường độ theo thứ tự TOKYO, HKO, USA×0.93, CMA (đổi gió 1 phút sang 10 phút).
3. Gió tại lồng: nếu có bán kính gió thì lấy giá trị theo bán kính (cận dưới); nếu không thì Rankine biến đổi (α 0.5), chặn ở 34 kt ngoài R34.
4. Loại bão và cấp độ QĐ 18 chỉ tính từ cường độ khi bão ở trong 200 km.
5. Ghi `exposure_method` cho từng lượt (`wind_radii`, `rankine`, `rankine_capped_by_r34`, `no_intensity`).

**Nắng nóng (`core/heat_stress.py`)**

1. Trung bình ngày SST (OISST ô 20.625 N 107.125 E, cách NB1 ~13 km).
2. Mức theo ngày: 1 = ≥ 31 °C; 2 = ≥ 33 °C; 3 = ≥ 34 °C. `alert_level` chỉ giữ mức 2–3 khi đã có ≥ 3 ngày liên tiếp ≥ 31 °C, nếu không hạ về mức 1.
3. Độ lệch cảm biến − OISST (trung vị, 129 ngày) cộng vào OISST để có bản "hiệu chỉnh". Đây chỉ là ca nhạy cảm vì chỉ có một mùa.
4. `experiments/heat_hindcast.py` ghi `offset_status`: `single_season_median` (kèm `offset_note`) hoặc `no_overlap_unadjusted` (không đủ ngày chồng lấn thì chỉ xuất bản thô, không dùng độ lệch 0.0 ngầm).

## 5. Cách chạy

Chạy ở thư mục gốc repo với `.venv`. Tải dữ liệu ghi một lần, không ghi đè; tải lại sẽ có tên theo ngày mới.

```powershell
.venv\Scripts\python experiments\hazard_data.py --help        # lệnh con: ibtracs --subset {WP,last3years,ACTIVE}, oisst, era5, marine-sst
.venv\Scripts\python experiments\storm_hindcast.py --stamp 20261022
.venv\Scripts\python experiments\heat_hindcast.py --stamp 20261022
```

Mỗi `--stamp` tạo thư mục chạy mới (`storm-hindcast-<stamp>/`, `heat-hindcast-<stamp>/`); không chạy lại với stamp đã dùng. Ghi một dòng vào `experiments/RESULTS.md` sau mỗi lần chạy.

## 6. Kết quả tóm tắt

**Bão (`storm-hindcast-20261022d`; các bản `-20261022`, `-b`, `-c` bị thay thế)**

- 265 lượt bão trong 500 km, mùa 1980–2026. Phương pháp: rankine 194, rankine_capped_by_r34 42, wind_radii 25, no_intensity 4.
- Gió tại lồng: cấp 6–7: 92; 8–9: 21; 10–11: 8; ≥ 12: 0; không xác định: 4. Từ cấp 8 trở lên: 29 lượt = 0.62 lượt/năm, rơi vào T6–T11 (đỉnh T9: 0.149/năm; T12–T5 là 0).
- YAGI 2024: 21 km, gió tại lồng ≥ cấp 11 (cận dưới), cấp độ QĐ 18 tham khảo 4; ERA5 tại NB1 tối đa 29.56 m/s (cấp 11).
- WIPHA 2025: lồng cấp 7. MAYSAK 2026 và NARRA 2026: lồng cấp 7. Sensor (mô tả, n = 2): nhiệt độ giảm khoảng 3.3 °C quanh NARRA rồi hồi phục.

**Nắng nóng (`heat-hindcast-20261022`)**

- OISST 1982–2026 cực đại 31.93 °C (2023-07-15). Sensor − OISST: trung vị +0.30 °C, MAE 0.82, r 0.44.
- Số ngày/năm ở mức ≥ 1: thô 5.75 (10 năm đầu 0.1, 10 năm cuối 17.3); hiệu chỉnh 10.16 (0.9 → 28.5). Mức ≥ 2 và ≥ 3: 0 ở mọi năm.
- Xu hướng Theil–Sen: thô +1.41 ngày/thập kỷ (KTC 0.0–3.08); hiệu chỉnh +3.94 (1.94–6.67).
- Lịch mức ≥ 1: tuần ISO 21–40, đỉnh tuần 29. Cờ nóng + lặng: 0.02 ngày/năm.
- Manifest của lần chạy 20261022 có trước trường `offset_status`; run dir ghi một lần nên không chạy lại.

## 7. Điều KHÔNG được tuyên bố

- Đây **không** phải cấp độ rủi ro thiên tai chính thức. Mapping Điều 42 chỉ mang tính tham khảo cho đến khi đối chiếu bản gốc.
- Không có tuyên bố về thời gian báo trước hay độ chính xác dự báo: IBTrACS là oracle.
- Gió tại lồng là cận dưới trong vùng bán kính gió; không có cấp ≥ 12 kể cả Yagi. Rankine bỏ qua che chắn của đất liền / vịnh và tính bất đối xứng.
- Mức nhiệt là rủi ro tăng trưởng/stress, không phải tử vong.
- Độ lệch SST chỉ từ một mùa (độ bất định ~1 °C, lớn hơn chính độ lệch); ô OISST 0.25° ngoài khơi đọc thấp đỉnh nóng trong vịnh.
- Chưa có ngưỡng sóng. Bậc hành động chỉ là đề xuất, cần chuyên gia / người nuôi xem lại.
- Cờ nóng + lặng gió chưa kiểm được (không có DO).
- Phản ứng sensor khi có bão chỉ mô tả, n = 2.

## 8. Cờ shadow

Advisory: `used_by_alerts: False`, `notification_eligible: False`, `basis: "theory_only_unvalidated"`. Mọi đầu ra: `source` ∈ {`forecast`, `best_track_oracle`, `reanalysis`, `sensor`}. Không sửa `core/alerts.py`, ngưỡng `core/weather_advisory.py` hay `HOURLY_VARIABLES` trong `core/weather.py`.

## 9. Việc tiếp theo

1. Thời gian báo trước: Open-Meteo Previous Runs (`reconstructed_run`, decisions #13) cho Yagi / Maysak / Narra.
2. Nối hai cảnh báo vào shadow runner (`runtime/hazard-shadow/*.jsonl`; nhiệt cần `MARINE_ENABLED`).
3. Chỉ số bệnh (Vibrio / Streptococcus theo nhiệt độ – độ mặn), dùng lại chuỗi ngày của `heat_stress`.
4. Lịch thả giống, kết hợp `heat_calendar_watch.csv` và `climatology_month.csv`.
5. Chuyên gia / người nuôi xem lại bậc hành động; đối chiếu Điều 42 với bản gốc.
