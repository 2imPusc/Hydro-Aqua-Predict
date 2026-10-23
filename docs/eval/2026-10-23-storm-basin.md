# Nhìn bão ở quy mô toàn vùng: báo trước được bao lâu cho NB1 (Cát Bà)?

Ngày: 2026-10-23. Trạng thái: nghiên cứu, shadow. Không điều khiển cảnh báo, không gửi người nuôi.

Câu hỏi của chủ dự án: đường vận hành hiện tại chỉ đọc gió dự báo **tại điểm lồng**, nên "thấy" bão muộn. Bão ảnh hưởng Bắc Bộ thường hình thành ở Tây Thái Bình Dương (biển Philippines) hoặc Biển Đông. Nếu nhìn tâm bão, hướng đi và tốc độ trên toàn vùng thì báo trước được bao lâu, và phải trả giá bao nhiêu báo nhầm?

Mã: `experiments/storm_basin.py` (khí hậu, mô hình, so sánh), `experiments/tigge_tracks.py` (tải quỹ đạo dự báo ECMWF). Test: `tests/test_storm_basin.py`.
Kết quả hiện hành: `artifacts/experiments/storm-basin-20261023b/` (`manifest.json` ghi nguồn và sha256).
**Đã thay thế, để nguyên, không dùng:** `storm-basin-20261023/` (thiếu cột lead của ensemble ECMWF trong bảng so sánh; mọi số khác giống hệt).

## 0. Trả lời ngắn

| Cách nhìn | Báo trước (trung vị) | Báo nhầm | Ghi chú |
| --- | --- | --- | --- |
| Gió dự báo tại điểm (`ecmwf_ifs025`, cấp 6, đã có) | 4–5 ngày cho bão lớn (Yagi 115 h, Wipha 134 h, Bualoi 111 h, Kajiki 100 h); 1–2 ngày cho bão nhỏ/gần | 1 cơn (Ragasa) / 19 cơn 2024–2026 | Giới hạn 7 ngày (168 h) do dữ liệu Previous Runs |
| Thống kê từ vị trí + hướng đi best-track (HGB, P(≤ 200 km trong 120 h) ≥ 0,3) | **57 h** (IQR 38–87), 114 cơn 1980–2026 | Mỗi mùa ~1,8 cơn không vào 500 km + ~2,4 cơn chỉ vào 200–500 km; 64 % số cơn bị "báo" không vào 200 km | Không sớm hơn gió điểm ECMWF cho bão lớn |
| Ensemble quỹ đạo ECMWF (TIGGE, % thành viên vào ≤ 200 km trong 120 h ≥ 0,3) | **93 h** (IQR 50–110), 7 cơn 2024–2026 | 2 cơn không vào 500 km + 3 cơn 200–500 km / 60 cơn có quỹ đạo | Mẫu nhỏ; BSS 0,78, AUC 0,99 |

- **Thống kê thuần từ trạng thái bão (CLIPER/analog/hồi quy/boosting) chỉ báo trước khoảng 2–2,5 ngày** ở ngưỡng 0,3. Nó có kỹ năng thật (BSS 0,26, AUC 0,90 ở 200 km/120 h) nhưng không thắng mô hình số trị.
- **Thứ thực sự cho báo sớm là quỹ đạo dự báo của mô hình số trị (ensemble ECMWF):** khoảng 4 ngày trước khi bão vào gần, ít báo nhầm hơn hẳn thống kê.
- **So với gió điểm ECMWF đang có:** với bão lớn đi từ xa (Yagi, Wipha, Kajiki, Bualoi), ENS báo 85–126 h, **ngang** gió điểm (100–134 h), không sớm hơn rõ. Giá trị thêm của tâm bão là **không bỏ sót**: Prapiroon (gió điểm bỏ lỡ, ENS 69–93 h), Matmo (gió điểm liền mạch 30 h, ENS 102 h), Trami.
- **Giới hạn vật lý:** bão sinh trên Biển Đông (43 % số cơn vào ≤ 200 km) chỉ mất trung vị **72 h** từ lúc hình thành tới 200 km. Không cách nhìn nào báo trước hơn tuổi của cơn bão.
- Đề xuất: **hai tầng**. Tầng "theo dõi" = xác suất từ ensemble quỹ đạo (ECMWF Open Data, có thời gian thực). Tầng "cảnh báo" = gió điểm hiện có. Thống kê vùng chỉ là dự phòng, giải thích được, khi không có ensemble.

