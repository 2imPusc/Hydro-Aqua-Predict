# Chỉ số nguy cơ môi trường gây bệnh cho cá giò nuôi lồng (Cát Bà) — đánh giá 2026-10-23

**Trạng thái:** lý thuyết, shadow. `used_by_alerts: False`, `notification_eligible: False`, `basis: "theory_only_unvalidated"`. Nhãn: *nguy cơ điều kiện môi trường, không phải chẩn đoán*. Không nối vào `core/alerts.py`.
**Mã:** `core/disease_risk.py`, `experiments/disease_hindcast.py`, `experiments/disease_events.csv`. **Run chính thức:** `artifacts/experiments/disease-hindcast-20261023b/` (mưa và nhiệt độ không khí = **ERA5 thật**, `models=era5`). Run `disease-hindcast-20261023` **bị thay thế**: mưa lấy từ `era5_precip_nb1_1982_20261020.csv` và nhiệt độ không khí từ `era5_nb1_1982_20261020.csv`, cả hai tải không có `models=` nên là `best_match` (ERA5 trước 2017, ECMWF IFS 9 km từ 2017), không phải ERA5; hai file đó giữ nguyên, dùng như nhãn `best_match`. Dữ liệu mưa ERA5 thật: `data/hazards/era5/openmeteo_era5_precip_nb1_1982_20261016.csv` (`hazard_data.py era5-precip --model era5 --end 2026-10-16`, ghi một lần, manifest ghi `model`); nhiệt độ không khí: `openmeteo_era5_nb1_1982_20261016.csv`. Cột `rain_source` / `cold_air_source` trong output ghi nguồn.

## 1. Kết luận ngắn

- Với khí hậu Cát Bà, **nhiệt độ nước một mình không phân biệt được ngày nguy cơ**: các cửa sổ nhiệt trong tài liệu phủ gần cả năm. Trên OISST 1982–2025, mức "thấp" không xuất hiện ngày nào (≥ trung bình: 365.2 ngày/năm); "cao" 216.6 ngày/năm, tuần ISO 16–48.
- Kiểm tra với 5 sự kiện cá lồng chết hàng loạt có nguồn (QN/HP + Thái Bình): 3/5 có ngày "cao" trong cửa sổ, kỳ vọng theo khí hậu 0.659 (≈ 3.3/5) → `no_skill_over_climatology`; kết luận **không bền** khi dịch ngưỡng ±1 °C (−1 °C cho 4/5). Chỉ 2 sự kiện có tác nhân bệnh được nêu → `insufficient_evidence` cho phần bệnh. Nếu chỉ tính QN/HP thì n = 3 (4 nếu kèm rét 2008 miền Bắc) → cũng `insufficient_evidence`.
- Cơ chế duy nhất riêng cho cá giò và riêng cho miền Bắc (lạnh kéo dài, Nhu et al. 2011) **bị OISST bỏ sót**: rét 2008 OISST thấp nhất 17.44 °C (nguồn báo 15 °C > 5 tuần); rét 2016 OISST 20.2 °C (nguồn báo < 10 °C). Ca nhạy cảm dùng nhiệt độ không khí ERA5 thật bắt được 2008 (cold_risk 1.0) và một phần 2016 (0.6, chuỗi < 14 ngày).

## 2. Nguồn tài liệu (chỉ số đã đọc trực tiếp)

