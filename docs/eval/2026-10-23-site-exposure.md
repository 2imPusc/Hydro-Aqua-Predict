# Phơi nhiễm gió, sóng, dòng chảy theo từng điểm lồng — 2026-10-23

**Trạng thái:** lý thuyết, hồi cứu, shadow. Mọi dòng mang `used_by_alerts: False`,
`notification_eligible: False`, `basis: "theory_only_unvalidated"`. Không sửa `core/alerts.py` hay ngưỡng của
`core/storm_advisory.py`.
**Mã:** `core/site_exposure.py` (thuần, có test `tests/test_site_exposure.py`), `experiments/site_exposure.py`.
**Run:** `artifacts/experiments/site-exposure-20261023/` (14 trạm, 4 điểm thiệt hại Yagi, 33 tâm polygon nuôi OSM,
463 điểm lưới 0,025°).

## 1. Câu hỏi

Cùng một cơn bão, lồng nào chịu gió và sóng mạnh hơn? Bản tin bão cho gió "trên vùng biển". Tại lồng,
gió bị đảo/núi che bớt, còn sóng phụ thuộc đà gió (fetch: khoảng nước trống phía đầu gió) và độ sâu.
Mục tiêu: với gió dự báo (tốc độ + hướng), ước lượng gió tại chỗ, sóng có nghĩa Hs và bậc cảnh báo cho từng điểm.

## 2. Phương pháp

| Bước | Cách làm | Nguồn |
| --- | --- | --- |
| Đà gió | Từ điểm lồng, bắn tia **về phía gió thổi tới** (gió từ hướng θ ⇒ tia về θ), bước 100 m, tối đa 200 km, trên mặt nạ nước OSM (`paths.WATER_SHAPEFILE`, phủ 106–109E, 19–21,92N). Đà gió thẳng = trung vị 3 tia θ−6°, θ, θ+6° (lựa chọn của nhóm, tránh một tia lọt khe đảo). Tia ra khỏi phạm vi mặt nạ trước khi gặp đất → gán 200 km, cờ `fetch_censored`. | SPM 1984 §3-V-4: dùng đà gió thẳng |
| Đà gió hiệu dụng | Saville: F_e = Σ F_i cos²α_i / Σ cos α_i, 15 tia cách 6°, ±42°. **Chỉ là chỉ số phơi nhiễm**, không dùng tính sóng. | Saville 1954 (theo ví dụ USDA TR-69 (1983), Western Dam Engineering 2013); SPM 1984 tr. 3-51: "Effective fetch should not be used with the growth curves presented herein" |
| Che chắn địa hình | Lấy cao độ DSM dọc 5 tia ngược gió (θ±10°, bước 30 m, tới 15 km). Mỗi tia lấy vật cản có x/H nhỏ nhất (H ≥ 5 m), hệ số gió = đường "hàng rào kín": 25 % ở 5H, 70 % ở 10H, 90 % ở 15H, 95 % ở 20H, 100 % ở 30H; **sàn 0,5** (giả định). Hệ số hướng = trung bình 5 tia. | Brandle, Zhou & Hodges, *How windbreaks work*, UNL EC1763 (2006), Hình 2 |
| Sóng | U_A = 0,71 U^1,23 (3-28a). Nước nông (3-39/3-40) với độ sâu = trung bình ETOPO dọc tia đà gió; nước sâu (3-33/3-34), trần sóng phát triển hoàn toàn (3-36/3-37); lấy min giữa giới hạn đà gió và giới hạn thời gian gió (3-35), **thời gian gió giữ hướng 3 h (giả định)**. Kiểm: U_A 20 m/s, F 30 km → 1,77 m (SPM tr. 3-47 ghi 1,75 m). | Shore Protection Manual 1984, tập 1, ch. 3 |
| Độ sâu | ETOPO 2022 15″ (~460 m, EGM2008), không phải số 0 hải đồ. | `docs/eval/2026-10-23-bathymetry-map.md` |
| Dòng chảy | Open-Meteo marine năm 2024 (`data/suitability/2024`, km/h ÷ 3,6), điểm gần nhất (lưới 0,083°). Mô hình MeteoFrance SMOC ~8 km, "considering Eulerian, Waves and Tides" (có thủy triều); tài liệu Open-Meteo: "Accuracy at coastal areas is limited". | open-meteo.com/en/docs/marine-weather-api |
| Phân lớp | Sóng NS 9415 bảng A.1: A 0–0,5; B 0,5–1,0; C 1,0–2,0; D 2,0–3,0; E > 3,0 m. Dòng NS 9415 bảng A.2: a < 0,3; b 0,3–0,5; c 0,5–1,0; d 1,0–1,5; e > 1,5 m/s. Lồng nổi: sóng < 1,0 m, dòng 10–100 cm/s (lý tưởng < 50). | NS 9415 (bảng trong slide Lader et al., SINTEF, OMAE2017-61659); NACA/FAO Seafarming RAS/86/024 (1989), Bảng 1 |
| Bậc cảnh báo | bậc gió = `site_action(beaufort(gió tại chỗ))` (cấp 6/8/10/12 → 1/2/3/4); bậc sóng A→0, B→1, C→2, D→3, E→4; **bậc = max(gió, sóng), +1 nếu dòng ≥ 1,0 m/s** (dòng dùng p95 năm 2024). Ánh xạ sóng→bậc và luật cộng là **giả định**. | nhóm đề xuất |
| Lớp phơi nhiễm | Hs lớn nhất (mọi hướng) khi gió ngoài khơi cấp 8 (17,2 m/s): A = kín, B = bán kín, ≥ C = hở (giả định). | — |
| Hướng nguy hiểm | Hs ≥ 2,0 m (lớp D) khi gió ngoài khơi cấp 10 (24,5 m/s). **Hướng cần chú ý:** 1,0–2,0 m (vượt giới hạn 1,0 m của lồng nổi). | — |