## 1. Dữ liệu và định nghĩa

- **Best track:** IBTrACS v04r01 WP (`data/hazards/ibtracs/ibtracs.WP.list.v04r01.20261022.csv`, có tới 2026-10-20). Mùa 1980–2026 (47 mùa). Bỏ các đường "spur". **Tập "mọi hệ thống"** = 1511 hệ thống (mọi cường độ, gồm ATNĐ và nhiễu động một số cơ quan ghi). **TS+** = gió cực đại đời ≥ 34 kt theo bất kỳ cơ quan nào: 1294.
- Mỗi đường đi được nội suy đều 3 giờ. "Vào ≤ R" = có điểm nội suy cách NB1 (20.71894 N, 107.04264 E) ≤ R km, **bất kể cường độ** lúc đó hay đã lên bờ.
- **Hình thành** = điểm đầu tiên của track. Vùng hình thành: Biển Đông (< 120°E), biển Philippines (120–135°E), xa (≥ 135°E).
- **Qua Philippines** = có điểm gốc trên đất liền (`DIST2LAND` = 0) trong hai hộp: 5,5–19 N × 119,5–126,7 E và Palawan 8,3–11,5 N × 117,1–119,5 E.
- **Cổng kinh tuyến** = lần đầu đi **về phía tây** qua kinh tuyến (đã ở phía đông trước đó). Cơn sinh ở phía tây cổng không tính cho cổng đó.
- **Vectơ di chuyển** = sai phân **lùi** 12 h (6 h nếu cơn còn trẻ). Làm được trong thời gian thực. Không dùng `STORM_SPEED`/`STORM_DIR` của IBTrACS.
- Cường độ: TOKYO, HKO, USA × 0,93, CMA (cùng thứ tự `core/storm_advisory.py`).

## 2. Khí hậu (1980–2026)

### 2.1. Bao nhiêu cơn, sinh ở đâu, đi đường nào

| Tập | R | Số cơn | Cơn/năm | Sinh Biển Đông | Sinh biển Philippines | Sinh xa (≥ 135°E) | Qua đất Philippines |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mọi hệ thống | 200 km | 117 | 2,5 | 43 % | 24 % | 33 % | 42 % |
| Mọi hệ thống | 500 km | 265 | 5,6 | 38 % | 27 % | 35 % | 43 % |
| TS+ | 200 km | 102 | 2,2 | 37 % | 25 % | 38 % | 45 % |
| TS+ | 500 km | 231 | 4,9 | 31 % | 29 % | 40 % | 48 % |

Hành lang (vĩ độ khi qua 120°E), cơn vào ≤ 200 km, mọi hệ thống:

| Hành lang | Tỉ lệ |
| --- | --- |
| Sinh trên Biển Đông (không qua 120°E) | 43 % |
| 120°E, 16,5–19 N (bắc Luzon) | 21 % |
| 120°E, 12–16,5 N (trung/nam Luzon) | 20 % |
| 120°E, 19–22,5 N (eo Luzon) | 12 % |
| 120°E, ≥ 22,5 N (Đài Loan/phía bắc) | 3 % |
| 120°E, < 12 N (Visayas/Mindanao) | 2 % |

Ô hình thành 5° có xác suất cao nhất tới ≤ 200 km (`genesis_bins_5deg.csv`): 15–20 N × 110–115 E (16/43 hệ thống = 37 %), 15–20 N × 115–120 E (16/57 = 28 %). Các ô ở biển Philippines 10–15 N × 130–140 E chỉ 14–15 %. Bản đồ: cột `lat_lo`, `lon_lo` ghép thẳng vào lưới.

### 2.2. Thời gian di chuyển tới NB1

Từ cổng (lần đầu qua) tới lúc vào ≤ 200 km / ≤ 500 km, giờ. Chỉ các cơn có qua cổng và có vào bán kính đó.

