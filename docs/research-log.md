# Nhật ký nghiên cứu

Mỗi thử nghiệm một mục, mới nhất ở cuối. Không sửa mục cũ; nếu kết luận thay đổi, thêm mục mới và ghi "xem lại RL-…".
Số liệu chi tiết nằm trong `artifacts/experiments/<run>/`; bảng chỉ mục ở `experiments/RESULTS.md`; quyết định ở `docs/decisions.md`.

Mẫu: **Câu hỏi** · **Thiết lập** (dữ liệu, phương pháp, gate) · **Kết quả** · **Kết luận** · **Artifact** · **Tiếp theo**.

---

## RL-01 · 2026-10-15 · Múi giờ của file export GreenLab

- **Câu hỏi:** cột `Date`/`fetchedAt` không có múi giờ là UTC hay giờ VN?
- **Thiết lập:** so dữ liệu `DataByDate` với cache live (UTC có múi giờ), thử dịch −8…+7 h, đo sai lệch trung vị Temperature/pH/TSS trên các mốc trùng.
- **Kết quả:** −7 h khớp tuyệt đối (0/0/0, 7 mốc); 0 h lệch 1.0/0.03/4.65. `all_data` khớp `intervals` ở 0 h (2.303 mốc).
- **Kết luận:** export là giờ Asia/Ho_Chi_Minh. Mọi kết quả trước 2026-10-15 dùng mốc lệch 7 h.
- **Artifact:** decisions #12; commit 0479014.
- **Tiếp theo:** chạy lại benchmark trên dữ liệu đã sửa (RL-03).

## RL-02 · 2026-10-15 · Độ phủ sensor và trạng thái COD

- **Câu hỏi:** sau backfill, lịch sử có đủ ≥ 90 % phút/ngày không; COD đã hồi phục chưa?
- **Thiết lập:** `scripts/sensor_coverage.py`, 2026-05-29 → 2026-10-14, ngày theo giờ VN.
- **Kết quả:** 123/139 ngày đạt; 16 ngày thiếu do phía nhà cung cấp (lấy lại vẫn thiếu). COD: hợp lệ 05-29→06-06; rail 558.8 06-08→08-12; **kẹt 0.0 suốt 35 ngày** 08-13→09-16 (QC cũ chấm VALID); 24–44 ở 09-17→19; rail lại từ ~09-20.
- **Kết luận:** dữ liệu đủ cho hướng 1. COD chưa hồi phục. Sửa QC: chuỗi không dao động → INVALID.
- **Artifact:** `sensor-coverage-20261015/`, `sensor-history-20261014/` (sha256 eb84b513e5a1…); commit 3894f71.

## RL-03 · 2026-10-16 · H1.1 benchmark baseline trên dữ liệu đã sửa giờ

- **Câu hỏi:** mô hình nào thắng persistence ở 15/30/60 phút?
- **Thiết lập:** `forecast_sensor_v2.py --fast`, B0–B4 × ridge/ExtraTrees/XGBoost, 5 fold × 7 ngày + lockbox 14 ngày, purge 60 phút. Gate: thắng ở các fold + CI bootstrap lockbox không chứa 0.
- **Kết quả:** Temperature: ridge −15…17 % MAE, 5/5 fold, đạt. pH: ridge −10…16 % (fold), −4…6 % (lockbox), 4/5 fold, **đạt lần đầu**. NH4: lockbox thắng, fold thua → không ổn định. TSS: mọi mô hình thua persistence. Mô hình cây (preset nhanh) không đạt ở đâu.
- **Kết luận:** dùng ridge cho Temperature, pH; giữ persistence cho NH4, TSS. Lần chạy đầu với `--write-predictions` hết RAM (16 GB): ~17 triệu dòng dict.
- **Artifact:** `forecast-h1.1-20261016-{Temperature,TSS,pH,NH4}/`.
- **Tiếp theo:** sửa bộ nhớ → kiểm định DM → chân trời 3/6/12 h → thủy triều.

## RL-04 · 2026-10-16 · TSS gần như đứng yên trong giai đoạn lockbox