| Nhóm | Nguồn | Nơi đăng / DOI | Con số đã đọc | Dùng làm |
| --- | --- | --- | --- | --- |
| Cá giò, VN, lạnh | Nhu et al. 2011 | Aquaculture 315:20–25, doi:10.1016/j.aquaculture.2010.07.024 | ngừng ăn < 18 °C; T1–T2/2008 nước 15 °C > 5 tuần → cá chết hàng loạt; lạnh > 2 tuần → nhiễm nấm, vi khuẩn (loét, xuất huyết); ngừng lớn < 22 °C; Amyloodinium gây chết cao ở trại giống RIA-1 2005–2006 | nhóm lạnh: 1 ở ≤ 15, 0 ở ≥ 22, đủ trọng số khi ≥ 14 ngày < 18 °C |
| Vibrio | Zhang, He & Austin 2020 | Mar Life Sci Technol, doi:10.1007/s42995-020-00037-z | V. harveyi gây bệnh ở cá sòng Nhật khi nước > 25 °C (dẫn Iwamoto) | vibrio 20→25 °C, không có cận trên |
| Vibrio | Takemura et al. 2014 | Front Microbiol, doi:10.3389/fmicb.2014.00038 | V. parahaemolyticus ưa nước > 20 °C; tổng Vibrio tăng theo nhiệt độ **và** độ mặn | điểm 20 °C; mưa không làm tăng Vibrio |
| Photobacterium d. piscicida | Varvarigos 2020 | CIHEAM Options Méditerr. B 75:83–96 | dịch ở cơ sở nuôi thương phẩm khi nước > 20 °C; trại giống dùng nước > 18 °C bị quanh năm | photobacterium 18→20 °C |
| Photobacterium d. piscicida | Romalde 2002 | Int Microbiol 5:3–9, doi:10.1007/s10123-002-0051-6 | sinh trưởng 15–32.5 °C, tối ưu 22.5–30 °C | cận trên 30→32.5 °C |
| Streptococcus | Bromage & Owens 2009 (tóm tắt) | Aquaculture 290:224–228, doi:10.1016/j.aquaculture.2009.02.038 | S. iniae (cá chẽm lồng biển): chết tăng ở 25–28 °C, giảm ngoài khoảng; pH, độ mặn không ý nghĩa; pH < 6 gây chết cấp | streptococcus 23/25/28/30 (vai ±2 °C là tự chọn) |
| Amyloodinium | Paperna 1984 | doi:10.1051/parasite/1984591007 (tóm tắt Europe PMC) | sinh sản tối ưu 18–30 °C, nhanh nhất 23–27; ngừng ở 15; hỏng ở 35; lây nhiễm hiệu quả chỉ 10–60 ppt | amyloodinium 15/18/30/35 |
| Amyloodinium | Pereira et al. 2011 | Aquaculture, doi:10.1016/j.aquaculture.2010.11.011 | số trophont tương quan **dương** với độ mặn | mưa không làm tăng ký sinh |
| Cryptocaryon | Yin et al. 2023 (tóm tắt Europe PMC) | Aquaculture, DOI chưa xác minh | 15 °C không nở; 15–18 °C phân cắt thấp; nở cao nhất 27 °C; lây nhiễm 18 °C thấp hơn 27 và 33 °C | cryptocaryon 15/21/33/– |
| Cryptocaryon | Kong et al. 2022 | Aquaculture, doi:10.1016/j.aquaculture.2022.738166 | độ mặn 5‰ và 40‰ giảm lây nhiễm; tối ưu 20‰ | mưa không làm tăng ký sinh |
| Mưa lớn | QĐ 46/2014/QĐ-TTg Đ.4 K.15 | (hết hiệu lực; bản thay thế QĐ 18/2021 chưa đối chiếu câu chữ) | mưa to 51–100 mm/24 h; mưa rất to > 100 mm/24 h | ngưỡng 100 mm (cửa sổ 3 ngày là tự chọn) |
| Mùa bệnh VN | Ly Van Khanh et al. 2017 | VJMST 17(1), doi:10.15625/1859-3097/17/1/8004 | cá giò, cá mú lồng ở Kiên Giang: bệnh chủ yếu T4–T5 và T7–T9 | chỉ mô tả (miền Nam) |
| Nocardia | Nguyen AT et al. 2026 | J Fish Dis, doi:10.1111/jfd.70171 | N. seriolae ở cá nâu VN, chết tới 70 %; không có số nhiệt | **không đặt ngưỡng** |
| Neobenedenia | Liu YM et al. 2021 (tóm tắt) | DOI không có | cá chim vây vàng Trạm Giang: nhiễm cao T1–T4, tương quan âm với nhiệt độ | **không đặt ngưỡng** |

Không trích dẫn (không mở được bản gốc): AFS Blue Book "Photobacteriosis", Lopez et al. 2002 (cá giò Bành Hồ), con số Nocardia "21 vs 24–33 °C" trên Inter-Research. Ngưỡng Streptococcus lấy từ cá chẽm; các bài S. dysgalactiae trên cá giò Đài Loan không có số nhiệt.