| Cổng | n (200) | Trung vị → 200 km | IQR | n (500) | Trung vị → 500 km | IQR |
| --- | --- | --- | --- | --- | --- | --- |
| 130°E | 51 | 123 | 108–141 | 121 | 111 | 93–129 |
| 125°E | 58 | 95 | 78–117 | 147 | 81 | 69–98 |
| 120°E | 67 | 72 | 56–93 | 163 | 57 | 42–72 |
| 115°E | 86 | 45 | 33–60 | 206 | 27 | 19–39 |
| 112°E | 101 | 24 | 18–36 | 237 | 6 | 3–15 |
| Cách NB1 1000 km | 117 | 51 | 39–72 | 265 | 33 | 24–45 |
| Cách NB1 800 km | 117 | 39 | 30–57 | 265 | 18 | 15–27 |
| Cách NB1 600 km | 117 | 24 | 18–36 | – | – | – |

Từ lúc hình thành tới ≤ 200 km (`genesis_to_arrival.csv`): Biển Đông **72 h** (IQR 51–121; 52 % ≤ 72 h), biển Philippines 138 h (117–168), xa 198 h (176–249).

Theo tháng (120°E → 200 km, trung vị): tháng 6 87 h (n 7), 7 69 h (22), 8 80 h (12), 9 68 h (12), 10 89 h (10), 11 87 h (4). Không phân tầng ENSO. Mẫu mỗi tháng nhỏ; khác biệt không rõ.

### 2.3. Tỉ lệ cơ sở: qua cổng rồi thì bao nhiêu cơn tới NB1?

| Cổng | Dải vĩ độ khi qua | Số cơn qua | Tới ≤ 500 km | Tới ≤ 200 km |
| --- | --- | --- | --- | --- |
| 125°E | tất cả | 570 | 26 % | 10 % |
| 125°E | 10–15 N | 184 | 32 % | 15 % |
| 125°E | 15–20 N | 195 | 37 % | 13 % |
| 125°E | 20–25 N | 89 | 12 % | 4 % |
| 120°E | tất cả | 455 | 36 % | 15 % |
| 120°E | 15–20 N | 162 | 57 % | 22 % |
| 115°E | 15–20 N | 157 | 78 % | 36 % |
| 112°E | 15–20 N | 159 | 85 % | 42 % |
| 112°E | 20–25 N | 88 | 93 % | 35 % |

Ý nghĩa: qua 125°E thì chỉ 1/10 cơn tới 200 km. Phải tới 115°E (cách khoảng 2 ngày) mới lên 1/3. Đó là lý do thống kê thuần không báo sớm được với độ tin cậy cao. Bảng theo ô 2,5°: `position_bin_rates.csv`.

## 3. Mô hình xác suất tiếp cận (thống kê, giải thích được)

### 3.1. Thiết kế

- Trạng thái mỗi 6 h (00/06/12/18 UTC) khi bão cách NB1 ≤ 3000 km và **chưa từng vào** R. Nhãn: vào R trong (t, t + H], H = 24/48/72/96/120 h. Track kết thúc trước t + H tính là 0.
- Mô hình: (a) khí hậu (tỉ lệ cơ sở của fold huấn luyện) — làm chuẩn; (a') khí hậu có điều kiện theo ô 2,5° × mùa (co về tỉ lệ ô, rồi về tỉ lệ cơ sở, k = 10); persistence kiểu CLIPER (ngoại suy thẳng hướng đi hiện tại, 0/1); (b) hồi quy logistic (vị trí, khoảng cách, phương vị, u, v, tốc độ tiếp cận, cường độ, biến đổi cường độ 24 h, tháng; thêm các số hạng bậc hai); (b') gradient boosting (HGB); (c) k-NN tương tự (vị trí, u, v, tháng; k = 50).
- Kiểm định chéo **bỏ một mùa** (47 fold, không rò rỉ trong một cơn). Brier skill (BSS) so với tỉ lệ cơ sở của fold huấn luyện.
- R = 200 km: 25 076 trạng thái, tỉ lệ dương 1,8 % (24 h) đến 7,6 % (120 h). R = 500 km: 23 514 trạng thái, 4,3–16,9 %.

### 3.2. Kỹ năng (LOYO, best track)

| R | H | Khí hậu theo ô | Persistence | Logistic | HGB | k-NN | AUC (HGB) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 200 | 24 | 0,34 | 0,30 | 0,48 | 0,44 | **0,50** | 0,99 |
| 200 | 72 | 0,26 | −0,17 | 0,33 | 0,33 | **0,35** | 0,95 |
| 200 | 120 | 0,21 | −0,35 | 0,26 | 0,26 | **0,28** | 0,90 |
| 500 | 24 | 0,44 | 0,43 | 0,61 | 0,60 | **0,62** | 0,99 |
| 500 | 72 | 0,37 | 0,08 | **0,49** | 0,49 | 0,49 | 0,95 |
| 500 | 120 | 0,32 | −0,12 | **0,41** | 0,39 | 0,40 | 0,91 |