Gió cấp 8/10/12 lấy **cận dưới** của cấp (17,2 / 24,5 / 32,7 m/s). Bậc trong bảng là bậc **lớn nhất trên 16 hướng**.

## 3. Kết quả theo trạm

Độ sâu tại điểm: ETOPO ô gần nhất ("—" = ETOPO coi là đất, lưới thô). Che chắn: các hướng có hệ số gió < 0,75.
Dòng: p50 / p95 / max năm 2024, điểm mô hình cách trạm 1,7–7,1 km.

| Trạm | Lớp | Hướng nguy hiểm (Hs ≥ 2 m ở cấp 10) | Cần chú ý (1–2 m) | Đà gió hướng xấu nhất (km) / F_e max | Che chắn (hướng; góc địa hình max) | Độ sâu (m) | Dòng (m/s) | Bậc cấp 8 / 10 / 12 | Hs hướng xấu cấp 8 / 10 / 12 (m) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NB1 cảng cá Cát Bà | hở | SW | — | SW 65,7 / 53 | ENE; 6,9° | 1 | 0,14 / 0,39 / 0,67 | 2 / 3 / 4 | 1,8 / 2,9 / 4,0 |
| NB15 Trà Báu | bán kín | — | E | E 3,9 / 2,0 | SSW→NNW; 23° | — | 0,06 / 0,17 / 0,89 | 2 / 3 / 4 | 0,7 / 1,1 / 1,5 |
| NB16 Bãi Giai – Phù Long | hở | — | NNW, W | NNW 8,0 / 4,6 | không; 3,0° | 6 | 0,06 / 0,11 / 0,47 | 2 / 3 / 4 | 1,0 / 1,6 / 2,2 |
| NB17 Trân Châu | kín | — | — | S 0,8 / 0,6 | 13/16 hướng; 37° | — | 0,14 / 0,39 / 0,67 | 1 / 2 / 3 | 0,3 / 0,5 / 0,7 |
| NB19 cảng Lạch Huyện | hở | SE | ESE, NNW | SE ≥ 200* / 60 | không; 2,9° | 14 | 0,08 / 0,19 / 0,58 | 2 / 4 / 4 | 1,9 / 3,1 / 4,4 |
| NB2 Bến Bèo | kín | — | — | NE 1,7 / 15 | SSW, SW; 7,8° | 39 (ETOPO nghi ngờ) | 0,17 / 0,47 / 0,75 | 2 / 3 / 4 | 0,5 / 0,7 / 1,0 |
| NB25 Cát Cò | hở | ESE, SSE, S | — | ESE ≥ 200* / 126 | 11/16 hướng; 23° | — | 0,14 / 0,39 / 0,67 | 2 / 4 / 4 | 1,9 / 3,1 / 4,6 |
| NB26 Tùng Thu | kín | — | — | SSW 0,9 / 43 | 13/16 hướng; 26° | — | 0,14 / 0,39 / 0,67 | 2 / 3 / 4 | 0,3 / 0,4 / 0,6 |
| NB27 Đông Nam Cát Bà | hở | ESE, SSE, S, E, SE | NNE, NE, ENE | ESE ≥ 200* / 141 | không; 5,1° | 17 | 0,14 / 0,39 / 0,67 | 2 / 4 / 4 | 2,0 / 3,3 / 4,8 |
| NB28 Đầu Bê – Hang Trai | hở | ESE, SE, SSE, ENE, E | N, NNE, NNW, NE | ESE ≥ 200* / 146 | không; 3,7° | — | 0,17 / 0,47 / 0,75 | 2 / 4 / 4 | 2,0 / 3,3 / 4,9 |
| NB3 Thoi Quýt – Gia Luận | bán kín | — | — | WSW 2,1 / 1,3 | 8/16 hướng; 26° | — | 0,06 / 0,17 / 0,89 | 1 / 2 / 3 | 0,5 / 0,8 / 1,1 |
| NB4 luồng Lạch Huyện phao 0 | hở | ESE→WSW (8 hướng) | 8 hướng còn lại | ESE ≥ 200* / 176 | không; 1,6° | 11 | 0,11 / 0,33 / 0,89 | 2 / 4 / 4 | 2,0 / 3,2 / 4,7 |
| NB5 luồng Lạch Huyện phao 9 | hở | SE, SSE, S, SSW, SW | 6 hướng W–NNW, ESE | SE ≥ 200* / 169 | không; 2,8° | 4 | 0,11 / 0,33 / 0,89 | 2 / 4 / 4 | 1,9 / 3,1 / 4,4 |
| NB6 luồng Hải Phòng phao 21 | hở | SE | N, NW, NNW | SE ≥ 200* / 59 | không; 3,0° | 12 | 0,08 / 0,19 / 0,58 | 2 / 4 / 4 | 1,9 / 3,1 / 4,4 |