## 3. Phương pháp

- **Thành viên:** hình thang (a, b, c, d) trên nhiệt độ nước trung bình ngày cho 5 nhóm ấm (bảng trên). Chỉ số ấm = **trung bình** 5 nhóm (tỷ lệ nhóm mầm bệnh gặp nhiệt độ thuận lợi). Nhóm lạnh: tuyến tính 15→22 °C; trước khi có ≥ 14 ngày liên tiếp < 18 °C bị chặn ở 0.6.
- **Cờ stress vật chủ (giả thuyết):** mưa 3 ngày ≥ 100 mm (proxy giảm độ mặn) hoặc |ΔT 3 ngày| ≥ 3 °C → cộng 0.25. Mưa tác động lên **vật chủ**, không lên mầm bệnh: tài liệu ký sinh trùng và Vibrio chỉ theo hướng ngược lại.
- **Tổng hợp:** chỉ số = max(chỉ số ấm, nguy cơ lạnh) + cờ, cắt [0, 1]. Mức: thấp < 0.4 ≤ trung bình < 0.75 ≤ cao.
- **Tham số tự chọn:** 0.4/0.75, 0.25, 100 mm/3 ngày, 3 °C/3 ngày, vai ±2 °C của Streptococcus, chặn 0.6, phép trung bình.
- **Dữ liệu:** OISST ô 20.625 N 107.125 E (1982–2026), ERA5 mưa và nhiệt độ không khí tại NB1 (`reanalysis`), sensor `Temperature` 2026-05-29 → 10-21; ERA5 thật chỉ tới 2026-10-16, ngày sau đó không có mưa (`sensor`, ngày ≥ 1296 bản ghi).
- **Đánh giá:** cửa sổ = 14 ngày trước ngày bắt đầu đến ngày kết thúc sự kiện; "trúng" = có ngày ở mức ≥ 1 / = 2. So với xác suất khí hậu: cùng cửa sổ ngày-trong-năm ở 44 năm đủ (gồm cả năm sự kiện). Sự kiện nghi ô nhiễm (Phù Long 2026) liệt kê nhưng không chấm.

## 4. Kết quả (`disease-hindcast-20261023b`, ERA5 thật; run `20261023` best_match bị thay thế)

**Khí hậu (OISST, 44 năm đủ 1982–2025)**

- Ngày/năm: cao 216.6; ≥ trung bình 365.2; nguy cơ lạnh cao 0.05 (ERA5 không khí: 3.41; run best_match cũ: 3.68).
- Ngày/năm thành viên = 1: vibrio 202.6, photobacterium 284.0, streptococcus 67.3, amyloodinium 325.0, cryptocaryon 287.5.
- Lịch tuần ISO (tỷ lệ ngày "cao"): ≥ 0.5 từ tuần 16 đến 48; hai đỉnh tuần 19–21 và 41–45 (= 1.0), lõm tuần 28–31 (≈ 0.75) vì ngày > 30 °C rơi khỏi vai trên của Streptococcus và Photobacterium.
- Xu hướng Theil–Sen (ngày/thập kỷ): cao −5.59 (KTC −10.0 … −0.57). Đây là **hệ quả của vai trên** (photobacterium −20.0, amyloodinium −16.25, streptococcus −7.26; vibrio +5.0, cryptocaryon +1.38), không phải nguồn nào nói ấm lên làm giảm bệnh.
- Cờ mưa: 8.34 ngày/năm (best_match cũ: 7.7); cờ đổi nhiệt nhanh: 0.52 ngày/năm.
- Độ nhạy ±1 °C: cao 191.5 / 216.6 / 218.0 ngày/năm (−1 / 0 / +1); tuần cao 15–50 / 16–48 / 17–47.

**Giai đoạn sensor (130 ngày)**: cao 76, trung bình 54, thấp 0. Cùng ngày, OISST cho 99 ngày cao; khớp mức 0.690 (cũ: 75/55, 98, 0.674). Sensor ấm hơn OISST (+0.3 °C trung vị, RL-30) nên nhiều ngày hè vượt vai trên → xuống "trung bình". Cờ mưa 14 ngày (best_match cũ: 10), đổi nhiệt nhanh 5 ngày.