(Ô là BSS so với khí hậu; AUC của logistic và k-NN gần như bằng HGB.)

- Ba mô hình học máy gần như ngang nhau. Hơn khí hậu theo ô khoảng 0,05–0,25 BSS. Không có mô hình nào nổi trội; chọn cái đơn giản (logistic hoặc k-NN) nếu cần giải thích.
- Persistence (ngoại suy thẳng) **tệ hơn khí hậu** ở 72–120 h: bão đổi hướng, đổi tốc độ.
- **Nhiễu vị trí thời gian thực** (thêm sai số Gauss 30 km mỗi trục ≈ 37 km bán kính trung bình, tính lại hướng đi): BSS giảm 0,02–0,05 (HGB 200 km/120 h: 0,26 → 0,24). Nhỏ.
- **Độ tin cậy** (HGB, 200 km/120 h, `reliability.csv`): gần đường chéo. Hơi báo cao ở 0,4–0,6 (p 0,45 → tần suất 0,33; p 0,55 → 0,46), hơi báo thấp ở mức rất thấp (p 0,008 → 0,016).

### 3.3. Báo trước theo cơn (114 cơn vào ≤ 200 km có ít nhất một trạng thái hợp lệ)

Xác suất dùng: HGB P(vào ≤ 200 km trong 120 h). Lead = lúc vào 200 km − lúc P vượt ngưỡng. "Liền mạch" = từ lúc đó P không rơi xuống dưới ngưỡng tới khi vào.

| Ngưỡng | POD | Lead lần đầu: trung vị (IQR), h | Lead liền mạch, h | Số cơn bị "báo" | Không vào 500 km | Vào 200–500 km | Báo nhầm / mùa (không vào 500) | Tỉ lệ cơn báo nhầm |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0,2 | 0,98 | 75 (47–103) | 50 | 369 | 125 | 132 | 2,7 | 0,70 |
| **0,3** | 0,97 | **57 (38–87)** | 38 | 309 | 85 | 113 | **1,8** | 0,64 |
| 0,5 | 0,90 | 33 (18–66) | 21 | 195 | 20 | 72 | 0,4 | 0,47 |

Với vị trí có nhiễu 30 km: ngưỡng 0,3 vẫn 57 h, báo nhầm 83 cơn (1,8/mùa). Không đổi đáng kể.

Theo vùng hình thành (ngưỡng 0,3): biển Philippines 66 h, Biển Đông 51 h, xa 57 h.

**Biến thể "theo dõi rộng":** P(vào ≤ 500 km trong 120 h) ≥ 0,3, chấm với sự kiện vào ≤ 200 km: lead 96 h (IQR 69–126) nhưng báo nhầm 253 cơn không vào 500 km (**5,4/mùa**) và 140 cơn 200–500 km; tỉ lệ cơn báo nhầm 0,78. Sớm hơn nhưng rất ồn.

So sánh mốc: cứ ~2,5 cơn/năm vào 200 km. Ở ngưỡng 0,3, mỗi mùa có khoảng 6,6 cơn bị "báo": 2,4 cơn đúng, 2,4 cơn đi ngang 200–500 km (vẫn có thể gây gió cấp 6, xem Kajiki, Bualoi), 1,8 cơn không tới.

## 4. So sánh với đường gió tại điểm (2024–2026)

Mốc chung: `peak_time` (giờ gió điểm lớn nhất theo best track, từ `storm-leadtime-20261023d`). Gió điểm: lead **liền mạch** cấp 6 của `ecmwf_ifs025` so với ERA5 thật (tính tới giờ ERA5 vượt cấp 6 đầu tiên, gần `peak_time`). Thống kê vùng: HGB, P(≤ 200 km hoặc ≤ 500 km trong 120 h) ≥ 0,3, lần đầu vượt. Ensemble: % thành viên ECMWF vào ≤ 200 / 500 km trong 120 h ≥ 0,3, chỉ các lần chạy trước `peak_time` khi bão còn ngoài bán kính.