\* đà gió tới biên mặt nạ nước (vịnh Bắc Bộ mở); sóng khi đó bị giới hạn bởi thời gian gió 3 h, không bởi đà gió.

Đọc nhanh:
- **Kín:** NB17 (Trân Châu), NB26 (Tùng Thu), NB2 (Bến Bèo, Lan Hạ). **Bán kín:** NB15, NB3 (bắc đảo, vịnh Hạ Long).
  **Hở về phía nam – đông nam (vịnh Bắc Bộ):** NB1, NB25, NB27, NB28 và các phao luồng NB4, NB5, NB6, NB19.
- Bão vào vùng này thường quay hướng gió từ bắc – tây bắc sang nam – tây nam khi tâm đi qua (ERA5 Yagi tại NB1:
  319° lúc 03 UTC → 200° lúc 11 UTC ngày 7/9). Vì vậy với nhóm hở, **pha gió nam sau khi tâm bão đi qua** nguy hiểm hơn pha gió bắc.
- Dòng p95 năm 2024 ≤ 0,47 m/s ở mọi trạm (lớp a–b); không trạm nào bị cộng bậc do dòng. Cực đại 0,47–0,89 m/s.
- Toàn lưới: 366/463 điểm lưới hở, 88 bán kín, 9 kín; 33 polygon nuôi OSM: 12 kín, 17 bán kín, 4 hở
  (các khu nuôi thực tế nằm ở chỗ kín hơn hẳn lưới đều, đúng như kỳ vọng).

Bảng mọi hướng × cấp gió: `direction_scenarios.csv`. Hồ sơ từng hướng (đà gió, F_e, độ sâu, vật cản, góc): `per_direction.csv`.
Lớp bản đồ (chưa nối UI): `site_exposure.geojson` (JSON chuẩn). `stations.json` của run này còn token `NaN` (pandas đọc được, không phải JSON chuẩn); mã đã sửa cho các run sau.

## 4. Hồi cứu Yagi 2024

Ba nguồn gió cho mỗi điểm (giờ/30 phút, 05–09/9/2024): (a) ERA5 thật tại ô của điểm (`openmeteo_era5_sites_wind_*`,
0,25°); (b) ERA5 tại NB1 áp cho mọi điểm (đồng nhất); (c) best track IBTrACS: Rankine thuần (cường độ 10 phút, RMW)
và bản "sàn bán kính gió" của `storm_advisory`. Hướng gió cho (c): xoáy ngược chiều kim đồng hồ + góc thổi vào 20°
(giả định, bỏ qua chuyển động của bão).