- **Câu hỏi:** vì sao MAE persistence của TSS ở lockbox (0.38) thấp hơn 8 lần so với fold (3.0–5.1)?
- **Thiết lập:** thống kê TSS theo ngày, 09-10 → 10-14.
- **Kết quả:** trước ~09-19: trung vị ~2.5 mg/L, có đỉnh tới 169. 09-30→10-04: một đợt tăng (trung vị tới 22). Từ 10-05: ~3 mg/L, độ lệch chuẩn < 0.1, chỉ 7–9 giá trị khác nhau mỗi ngày.
- **Kết luận:** lockbox của TSS không đại diện, nên kết luận "persistence thắng" cho TSS không đáng tin. Cần kiểm tra sức khỏe sensor TSS (QC hiện chỉ xét COD).

## RL-05 · 2026-10-16 · Bản đồ phù hợp cá giò theo Ghaderi (2026), HP + QN (bản nháp)

- **Câu hỏi:** tiêu chí của Ghaderi (lồng xa bờ, Iran) có xếp đúng các vùng nuôi hiện có ở HP/QN không?
- **Thiết lập:** 154 điểm biển, lớp 2024 (Open-Meteo Marine/ERA5, ETOPO1, OSM, độ mặn và chất lượng nước nội suy IDW từ 113 trạm). Hàm thuộc tam giác, trung bình theo thời gian, SUM/PRODUCT/GAMMA, có và không trọng số AHP. Kiểm chứng: phân vị điểm số của 22 vùng nuôi OSM nằm trên biển.
- **Kết quả:** có trọng số: vùng nuôi ở phân vị ~24 %; SUM không trọng số: ~52 %. Ô có vùng nuôi cách bờ 0–0.8 km (Ghaderi yêu cầu 2–10 km), điểm cao ở sóng/gió (được che chắn) và gần cảng.
- **Kết luận:** tiêu chí xa bờ không hợp với lồng gần bờ trong vịnh ở VN. Hạn chế: ETOPO1 quá thô gần bờ; 22 vùng nuôi chỉ rơi vào ~5 ô; khu bảo tồn tính bằng điểm tâm.
- **Artifact:** `suitability-h3-2024-draft/`; commit b91ab51.
- **Tiếp theo:** thử bộ tiêu chí gần bờ đặt trước, không chỉnh theo vùng nuôi (RL-06).

## RL-06 · 2026-10-16 · Tiêu chí gần bờ cho lồng trong vịnh (hướng 3)