Lead tính bằng giờ trước `peak_time`. "–" = không vượt ngưỡng (hoặc gió điểm không chạm cấp 6 theo ERA5). Cột cuối: tuổi cơn (từ điểm đầu best track) lúc `peak_time` = trần của mọi cách báo theo tâm bão.

| Cơn | Cách NB1 (km) | ERA5 cấp | Gió điểm, liền mạch | Thống kê ≤ 200 | Thống kê ≤ 500 | ENS ≤ 200 | ENS ≤ 500 | Tuổi cơn |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MALIKSI 2024 | 453 | 4 | – | 45 | 45 | – | 45 | 45 |
| (không tên) 2024-07 | 328 | 5 | – | 57 | 57 | – | 21 | 57 |
| PRAPIROON 2024 | 56 | 6 | bỏ lỡ | 123 | 165 | 69 | 93 | 177 |
| **YAGI 2024** | 21 | 8 | **115** (cấp 8: 92) | 42 | 162 | **102** | **126** | 186 |
| SOULIK 2024 | 405 | 4 | – | 49 | 97 | – | 73 | 97 |
| TRAMI 2024 | 482 | 6 | bỏ lỡ | 24 | 126 | – | 120 | 204 |
| WUTIP 2025 | 209 | 5 | – | 60 | 66 | 48 | 48 | 66 |
| (không tên) 2025-06 | 276 | 3 | – | 42 | 48 | – | 24 | 48 |
| **WIPHA 2025** | 17 | 7 | **134** | 124 | 130 | **118** | **118** | 136 |
| (không tên) 2025-08 | 41 | 5 | – | 56 | 56 | 20 | – | 56 |
| **KAJIKI 2025** | 260 | 7 | **100** | 91 | 103 | 85 (không liền mạch) | 85 | 103 |
| NONGFA 2025 | 303 | 6 | 21 | 36 | 54 | – | 48 | 54 |
| RAGASA 2025 | 128 | 4 | – (báo nhầm theo ERA5) | – | 84 | 108 | 108 | 186 |
| **BUALOI 2025** | 292 | 7 | **111** | 42 | 84 | 108 (không liền mạch) | 108 | 138 |
| MATMO 2025 | 134 | 6 | 30 (any 119) | 36 | 84 | 102 | 102 | 108 |
| FENGSHEN 2025 | 493 | 5 | – | – | 121 | – | 79 | 163 |
| MAYSAK 2026 | 74 | 6 | 49 | 62 | 62 | 56 | 56 | 62 |
| NARRA 2026 | 74 | 6 | −8 (trễ) | không có trạng thái | không có | không có | không có | 54 |
| SAUDEL 2026 | 356 | 4 | – | 6 | – | – | – | 6 |

Đọc bảng:

- **Bão lớn đi từ xa (Yagi, Wipha, Kajiki, Bualoi):** gió điểm ECMWF đã báo liền mạch 100–134 h. ENS quỹ đạo báo 85–126 h, **ngang** gió điểm, không sớm hơn rõ. Thống kê vùng ở bán kính 200 km chỉ 42 h cho Yagi và Bualoi (bão còn xa, tỉ lệ cơ sở thấp), nhưng ở 500 km thì 84–162 h — sớm, đổi lại báo nhầm nhiều (mục 3.3).
- **Nơi nhìn toàn vùng thêm giá trị thật:** Prapiroon (gió điểm bỏ lỡ; ENS 69–93 h, thống kê 123 h), Matmo (gió điểm liền mạch chỉ 30 h; ENS 102 h), Trami và Fengshen (ENS ≤ 500 km báo 79–120 h; gió điểm không chạm hoặc bỏ lỡ). Tức là: tâm bão giúp **không bỏ sót** cơn có gió điểm yếu trong mô hình 0,25°.
- **Ragasa:** vào 128 km theo best track nhưng ERA5 chỉ cấp 4. ENS báo 108 h là đúng về hình học, "nhầm" về gió. Cần tầng gió điểm để quyết định hành động.
- **Bão sinh trên Biển Đông (Maysak, Wutip, Nongfa, Narra, Saudel):** mọi cách đều chỉ 0–2,5 ngày, vì cơn mới 1–3 ngày tuổi. Narra sinh cách NB1 157 km: không cách nhìn tâm bão nào báo trước được; gió điểm cũng trễ.
- Bảng này chỉ có các cơn đã vào 500 km, nên không thấy báo nhầm. Báo nhầm của ENS và thống kê trên cùng tập 60 cơn: mục 5.2.