| Điểm | Gió tại chỗ max ERA5 ô / Rankine (m/s) | Hs max ERA5 ô / Rankine (m) | Bậc max ERA5 ô / Rankine | Thiệt hại ghi nhận |
| --- | --- | --- | --- | --- |
| NB1, NB25, NB27 (nam Cát Bà) | 17,8–18,3 / 36–44 | 1,4–1,9 / 4,1–4,6 | 2 / 4 | lồng Cát Bà "bị sóng lớn đánh sập" (vneconomy) |
| NB4, NB5 (phao Lạch Huyện) | 13,9–18,9 / 46 | 1,2–2,1 / 5,0–5,2 | 2–3 / 4 | — |
| NB17, NB26, NB2, NB3, NB15 (kín, bán kín) | 10,5–15,7 / 31–42 | 0,2–0,3 / 0,3–1,0 | 0–1 / 3–4 | — |
| VAST_A1 Hạ Long, bắc Cát Bà | 13,9 / 45 | 0,6 / 1,7 | 1 / 4 | toàn bộ bị phá hủy (SAR) |
| VAST_A2 nam Cẩm Phả | 17,1 / 44 | 0,5 / 1,8 | 1 / 4 | ~80 % lồng (SAR) |
| VAST_A3 Bái Tử Long | 22,8 / 44 | 1,0 / 2,6 | 2 / 4 | toàn bộ (SAR) |
| VAST_A4 tây Trà Bản | 18,3 / 44 | 0,6 / 1,5 | 2 / 4 | toàn bộ (SAR) |

Tọa độ VAST_A1–A4 là **vị trí ước lượng** từ mô tả vùng SAR của VAST, không phải điểm khảo sát.

Nhận xét:
- Best track cho gió cấp 11–14 ở mọi điểm (mắt bão đi qua cả vùng); ERA5 0,25° chỉ cho cấp 7–9 (gió ngoài khơi tại ô) (đọc thấp lõi bão,
  như RL-29). Ô ERA5 21,0N 107,0E (bắc Cát Bà, Hạ Long) yếu hơn ô 20,75N (13,9 so với 18,9 m/s) vì ô đó nhiều đất.
- Mô hình xếp các điểm **nam Cát Bà** sóng cao nhất (đà gió mở ra vịnh Bắc Bộ), còn vùng Quảng Ninh bị phá hủy hoàn
  toàn lại chỉ có Hs 1,5–2,6 m (đà gió ngắn giữa các đảo). Thiệt hại thực tế bão hòa: cả Cát Bà lẫn bốn vùng SAR
  Quảng Ninh đều mất gần hết lồng. Vì vậy Yagi **không kiểm định được** việc xếp hạng phơi nhiễm (n = 1, thiệt hại
  gần như toàn bộ). Phù hợp với giả thuyết rằng ở gió cấp ≥ 12, **gió tác động trực tiếp lên bè** (bậc 4 ở mọi điểm
  theo Rankine) quyết định, còn che chắn sóng chỉ phân biệt được ở bão yếu hơn (cấp 8–10).
- Sóng mô hình MFWAM (Open-Meteo marine, ~8 km) trong Yagi tại điểm gần nhất: 2,6–3,0 m. Hs của chúng tôi với gió
  ERA5 ở các điểm hở 1,4–2,1 m, với gió Rankine 4–5 m: cùng bậc, nhưng đây không phải kiểm định (lưới 8 km nằm ngoài vịnh).

## 5. Hạn chế

- **Chưa kiểm định.** Không có số đo sóng, gió hay dòng tại lồng. Bậc và lớp phơi nhiễm là đề xuất.
- Công thức SPM 1984 (U_A ∝ U^1,23) được khớp cho gió vừa; ở cấp 10–12 là ngoại suy, chỉ đọc theo bậc độ lớn.
  Sóng lừng (swell) từ vịnh Bắc Bộ không được tính: ở điểm hở, Hs thực tế có thể lớn hơn (Lader et al. thấy
  phương pháp đà gió thấp hơn phao đo ở điểm hở: 1,34 so với 2,79 m; 1,15 so với 3,59 m).
- Hệ số che chắn dùng đường cong hàng rào chắn gió 2 chiều cho đảo đá vôi 3 chiều (gió vòng qua hai bên); sàn 0,5
  là giả định. DSM Copernicus gồm cả cây và nhà. Gió giật sau núi có thể mạnh hơn trung bình.
- Mặt nạ OSM coi một số bãi bồi, rừng ngập mặn, sông là nước; đảo < 100 m có thể lọt giữa hai bước tia.
  Tọa độ trạm là điểm quan trắc, không phải vị trí lồng; kết quả nhạy với vị trí cỡ vài trăm mét
  (NB16 cách nước OSM 884 m, NB15 175 m, NB3 161 m, NB25 98 m: đã dời vào nước).