**Sự kiện** (`event_scores.csv`)

| Sự kiện | Cửa sổ | Mức max (OISST) | T min–max (°C) | Lạnh OISST / ERA5 khí | Cờ mưa | P khí hậu "cao" |
| --- | --- | --- | --- | --- | --- | --- |
| Rét miền Bắc 2008 (Nhu) | 2007-12-18 → 2008-02-29 | 1 | 17.44–22.86 | 0.6 / 1.0 | không | 0.273 |
| Rét Thái Bình 2016 | 2016-01-08 → 01-27 | 1 | 20.22–21.49 | 0.25 / 0.6 | không | 0.023 |
| Bến Do, Cẩm Phả 2016 | 2016-07-26 → 08-15 | 2 | 29.96–31.85 | 0 / 0 | có | 1.0 |
| Lan Hạ 2018 (nấm mang) | 2018-10-03 → 10-24 | 2 | 26.65–28.95 | 0 / 0 | không | 1.0 |
| Vân Đồn 2025 (độ mặn 20‰) | 2025-09-17 → 10-31 | 2 | 27.45–30.32 | 0 / 0.27 | có | 1.0 |
| Phù Long 2026 (nghi nước thải, không chấm) | 2026-06-07 → 07-10 | 2 | 29.95–30.92 | 0 / 0 | có | 1.0 |

- Trúng "cao" 3/5, kỳ vọng khí hậu 0.659 → `no_skill_over_climatology`; không bền với ±1 °C.
- Cờ mưa có ở 2/5 sự kiện, đúng hai sự kiện mà nguồn quy cho mưa (khí hậu cùng cửa sổ 0.264; best_match cũ 0.245). Đây chỉ là kiểm tra ERA5 tái hiện được mưa đã báo, **không** chứng minh chỉ số báo trước bệnh.
- Hai sự kiện rét (2008: 1.0, Thái Bình 2016: 0.6) vẫn được ERA5 không khí thật bắt, cùng giá trị với run cũ; ERA5 thật không đổi cờ mưa theo sự kiện (chỉ đổi xác suất khí hậu: Bến Do 0.386, Lan Hạ 0.341, Vân Đồn 0.591, Phù Long 0.295) và không đổi kết luận (`no_skill_over_climatology`, không bền ±1 °C). Vân Đồn: nguy cơ lạnh không khí 0.282 (cũ 0.271).
- Ba sự kiện mùa ấm "trúng" chỉ vì cửa sổ nằm trong mùa luôn "cao" (P khí hậu 1.0).

## 5. Hạn chế

- Không có đo DO, độ mặn; mưa chỉ là proxy độ mặn, không tính dòng chảy sông (Bạch Đằng, Cấm) hay thủy triều.
- Ngưỡng lấy từ loài khác (cá chẽm, cá tráp, cá sòng, cá đù vàng) hoặc thí nghiệm sinh trưởng in vitro; chỉ nhóm lạnh là riêng cho cá giò ở VN.
- OISST 0.25° ngoài khơi đọc thiếu lạnh ven bờ (min 45 năm 15.75 °C) và thiếu đỉnh nóng; sensor chỉ có T5–T10, không kiểm được nhóm lạnh.
- 5 sự kiện, ngày 2008 và Vân Đồn 2025 chỉ chính xác tới tháng; Thái Bình không phải cá giò, chỉ một bài báo. Nguồn sự kiện là báo chí, chưa có xét nghiệm công bố.
- Không đặt ngưỡng cho Nocardia, Neobenedenia, Lactococcus (không đọc được số nhiệt cho cá biển).

## 6. Việc tiếp theo

1. Nhóm lạnh nên chạy trên nhiệt độ ven bờ (sensor mùa đông 2026–27, hoặc ERA5 không khí đã hiệu chỉnh) thay vì OISST.
2. Thu nhật ký bệnh / xét nghiệm của trại (Trung tâm Quan trắc Môi trường và Bệnh thủy sản miền Bắc) để có sự kiện có tác nhân và ngày chính xác.
3. Bổ sung đo độ mặn tại lồng trước khi dùng cờ mưa.
4. Thêm một dòng `experiments/RESULTS.md` cho run này (chưa ghi theo yêu cầu nhiệm vụ).