**Sơ đồ hai tầng đề xuất (chưa vận hành):**

1. **Theo dõi (watch), 3–5 ngày:** xác suất ensemble ECMWF vào ≤ 500 km trong 120 h ≥ 0,3, hoặc ≤ 200 km ≥ 0,2. Nội dung: "có bão có thể ảnh hưởng, theo dõi bản tin". Không đề xuất hành động tốn kém. Thống kê vùng (logistic/k-NN) dùng làm dự phòng khi thiếu ensemble, ở ngưỡng 0,5 (ít báo nhầm, lead ~1,5 ngày).
2. **Cảnh báo (warning), 1–4 ngày:** gió điểm hiện có (`core/storm_advisory.evaluate_storm_advisory`), các bậc cấp 6/8/10. Theo dõi giúp người nuôi chuẩn bị sớm; cảnh báo quyết định hành động.
3. Theo dõi không bao giờ tự nâng thành cảnh báo. Bản tin của cơ quan khí tượng vẫn là nguồn chính thức.

## 5. Kho quỹ đạo dự báo: có gì, tải được không

Thử ngày 2026-10-23 (HTTP thật, không đăng nhập):

| Nguồn | Có gì | Truy cập | Đã dùng? |
| --- | --- | --- | --- |
| **TIGGE TC tracks (NCAR GDEX d330003)**, CXML | ECMWF, UKMO, NCEP, JMA, CMA, MSC, Météo-France, KMA; 2006-10 → 2026-11; ECMWF: HRES + control + 50 thành viên, 00/12 UTC, tới 360 h | Trang dataset hiện nút "Sign In". Nhưng bản sao OSDF `https://osdf-director.osg-htc.org/ncar/rda/d330003/ecmf/...` liệt kê thư mục và tải file **không cần đăng nhập** (HTTP 200). CC BY 4.0, phi thương mại | **Có**: ECMWF 2024-05-01 → 2024-12-15, 2025-05-01 → 12-15, 2026-05-01 → 10-21; 1 lần chạy/ngày (00 UTC; 12 UTC khi không có file 00 UTC). 531 lần chạy. Chỉ giữ bản trích WP (CSV) + manifest sha256 từng file gốc trong `data/hazards/tigge/` |
| **ECMWF Open Data** (thời gian thực) | `.../ifs/0p25/oper/<run>-360h-oper-tf.bufr` và `.../enfo/<run>-360h-enfo-tf.bufr` (quỹ đạo bão HRES và ensemble, BUFR) | Không cần đăng nhập, CC BY 4.0. Chỉ giữ vài ngày gần nhất (thư mục có 2026-10-21, 10-22) | Chưa. Đây là nguồn **vận hành** cho tầng theo dõi; TIGGE là kho nghiên cứu, không phải luồng thời gian thực |
| **UCAR RAL a-decks mở** (`hurricanes.ral.ucar.edu/repository/data/adecks_open/`) | File ATCF a-deck WP 2003–2026 (vd. `awp112024.dat`) | Mở, HTTP 200 | Chưa. **Chỉ có mô hình không độc quyền:** GFS (AVNX), GEFS (AP01–30, AEMN), CMC/CEMN, NAVGEM, UKM, CARQ. **Không có** dự báo chính thức JTWC, **không có** ECMWF |
| JTWC (`metoc.navy.mil/jtwc`) | Best track, ATCR | HTTP 403 từ máy này | Không. Không tìm được kho a-deck chính thức JTWC công khai |
| NRL ATCF (`nrlmry.navy.mil/atcf_web`) | Trước đây có a/b-deck | Chuyển hướng, HTTP 403 | Không |
| JMA / RSMC Tokyo | Best track RSMC (HTTP 200); báo cáo năm có bảng sai số | Không thấy kho bản tin dự báo lịch sử dạng máy đọc | Chỉ dùng số liệu sai số đã công bố (mục 6) |
| NCHMF (Việt Nam) | Bản tin văn bản/ảnh trên web | Không thấy kho lịch sử máy đọc được | Không |

### 5.1. Sai số quỹ đạo HRES ECMWF (TIGGE, 2024–2026)

So với best track nội suy; bỏ các lần ghép có sai số tại t0 > 150 km. Trung vị (IQR), km.