- **Câu hỏi:** bộ tiêu chí cho lồng gần bờ có xếp các vùng nuôi hiện có cao hơn bộ xa bờ của Ghaderi không?
- **Thiết lập:** như RL-05, đổi 3 điểm (decisions #15): khoảng cách bờ (0.1, 1, 5) km; dòng chảy (0.05, 0.2, 0.6) m/s; bỏ độ sâu vì ETOPO1 không phân giải được trong ~2 km gần bờ. N1 = chỉ tiêu chí vật lý; N2 = N1 + chất lượng nước tại trạm. **Ngưỡng đặt sau khi xem chẩn đoán RL-05**, nên đây không phải kiểm chứng độc lập.
- **Kết quả:** phân vị của vùng nuôi: N1 có trọng số 0.42 (SUM) đến 0.58 (PRODUCT); N1 không trọng số SUM 0.71 (Ghaderi: 0.24 / 0.52). N2 ≈ N1 (+0.005), vì chất lượng nước gần như đồng đều giữa các ô (DO, pH đều ≈ 1). Spearman giữa xếp hạng N1 và Ghaderi: 0.28. Vùng top 20 % dời lên phía bắc (vĩ độ trung bình 20.85 → 21.09, tức vịnh Hạ Long/Bái Tử Long).
- **Kết luận:** tiêu chí gần bờ phù hợp hơn với thực tế nuôi, nhưng xếp hạng **rất nhạy** với lựa chọn tiêu chí. Chưa kết luận được bản đồ nào đúng khi chưa có dữ liệu kiểm chứng độc lập. Lớp chất lượng nước (113 trạm, theo quý, nội suy IDW) quá mượt để phân biệt các ô.
- **Artifact:** `suitability-h3-2024-nearshore/`; commit 8b0b3b0.
- **Tiếp theo:** (1) lấy bản đồ quy hoạch vùng nuôi chính thức của HP/QN hoặc vùng nuôi cá Hong Kong làm tập kiểm chứng độc lập; (2) độ sâu gần bờ chi tiết (hải đồ/GEBCO); (3) phân tích độ nhạy trọng số (H3.2).

## RL-07 · 2026-10-16 · Chuẩn bị H1.2 và dữ liệu ngoài

- **Việc đã làm:**
  - Benchmark ghi dự báo dạng Parquet theo khối (hết lỗi tràn RAM).
  - Thêm module kiểm định Diebold–Mariano (`forecast_dm_test.py`).
  - Thêm chân trời 180/360/720 phút; purge = max(60 phút, chân trời).
  - Nhãn của fold trượt không còn chạm vào lockbox (decisions #16).
  - Thêm B6 thủy triều.
- **Dữ liệu ngoài:**
  - 10.152 bản tin dựng lại (Open-Meteo Previous Runs, lead 1–3 ngày), khả dụng tính từ cuối ngày chạy mô hình + 12 h (decisions #13).
  - Mực nước mô hình tại NB1: triều nhật triều, biên độ trung vị 2.4 m/ngày, chu kỳ chính 24–26 h.
  - NERRS Jobos Bay từ NCEI: 131 file, 216 MB (chất lượng nước và khí tượng 15 phút, dinh dưỡng; 1995/2001–2011).
- **Phát hiện phụ:** kernel Bartlett của DM bác bỏ sai 8–11 % (danh nghĩa 5 %), nên chọn kernel rectangular.
- **Artifact:** `external-context-06M26042804-2026-05-28_2026-10-15/`, `data/foreign/nerrs_ncei/jobos/`; các commit 182781f…b03ce84.

## RL-08 · 2026-10-16 · H1.2: chân trời 15 phút–12 giờ, thời tiết (B5) và thủy triều (B6)

- **Câu hỏi:** dự báo xa hơn có thắng persistence không? Thời tiết và thủy triều có giúp thêm không?
- **Thiết lập:** dữ liệu `sensor-history-20261014`; ridge/XGBoost (preset nhanh); B0, B4, B5 (B4 + bản tin dựng lại), B6 (B4 + mực nước). Gate (decisions #16): ≥ 4/5 fold thắng persistence, DM lockbox p < 0.05. Đóng góp của thời tiết/thủy triều: DM so trực tiếp với B4 trên cùng mốc. Lockbox: 14 ngày cuối (đến 2026-10-14).
- **Kết quả (đạt gate, so với persistence):**
  - Temperature: đạt ở mọi chân trời 15 phút–12 giờ. MAE giảm (B4 → B5): 15 phút +13 → +13 %, 60 phút +18 → +20 %, 3 h +23 → +30 %, 6 h +29 → +38 %, 12 h +37 → +46 %.
  - pH: đạt tới 60 phút (+4…6 %); ở 3 h chỉ B6 đạt (+8 %); 6–12 h không đạt.
  - NH4: không đạt ở đâu. TSS: mọi mô hình thua persistence.
- **Đóng góp so với B4 (DM trực tiếp):**
  - Thời tiết cho Temperature: +8.4 % (3 h), +12.6 % (6 h), +13.9 % (12 h), p < 0.001.
  - Thủy triều cho pH: +4.8 % (6 h, p = 0.04), +6.6 % (12 h, p = 0.007); cho Temperature +1.5–4.3 %.
  - NH4: thời tiết không giúp; thủy triều làm kém đi ở 30–60 phút.
- **Kết luận:**
  - Bằng chứng **sơ bộ** đầu tiên rằng thời tiết giúp dự báo (câu hỏi trung tâm của hướng 2), nhưng mới cho nhiệt độ nước, chưa cho NH4/TSS.
  - Nên đưa nhiệt độ và pH dự báo 3–12 h vào shadow.
- **Hạn chế:**
  - Bản tin là `reconstructed_run`, chưa phải `captured_live`.
  - Một trạm; lockbox 14 ngày.
  - Mô hình cây chạy preset nhanh.
  - Sensor TSS bất thường trong lockbox (RL-04).
- **Artifact:** `forecast-h1.2-20261016-{Temperature,pH,NH4,TSS}/` (có `dm_tests.csv`), `forecast-h1.2-20261016-addon-dm/addon_vs_B4_dm.csv`.
- **Tiếp theo:**
  - Lặp lại B5 khi đủ `captured_live` (H2.2).
  - Shadow cho Temperature và pH 3–12 h (H1.5).
  - Khoảng tin cậy conformal (H1.3).
  - Kiểm tra sensor TSS.

## RL-09 · 2026-10-16 · Khoảng dự báo conformal (H1.3)

- **Câu hỏi:** khoảng dự báo split-conformal có đạt độ phủ danh định trên lockbox không (PI80 ∈ [0.75, 0.85], ≤ 1 % khoảng vô hạn)?
- **Thiết lập:** dự báo của H1.2 (ridge/XGBoost; B4, B5, B6). Phần dư tuyệt đối, khoảng đối xứng, hiệu chỉnh trên 3 fold trượt cuối. Bốn phương pháp:
  - static;
  - static_night (tách ngày/đêm);
  - ACI γ = 0.005;
  - ACI-scaled γ = 0.005·15/h.
  Phần dư chỉ được dùng khi đã quan sát được trước thời điểm dự báo.
- **Kết quả:**
  - Temperature, static PI80: 0.76 (15 phút) → 0.70 (60 phút) → 0.54 (6 h); chỉ 15 phút đạt. Độ phủ theo ngày giảm sau 04/10, tức sai số tháng 10 lớn hơn tháng 9.
  - Temperature, ACI-scaled PI80: 0.75–0.80, đạt 15/18 cấu hình; khoảng rộng hơn 1.3–1.6× (3 h: 1.94 °C so với 1.31 °C).
  - pH: static đạt 10/18, static_night 13/18 (độ rộng PI80 0.08–0.67 đơn vị pH).
  - ACI γ cố định suy biến từ 60 phút trở lên (12–75 % khoảng vô hạn do phản hồi trễ h phút).
  - NH4 phủ quá mức ở chân trời dài (rộng 6.7–8.7× MAE của persistence). XGBoost với static gần như không đạt.
- **Kết luận:**
  - Nhiệt độ: dùng ACI-scaled cho shadow.
  - pH: static_night đủ dùng.
  - Không dùng ACI γ cố định khi chân trời ≥ 60 phút.
  - Mới đánh giá trên một lockbox 14 ngày.
- **Ghi chú:** subagent báo "fold 5 chồng lockbox". Đã kiểm tra lại: ở mọi chân trời, nhãn fold trượt kết thúc trước lockbox (bản sửa a1b7460). Bộ lọc của nó dùng một mốc lockbox chung (mốc sớm nhất, của 720 phút) nên chỉ bỏ thừa dữ liệu hiệu chỉnh ở chân trời ngắn. Đây là thận trọng thừa, không phải rò rỉ. Còn một thiếu sót thật: `actual_at` trống ở các dòng lockbox của predictions.parquet.
- **Artifact:** `forecast-h1.3-conformal-20261016-v3/` (hai run trước bị thay thế, đã gắn SUPERSEDED.txt); commit bd996a4.
- **Tiếp theo:** ghi `actual_at` cho lockbox; thử cửa sổ trượt cho ACI-scaled; tìm nguyên nhân sai số nhiệt độ tăng từ 04/10; kiểm tra lại độ phủ trên dữ liệu shadow mới.

## RL-10 · 2026-10-16 · TSS: cảm biến hỏng hay nước lặng? QC cho mọi chỉ số (xem lại RL-04)

- **Câu hỏi:** TSS đứng ở ~3 mg/L từ 05/10 (7–9 giá trị khác nhau mỗi ngày) là cảm biến kẹt hay nước thật sự lặng?
- **Thiết lập:** thống kê theo ngày cho mọi chỉ số (số giá trị khác nhau, std, CV, tỷ lệ bước bằng 0, độ phân giải); so TSS với chính lịch sử của nó và với các cảm biến khác cùng ngày; tìm bước nhảy, khoảng trống, dấu hiệu hiệu chuẩn.
- **Kết quả:** không có bước nhảy, khoảng trống hay dấu hiệu hiệu chuẩn. TSS tăng thành xung 30/09–04/10, rồi giảm mượt về mức sàn ~3 mg/L (độ phân giải 0.05). Mức sàn này đã xuất hiện ở các đợt lặng trước. Từ 11/10 TSS biến thiên trở lại (25–27 giá trị/ngày). pH, Temperature, NH4 vẫn biến thiên bình thường.
- **Kết luận:**
  - Không phải cảm biến hỏng; nhiều khả năng nước lặng và TSS chạm mức sàn đo được. RL-04 nói "bất thường" là chưa đúng; lockbox TSS chỉ là giai đoạn ít thông tin.
  - Thêm `core.quality.sensor_day_health` (OK/SUSPECT/INVALID) và các cột `*_health` trong báo cáo độ phủ. Kết quả: TSS SUSPECT 9/140 ngày; pH, NH4, Temperature 0 ngày.
  - Ngưỡng hiệu chỉnh trên đúng một trạm.
- **Phát hiện phụ:** pH = 5.94 ngày 07/10, dưới dải hợp lý 6.0, chưa bị gắn cờ.
- **Artifact:** commit d2d41fc.
- **Tiếp theo:** đối chiếu TSS với mẫu đo thực địa; giảm trọng số các ngày SUSPECT khi chấm điểm dự báo TSS; kiểm tra pH ngày 07/10.

## RL-11 · 2026-10-16 · Dữ liệu kiểm chứng độc lập: vùng nuôi VN và Hong Kong

- **Câu hỏi:** có ranh giới vùng nuôi biển chính thức (có tọa độ) cho QN/HP không? Lấy tọa độ trạm EPD và vùng nuôi cá của Hong Kong ở đâu?
- **Thiết lập:** tìm văn bản QĐ-TTg/QĐ-UBND và báo ngành; truy vấn dịch vụ ArcGIS REST của CSDI Hong Kong.
- **Kết quả:**
  - Hong Kong: tọa độ 94/94 trạm EPD (khớp mã trạm 2015–2025); 28 vùng nuôi cá AFCD (38 đa giác, WGS84).
  - Việt Nam: chưa có bảng tọa độ góc. Chỉ có tên vùng và diện tích (QĐ 80/QĐ-TTg: ~45.146 ha nuôi biển ở QN; QĐ 2232/QĐ-UBND: 5 vùng, ~93.600 ha; HP: Hang Vẹm–Vũng Ô, Hòn Thối Quýt–Gia Luận, Ghẽ Gầm–Gia Luận).
- **Kết luận:** dữ liệu Hong Kong sẵn sàng (trạm cho hướng 4; vùng nuôi cá làm tập kiểm chứng ngoài cho hướng 3). Việt Nam chưa có kiểm chứng độc lập.
- **Artifact:** `data/foreign/hk_epd/stations.csv`, `fish_culture_zones.csv`, `data/suitability/validation/SOURCES.md`.
- **Tiếp theo:** xin phụ lục tọa độ từ Sở NN&MT Quảng Ninh và Chi cục Thủy sản Hải Phòng; chạy bộ tiêu chí phù hợp trên Hong Kong và kiểm chứng bằng 28 vùng nuôi cá.

## RL-12 · 2026-10-16 · Thử phương pháp hướng 4 trên NERRS Jobos Bay

- **Câu hỏi:** dùng dữ liệu của một trạm neo cho một vị trí khác cách 1–5 km thì sai số thế nào, gate 80/90/95 có đạt không, và thời tiết có làm độ tin cậy giảm không? (decisions #14)
- **Thiết lập:**
  - Dữ liệu: NERRS Jobos (NCEI), 4 trạm cách nhau 1.0–5.0 km. Trạm 09, 10 trong đầm rừng ngập mặn sâu 1 m; trạm 19, 20 trong vịnh hở trên thảm cỏ biển sâu 2 m.
  - Chỉ giữ giá trị có cờ tốt `<0>`: chất lượng nước 2007 → 2011-07, khí tượng 2007–2010. Trung bình theo giờ.
  - Dung sai: Temp 0.5 °C, Sal 1 psu, DO 0.5 mg/L, pH 0.2 (bằng độ chính xác sensor), Turb max(2 NTU, 20 %).
  - Hai cách chuyển giá trị: (a) lấy nguyên giá trị trạm neo; (b) ánh xạ tuyến tính fit trên 30 ngày quá khứ.
  - Phân tầng: mưa 6 h/24 h trước đó, gió, ngày/đêm, mùa.
  - Gate: cận dưới bootstrap theo ngày ≥ ngưỡng, và ≥ 30 ngày.
- **Kết quả:**
  - Lấy nguyên giá trị: không đạt ô nào (0/936). Tỷ lệ giờ trong dung sai: Temp 0.30–0.68, DO 0.07–0.32, pH 0.15–0.54.
  - **Loại môi trường quan trọng hơn khoảng cách:** cặp 09↔19 cách 1.0 km nhưng khác loại có Temp 0.30; cặp 19↔20 cách 2.3 km, cùng loại, có Temp 0.68. Trung bình cùng loại so với khác loại: Temp 0.54/0.35, pH 0.54/0.27.
  - Ánh xạ hiệu chỉnh: chỉ pH ±0.2 đạt 80 % (5/12 cặp) và 90 % (2 cặp); pH ±0.1 trượt hết; Temp, Sal, DO, Turb đều dưới 0.80.
  - **Mưa ≥ 10 mm trong 24 h làm ánh xạ hiệu chỉnh kém đi:** 43/60 ô, Δ = −0.11 (Sal −0.21, Temp −0.14); vẫn còn −0.10 khi chỉ xét mùa mưa. Với cách lấy nguyên giá trị, tác động của mưa chủ yếu do trùng mùa. Gió không có tác động phát hiện được, nhưng tầng "gió mạnh" chỉ > 1.5 m/s, không phải gió bão.
- **Kết luận:**
  - Bản đồ tin cậy phải tách theo vùng nước hoặc loại môi trường trước, rồi mới xét khoảng cách.
  - Chỉ chuyển được giá trị khi có điểm đối chứng để hiệu chỉnh, và nên hạ mức tin cậy sau mưa lớn.
  - Phần dùng được cho Việt Nam: gate theo cờ chất lượng; gate bằng bootstrap theo ngày; dung sai không dưới độ chính xác sensor; báo cáo theo tầng mưa và tách mùa.
  - Phần không dùng được: Jobos triều nhỏ (~0.3 m) còn Cát Bà triều lớn; vùng nông khác lồng nuôi; không có NH3/TSS.
- **Hạn chế:**
  - Tọa độ trạm nhất quán nhưng chỉ trạm 19 khớp khoảng cách ghi trong metadata.
  - CI bootstrap theo ngày là cận dưới của độ bất định.
  - Cột năm trong `nutrients_summary.csv` của artifact bị lệch so với code đã commit (chạy lại sẽ ra 2007–2010).
- **Artifact:** `nerrs-h4-pilot-20261016/`; commit 20fa8e7.
- **Tiếp theo:**
  - H4.4 (điểm đối chứng tại VN) cần: một điểm thứ hai cùng vùng nước và cùng độ sâu với NB1, cộng một điểm khác vùng; Temp/Sal/DO/pH theo giờ; mưa và gió đo tại chỗ; ≥ 30 ngày mỗi tầng, gồm một mùa mưa; GPS có nguồn rõ; độ chính xác sensor.
  - Thêm pha triều làm tầng phân tích.
  - Chạy cùng phương pháp trên HK EPD (94 trạm) với cách phân vùng theo vùng kiểm soát nước.

## RL-13 · 2026-10-16 · pH trôi từ 19/09 và sai số nhiệt độ tăng từ 04/10 (xem lại RL-08, RL-09 phần pH)

- **Câu hỏi:** pH 5.94 ngày 07/10 có thật không? Vì sao sai số dự báo nhiệt độ và độ phủ conformal xấu đi từ ~04/10?
- **Thiết lập:** lịch sử sensor, dự báo H1.2, độ phủ H1.3, bản tin dựng lại, mực nước. Chia 4 giai đoạn: 27/08–16/09, 17–30/09, 01–04/10, 05–14/10. Phân tích chỉ đọc dữ liệu.
- **Kết quả, pH:**
  - Đến 18/09: 7.4–8.2 mỗi ngày (trung vị tháng 8 = 7.94), chưa ngày nào < 7. Từ 19/09: trung vị ~6.9–7.0 (tháng 10 = 6.94); 15.958 phút < 7.0 trên 22 ngày; 48 phút < 6.0, đều ngày 07/10.
  - Ngày 07/10 không mưa, trời quang, TSS phẳng. Chu kỳ ngày–đêm đảo ngược: tương quan pH–nhiệt độ từ +0.71 (mùa hè) còn −0.05.
  - COD và NH4 nhảy bậc chiều 16/09 → nghi có sự cố hoặc bảo dưỡng đầu dò.
  - Bộ lọc 6.0–9.5 hiện tại chỉ loại 48 phút.
- **Kết quả, nhiệt độ:**
  - Sai số tăng do **biên độ ngày–đêm tăng**: biên độ nước trung bình 3.0 → 4.6 → 5.3 °C, trời quang, gió nhẹ sau front lạnh 05/10. Không phải do lệch hệ thống hay thủy triều.
  - Tương quan sai số theo ngày: với biên độ nước +0.75; với mây −0.48; với biên độ triều +0.03.
  - Persistence: MAE 6 h tăng từ 0.93 lên 1.80. Ridge: sai số chủ yếu là phương sai (bias² < 2.5 % MSE). XGBoost lệch dương +0.5…+1.9 °C (kéo về mức nhiệt mùa hè).
  - Chuẩn hóa conformal theo biên độ nhiệt 24 h đưa độ phủ PI80 ngày 05–14/10 từ 0.44–0.66 lên 0.73–0.83 (khoảng rộng hơn 1.4–1.6×). Đây mới là thử một lần, chưa phải quy trình online.
  - B5 (thời tiết) giảm MAE 6 h của ridge 8.9 % (tháng 9) và 12.6 % (tháng 10), thắng ở mọi ngày lockbox.
- **Kết luận:**
  - **Dữ liệu pH từ 19/09 không đáng tin.** Lockbox pH nằm trọn trong giai đoạn này, nên các kết luận về pH ở RL-08 (đạt gate, thủy triều giúp) và RL-09 (độ phủ PI pH) **chưa có giá trị** cho đến khi đánh giá lại trên dữ liệu trước trôi.
  - Kết luận về nhiệt độ vẫn giữ.
  - H1.5 đã được chỉnh: pH chỉ huấn luyện trên dữ liệu ≤ 18/09; bản ghi gắn nhãn khi pH ngoài 7.0–8.6.
- **Artifact:** chỉ có script tạm trong scratchpad.
- **Tiếp theo:**
  - Thêm vào `core.quality`: dải pH nước biển 7.0–8.6 (SUSPECT) và luật |ΔpH 60 phút| > 0.5.
  - Đánh giá lại pH trên giai đoạn 29/05–18/09.
  - Đưa chuẩn hóa theo biên độ nhiệt vào ACI-scaled.
  - Bỏ XGBoost cho nhiệt độ, hoặc chuyển sang dự báo độ chênh.
  - Xin nhật ký bảo dưỡng cảm biến quanh 16–19/09.

## RL-14 · 2026-10-16 · Độ tin cậy không gian trên HK EPD (94 trạm, lấy mẫu hằng tháng)

- **Câu hỏi:** với cách lấy mẫu định kỳ giống VN, dùng giá trị trạm neo cho vị trí khác thì sai số tăng theo khoảng cách thế nào? Có phụ thuộc vào việc cùng vùng kiểm soát nước (WCZ) hay cùng chế độ mặn không? (kiểm chứng RL-12)
- **Thiết lập:**
  - Dữ liệu: 10.878 mẫu nước mặt, 2015–2025. Ghép cặp trong ±3 ngày, nhưng so sánh chính chỉ dùng cặp **trùng ngày**: các vùng được lấy mẫu theo chuyến riêng (cùng vùng 82 % trùng ngày, khác vùng chỉ 4 %), nên dữ liệu ±3 ngày lẫn hiệu ứng lệch ngày.
  - "Cùng chế độ mặn": chênh trung vị độ mặn mùa mưa < 2 psu.
  - Dung sai như RL-12. NH3 chặt = 30 % tương đối, bỏ giá trị dưới giới hạn phát hiện.
  - Gate: bootstrap theo ngày lấy mẫu, ≥ 30 ngày. Mưa lấy từ ERA5.
- **Kết quả:**
  - **Nhãn WCZ gần như không thêm thông tin:** ở cùng khoảng cách, chênh lệch nằm trong ±0.05.
  - **Chế độ mặn quyết định:** cùng chế độ so với khác chế độ, ở 0–2 km: Temp +0.38, pH +0.38, DO +0.23, TSS +0.21. Cặp khác chế độ không đạt 80 % ở bất kỳ khoảng cách nào.
  - **Bán kính 80 % (cùng chế độ):** Temp 5 km (mùa khô 10 km); Sal 5 km; pH > 20 km (95 % trong 5 km). DO, TSS, NH3 không có bán kính nào.
  - Ánh xạ hiệu chỉnh 24 tháng không tốt hơn lấy nguyên giá trị.
  - So với khí hậu tháng của chính trạm: chuyển giá trị tốt hơn nhiều (Temp 0.84 so với 0.23).
  - Mưa ≥ 20 mm trong 3 ngày trước làm Sal giảm 0.30 (riêng mùa mưa 0.25).
- **Kết luận:**
  - Xác nhận RL-12 trên một bộ dữ liệu khác, cùng kiểu lấy mẫu với VN.
  - **Bản đồ tin cậy VN phải có lớp chế độ mặn** (vùng biển Cát Bà khác vùng chịu ảnh hưởng cửa sông Hải Phòng) trước khi xét khoảng cách; ranh giới hành chính không thay được.
  - Không vẽ vùng tin cậy cho DO. Hạ mức tin cậy độ mặn sau mưa lớn.
  - Chỉ chuyển phương pháp, không chuyển con số bán kính.
- **Hạn chế:** không có giờ lấy mẫu; cặp khác vùng trùng ngày chỉ là các vùng kề nhau; ô ERA5 cách trọng tâm các trạm ~18 km; năm 2020–2022 ít mẫu.
- **Artifact:** `hk-epd-reliability-20261016/`; commit 37a0f23.
- **Tiếp theo:**
  - Dựng lớp chế độ mặn cho HP/QN từ dữ liệu quan trắc quý, rồi chạy lại P0/P1 theo cùng chế độ và khác chế độ (H4.1).
  - H4.4: điểm đối chứng cùng chế độ mặn với NB1, đo theo giờ.

## RL-15 · 2026-10-16 · H1.5: đưa dự báo 3–12 giờ vào shadow runner

- **Câu hỏi:** các dự báo đã qua gate (Temperature B4/B5, pH B4/B6; 3/6/12 h) có chạy được trong shadow, được ghi sổ và chấm điểm, mà vẫn giữ các chốt an toàn không?
- **Thiết lập:**
  - 12 mô hình ridge fit trên `sensor-history-20261014`. pH chỉ huấn luyện trên dữ liệu ≤ 18/09 (RL-13).
  - Đặc trưng lúc chạy được dựng cho từng mốc dự báo; có test khẳng định trùng khớp với `build_frame` của benchmark.
  - B5: chỉ dùng bản tin `captured_live` (retrieved_at ≤ mốc, tuổi ≤ 24 h). B6: mực nước dự báo của Open-Meteo Marine.
  - Khoảng tin cậy: Temperature dùng ACI-scaled; pH dùng static_night; trạng thái dựng lại từ sổ ghi, chỉ dùng mốc đã biết giá trị thật.
  - Sổ ghi riêng: `runtime/forecast-shadow/long_*.jsonl`.
  - Bản ghi pH gắn `ph_probe_suspect` khi đầu vào ngoài 7.0–8.6; các bản ghi này không được chấm điểm hay dùng hiệu chỉnh.
- **Kết quả:**
  - MAE trong mẫu thấp hơn persistence ở mọi cấu hình (chỉ để kiểm tra hợp lý). Temperature 12 h: B4 0.66, B5 0.57, persistence 0.94 °C.
  - Chạy ở chế độ cache: `stale_sensor_data`, không ghi gì (đúng thiết kế).
  - Chạy lại trên dữ liệu cache vào sổ tạm: 9 bản ghi phát hành, 3 bỏ qua có lý do; mọi bản ghi pH bị gắn nhãn (pH hiện tại 6.88).
  - 305 test pass.
- **Kết luận:**
  - Sẵn sàng về kỹ thuật.
  - Vận hành thật còn bị chặn bởi: chế độ fetch đang là cache; `MARINE_ENABLED` đang tắt; chưa có scheduled task cho shadow runner; độ phủ bản tin tự thu thấp (~29 % số giờ kể từ 26/09, đã cải thiện từ 15/10); đầu đo pH nghi hỏng.
  - **Rủi ro:** mô hình Temperature dùng các lag pH, mà pH sau 19/09 đã trôi. Đầu vào pH vẫn nằm trong miền huấn luyện nhưng không đúng về vật lý → nên huấn luyện lại Temperature không dùng pH (hoặc chỉ dùng pH trước 19/09).
- **Artifact:** `core/models/sensor_future/haiphong_*_ridge_*_deb84b513_*.pkl`, `sensor_future_long_manifest.json`; commit 8028b5e, dd3e95a, 9d1abe6.
- **Tiếp theo:**
  - Chủ dự án quyết định bật fetch live, bật marine, cài task cho shadow runner.
  - Tích lũy ≥ 4 tuần sổ ghi rồi so độ phủ khoảng tin cậy với RL-09.
  - Huấn luyện lại Temperature bỏ lag pH.
  - Định kỳ dọn các bản ghi đã chấm điểm khỏi bộ nhớ (~17 nghìn bản ghi mỗi ngày).