- Độ sâu ETOPO 460 m: nhiều điểm rơi vào ô "đất"; NB2 39 m nằm trong vùng hố nghi ngờ. Độ sâu dọc đà gió dùng
  trung bình ETOPO; không có số 0 hải đồ, không cộng nước dâng do bão (làm sóng nước nông lớn hơn).
- Dòng chảy 8 km không phân giải được dòng xiết ở lạch hẹp. Lê Đức Cường & Nguyễn Văn Thảo (2019) mô phỏng
  Delft3D vịnh Hạ Long: ngoài khơi 50–80 cm/s, đôi khi ~120 cm/s; ở một số cửa lạch hẹp 90–100 cm/s; cửa Lục
  80–90 cm/s khi triều lên, có thể > 1 m/s khi triều xuống. Dòng dư theo mùa 0,1–0,25 m/s (Vu et al. 2024, COHERENS).
  Vì vậy lớp dòng a–b ở bảng trên **không** loại trừ dòng mạnh tại lồng nằm ở lạch.
- Hướng gió Rankine bỏ qua chuyển động của bão và tính bất đối xứng; ERA5 0,25° gần như đồng nhất cho 14 trạm.

## 6. Dữ liệu tải mới (ghi một lần)

| File | Nguồn | Độ phân giải |
| --- | --- | --- |
| `data/terrain/copernicus-glo30-20261023/N20_00_E106_00.tif`, `N20_00_E107_00.tif`, `N21_00_E106_00.tif`, `N21_00_E107_00.tif` (+ manifest, sha256) | Copernicus DEM GLO-30 (DSM), AWS open data `copernicus-dem-30m` | 1″ (~30 m), EGM2008 |
| `data/hazards/era5/openmeteo_era5_sites_wind_2024-09-04_2024-09-09_20261023.csv` (+ manifest) | Open-Meteo archive `models=era5`: `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`, 18 điểm | 0,25°, giờ |

## 7. Cách chạy

```powershell
.venv\Scripts\python experiments\site_exposure.py download-dem --stamp <yyyymmdd>
.venv\Scripts\python experiments\site_exposure.py download-era5-wind
.venv\Scripts\python experiments\site_exposure.py run --run-name site-exposure-<stamp>   # ~5 phút, thư mục mới
```

## 8. Tài liệu

- U.S. Army Corps of Engineers (1984). *Shore Protection Manual*, 4th ed., vol. 1, ch. 3 (eq. 3-28a, 3-33…3-40; tr. 3-47, 3-51).
- Saville, T. (1954). *The effect of fetch width on wave generation*. BEB Tech. Memo 70; công thức cos² theo
  "Predicting Wave Runup on Dam Slopes", Western Dam Engineering Technical Note (2013), dựa trên USDA TR-69.
- Brandle, J. R., Zhou, X., Hodges, L. (2006). *How windbreaks work*. University of Nebraska–Lincoln Extension EC1763.
- Lader, P. et al. (2017). Classification of aquaculture locations in Norway with respect to wind wave exposure.
  OMAE2017-61659 (slide SINTEF/EXPOSED: bảng NS 9415 A.1, A.2; SPM 3-33a/3-34a; kiểm với phao).
- NACA/FAO Seafarming Development Project RAS/86/024 (1989). *Site selection criteria for marine finfish netcage
  culture in Asia*. NACA-SF/WP/89/13, Bảng 1.
- Lê Đức Cường, Nguyễn Văn Thảo (2019). Mô phỏng lan truyền trầm tích lơ lửng và muội than … vịnh Hạ Long.
  Tạp chí Khoa học và Công nghệ Biển 19(2): 233–241. doi:10.15625/1859-3097/19/2/9729.
- Vu, V. D. et al. (2024). Seasonal variation of coastal currents and residual currents in the Cat Ba – Ha Long
  coastal area. Regional Studies in Marine Science 80:103874. doi:10.1016/j.rsma.2024.103874.
- Open-Meteo Marine Weather API docs (truy cập 23/10/2026): dòng chảy SMOC 0,08°, gồm thủy triều; cảnh báo độ chính xác ven bờ.
- VAST (2024). Dùng ảnh SAR đánh giá nhanh thiệt hại nuôi trồng do bão Yagi tại Quảng Ninh và Hải Phòng; vneconomy.vn
  "Toàn ngành thủy sản điêu đứng vì bão Yagi" (lồng Cát Bà, Đồ Sơn, Vân Đồn bị sóng đánh sập; 4.246 lồng bè toàn quốc).