| Lead | Toàn WP (n điểm / cơn) | Trung vị | Điểm kiểm cách NB1 ≤ 1500 km (n / cơn) | Trung vị | IQR |
| --- | --- | --- | --- | --- | --- |
| 0 h | 514 / 60 | 25 | 159 / 31 | 25 | 11–46 |
| 24 h | 476 / 60 | 46 | 163 / 32 | 40 | 24–71 |
| 48 h | 403 / 55 | 90 | 151 / 28 | 76 | 42–113 |
| 72 h | 324 / 51 | 130 | 128 / 26 | 102 | 57–165 |
| 96 h | 248 / 43 | 210 | 101 / 20 | 147 | 94–253 |
| 120 h | 179 / 38 | 295 | 84 / 18 | 215 | 117–290 |

Cùng độ lớn với sai số chính thức RSMC Tokyo (mục 6). Ở 120 h sai số ~200–300 km, bằng bán kính 200 km: vì vậy dùng **xác suất ensemble**, không dùng một đường HRES.

### 5.2. Ensemble ECMWF và thống kê vùng trên cùng các trạng thái

Cùng các cặp (cơn, 00 UTC) mà ECMWF có quỹ đạo: 285 trạng thái (R 200), 260 (R 500); 60 cơn, 7 cơn vào ≤ 200 km. Thống kê vùng = dự báo ngoài fold (LOYO).

| R | H | BSS ECMWF ENS | BSS HGB | BSS k-NN | AUC ENS | AUC HGB |
| --- | --- | --- | --- | --- | --- | --- |
| 200 | 48 | **0,88** | 0,24 | 0,41 | 1,00 | 0,96 |
| 200 | 72 | **0,87** | 0,33 | 0,34 | 1,00 | 0,96 |
| 200 | 120 | **0,78** | 0,25 | 0,25 | 0,99 | 0,91 |
| 500 | 72 | **0,75** | 0,59 | 0,53 | 0,99 | 0,96 |
| 500 | 120 | **0,70** | 0,58 | 0,50 | 0,98 | 0,96 |

Theo cơn (P(≤ 200 km trong 120 h), 7 cơn vào 200 km):

| Mô hình | Ngưỡng | POD | Lead lần đầu: trung vị (IQR), h | Số cơn bị "báo" | Không vào 500 km | Vào 200–500 km |
| --- | --- | --- | --- | --- | --- | --- |
| ECMWF ENS | 0,2 | 7/7 | 105 (62–116) | 17 | 4 | 6 |
| ECMWF ENS | 0,3 | 7/7 | **93 (50–110)** | 12 | 2 | 3 |
| ECMWF ENS | 0,5 | 7/7 | 93 (50–102) | 10 | 1 | 2 |
| HGB | 0,3 | 6/7 | 38 (13–44) | 16 | 2 | 8 |
| HGB | 0,5 | 4/7 | 27 | 8 | 0 | 4 |

Độ tin cậy ENS (200 km/120 h): p ≥ 0,7 → 22/22 trạng thái đúng; p 0,3–0,5 → 0/10 đúng (báo cao ở giữa). Mẫu quá nhỏ để hiệu chỉnh.

**Lưu ý công bằng:** ENS chỉ có từ khi ECMWF bắt đầu theo dõi hệ thống; một lần chạy/ngày (thống kê vùng có 4 trạng thái/ngày). Bảng 5.2 so trên cùng trạng thái nên điểm số công bằng. Lead của ENS không so trực tiếp được với lead HGB trong mục 3.3 (khác tập cơn, khác tần suất).

## 6. Tài liệu đã đọc

1. RSMC Tokyo – Typhoon Center, *Activities of the RSMC Tokyo – Typhoon Center in 2024*, ESCAP/WMO Typhoon Committee 57th session, WRD/TC.57/7.1 (18/02/2025). Sai số quỹ đạo chính thức 2024 (26 TC từ TS): **71 / 106 / 152 / 245 / 424 km** ở 24/48/72/96/120 h (2023: 61 / 110 / 165 / 249 / 356 km). Vòng xác suất 70 %: tỉ lệ trúng 2024 75 / 81 / 78 / 69 / 62 %. https://www.typhooncommittee.org/57th/docs/item%207/7.1.Review_RSMC_Activities_2024_20250218.pdf
2. RSMC Tokyo – Typhoon Center, *Review of the activities of RSMC Tokyo in 2025*, Typhoon Committee 58th session (dự thảo phụ lục A). 2025 (27 TC): **67 / 105 / 179 / 302 / 508 km** ở 24–120 h. https://www.typhooncommittee.org/58th/docs/item%207/7.1.Review_RSMC_Activities_2025.pdf
3. Pham-Thi T.-H., Nguyen B. T., Nguyen V. H., Mai V. K. (2024). *Distribution characteristics of tropical cyclones affecting the Vietnam region during 1992–2022.* Vietnam Journal of Marine Science and Technology. doi:10.15625/1859-3097/21326. Tóm tắt: khoảng **32 %** XTNĐ ảnh hưởng trực tiếp đất liền Việt Nam; tần suất cao ở vịnh Bắc Bộ (**0,9 cơn/năm**) và ngoài khơi phía bắc (> 1,1 cơn/năm trên ô 1°); đỉnh tháng 9 trên Biển Đông.
4. Huang X., He L., Zhao H., Huang Y. (2017). *Characteristics of tropical cyclones generated in South China Sea and their landfalls over China and Vietnam.* Natural Hazards 88(2). doi:10.1007/s11069-017-2905-4. 1949–2014: **152** lần đổ bộ Trung Quốc và **147** lần đổ bộ Việt Nam của XTNĐ sinh trên Biển Đông (105–120°E, 5–20°N); xu thế giảm tuyến tính; đổ bộ Việt Nam muộn hơn Trung Quốc khoảng một tháng.

So với mục 2: 43 % số cơn vào ≤ 200 km NB1 sinh trên Biển Đông, khớp với nhận định của [4] rằng Biển Đông là nguồn bão đổ bộ Việt Nam đáng kể. 2,5 hệ thống/năm vào ≤ 200 km (mọi cường độ) phù hợp bậc độ lớn 0,9 cơn/năm/ô 1° của [3] cho vịnh Bắc Bộ (hai đại lượng khác nhau, chỉ so bậc).

Nguồn dữ liệu (không phải tài liệu): IBTrACS v04r01 (Knapp et al. 2010, BAMS; NOAA NCEI); TIGGE TC tracks, NCAR GDEX d330003, định dạng CXML (Bureau of Meteorology).

## 7. Hạn chế

1. **Best track là hậu phân tích.** Vị trí thời gian thực sai ~20–50 km; cường độ được sửa sau. Ca nhiễu 30 km/trục chỉ mô phỏng sai số vị trí, không mô phỏng sửa cường độ, không mô phỏng việc hệ thống được "đặt tên" muộn hơn điểm đầu của best track (best track có thể bắt đầu sớm hơn bản tin đầu tiên).
2. "Vào ≤ 200 km" là hình học, không phải gió. Kajiki (260 km) và Bualoi (292 km) cho gió cấp 7 theo ERA5 mà không vào 200 km; Ragasa vào 128 km nhưng ERA5 chỉ cấp 4. Sự kiện hình học và sự kiện gió không trùng nhau.
3. Tập "mọi hệ thống" gồm cả nhiễu động yếu chỉ một cơ quan ghi. Trước khoảng 1987 nguồn cường độ khác (JMA không ghi gió cho ATNĐ). Không phân tầng ENSO, không xét xu thế dài hạn.
4. ENS chỉ có 3 mùa, 7 cơn vào 200 km: không có khoảng tin cậy. Một lần chạy/ngày. Chỉ ECMWF; chưa thử UKMO/NCEP/JMA trong TIGGE.
5. TIGGE ghép cơn bằng vị trí t0 (≤ 300 km tới best track cùng giờ). Có thể ghép nhầm khi hai cơn gần nhau; sai số "toàn WP" tính trung bình bị kéo lên bởi các ca này, nên chỉ đọc trung vị.
6. Mốc so sánh khác nhau: gió điểm tính tới giờ ERA5 vượt cấp 6 đầu tiên; thống kê vùng/ENS tính tới `peak_time`. Gió điểm bị chặn ở 168 h vì Previous Runs chỉ có 7 ngày.
7. Không làm `core/storm_basin.py`: chưa có gì được kiểm chứng trong thời gian thực, và mô hình huấn luyện trên best track. Không có hình (matplotlib không có trong venv gốc).
8. Không có bản tin chính thức JTWC/JMA/NCHMF lịch sử dạng máy đọc, nên không chấm được "báo trước chính thức".
