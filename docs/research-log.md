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

## RL-16 · 2026-10-16 · Kiểm chứng ngoài mẫu tại Hong Kong: tiêu chí phù hợp cá giò so với 28 vùng nuôi cá AFCD

- **Câu hỏi:** giữ nguyên ngưỡng (không chỉnh lại), bộ tiêu chí gần bờ (RL-06) có xếp các vùng nuôi cá chính thức của Hong Kong cao hơn bộ Ghaderi không?
- **Thiết lập:**
  - Lưới 1/60° trong vùng biển HK; mặt nạ biển dựng từ đường bờ OSM (515 ô).
  - Sóng, dòng chảy, SST: Open-Meteo Marine, độ phân giải thực ~9 km. Gió: ERA5 0.25°.
  - Độ mặn và chất lượng nước: trung vị các trạm EPD 2020–2024, nội suy IDW.
  - Nhãn dương: ô nằm trong hoặc cách vùng nuôi ≤ 1.8 km (26/28 vùng có ô).
  - Đánh giá: AUC, khoảng tin cậy bootstrap theo vùng; ablation ghép cặp (bỏ độ sâu, đổi từng ngưỡng).
- **Kết quả:**
  - SUM có trọng số: Ghaderi AUC 0.63 [0.53; 0.73]; gần bờ 0.75 [0.63; 0.85]; chênh ghép cặp +0.12 [0.08; 0.15].
  - Riêng việc bỏ lớp độ sâu đã cho +0.06. Không trọng số, phần lợi còn lại sau khi bỏ độ sâu ≈ 0.
  - Ngưỡng dòng chảy gần bờ mang phần lợi còn lại. **Ngưỡng khoảng cách bờ gần bờ không được ủng hộ:** vùng nuôi ở HK chỉ cách bờ trung bình 0.43 km.
  - PRODUCT/GAMMA suy biến (khoảng cách bờ theo Ghaderi = 0 ở mọi ô vùng nuôi).
  - Yếu tố phân biệt rõ nhất: gió, sóng (được che chắn), gần cảng (phần này có tính vòng lặp). Khu bảo tồn kéo điểm các vùng nuôi phía đông bắc xuống. Chất lượng nước đồng đều → N2 ≈ N1.
- **Kết luận:**
  - Tiêu chí xa bờ không hợp với lồng gần bờ: **xác nhận ở hai nơi** (VN, HK).
  - Phần lợi của bộ gần bờ chủ yếu đến từ việc bỏ độ sâu (ETOPO1 quá thô gần bờ) và tiêu chí che chắn. **Chưa kiểm chứng được** ngưỡng khoảng cách bờ của RL-06.
  - Hạn chế lớn nhất là lớp sóng/gió/độ sâu quá thô để nhìn thấy độ che chắn bên trong vịnh. Các vùng nuôi HK được quy hoạch từ thập niên 1980, không phải "tối ưu đã đo".
- **Artifact:** `suitability-hk-2024/` (validation, drivers, ablation); dữ liệu `data/suitability_hk/2024/`; commit e84f8e8.
- **Tiếp theo:**
  - Độ sâu gần bờ chi tiết (GEBCO/hải đồ) cho cả HK và VN.
  - Chỉ số che chắn phân giải < 1 km (fetch theo hướng gió, mô hình sóng ven bờ), thay cho sóng 9 km.
  - Độ nhạy theo bán kính gán nhãn và theo lớp khu bảo tồn.

## RL-17 · 2026-10-17 · Luật QC cho pH (dải nước biển + tốc độ đổi)

- **Câu hỏi:** luật tự động có tách được giai đoạn pH trôi (từ 19/09, RL-13) mà không gắn cờ sai giai đoạn sạch không?
- **Thiết lập:** `core/quality.py`: dải 7.0–8.6 → SUSPECT (không phải INVALID; dải cứng 6.0–9.5 giữ nguyên); |ΔpH| trong 60 phút > 0.5 → SUSPECT; theo ngày: trung vị ngoài dải hoặc > 10 % số đo ngoài dải → SUSPECT. Hằng số trong `core/config.py`; ledger dài hạn và `sensor_future_long` dùng lại cùng luật.
- **Kết quả:**
  - 29/05–18/09: 113/113 ngày OK, 0 số đo ngoài dải, 0 bước nhảy > 0.5/h.
  - 19/09–15/10: 21/27 ngày SUSPECT. Ngưỡng 10 % (thay vì 50 %) tách sạch hai giai đoạn; 50 % chỉ bắt ~11 ngày.
  - Lọt 6 ngày: 24/09 (trung vị 7.98, có vẻ hồi thật) và 25–30/09 (trung vị 7.2–7.4, thấp hơn mọi ngày trước trôi nhưng vẫn trong dải).
  - Chu kỳ ngày–đêm đảo ngược chưa có luật nào bắt.
- **Kết luận:** luật dải + tỷ lệ đủ để tự gắn cờ các đợt trôi mạnh; trôi nhẹ cần luật so với mức nền.
- **Artifact:** commit a9831b1 (317 test).
- **Tiếp theo:** luật so với mức nền trước trôi (trung vị trượt 14 ngày), luật tương quan pH–nhiệt độ theo ngày.

## RL-18 · 2026-10-17 · Nhiệt độ không dùng pH (A1) và đánh giá lại pH trên dữ liệu sạch (A3)

- **Câu hỏi:** (A1) bỏ lag pH (pH hỏng từ 19/09) thì dự báo nhiệt độ còn đạt gate #16 không? (A3) trên giai đoạn sạch 29/05–18/09, dự báo pH có thắng persistence không?
- **Thiết lập:** lịch sử `sensor-history-20261015` (sha256 d2738731…); ridge; B4/B5 và bản `_nopH`; `--end 2026-09-18` cho A3 (lockbox ~04–18/09); kiểm tra bằng assert rằng không nhãn fold nào chạm lockbox (`fold_label_check.json`). Gate #16: ≥ 4/5 fold thắng + DM lockbox p < 0.05.
- **Kết quả A1 (lockbox 01–15/10):**
  - Mọi biến thể nhiệt độ đạt gate ở 60/180/360/720 phút (5/5 fold). Skill B5 vs persistence: 20 / 30 / 38 / 46 %.
  - Bỏ pH làm MAE lockbox tăng 1–4 % (B4 +3.0/+3.8/+3.4/+1.6 %; B5 +3.4/+3.9/+1.9/+0.75 %), có ý nghĩa (DM p ≤ 0.009).
  - Nhưng ở fold 4 (17–24/09, lúc pH bắt đầu trôi) bản nopH **tốt hơn** 11–24 %; fold 5 tốt hơn 1–7 %. Bundle nhiệt độ hiện tại lệch +0.2…+0.4 °C nếu pH nhảy +1 (ví dụ khi hiệu chuẩn lại đầu dò).
  - Tiêu chí đặt trước (đạt gate và MAE trong 3 % ở mọi chân trời 180/360/720) không đạt ở 180 phút → **runtime chưa đổi**.
- **Kết quả A3 (pH, lockbox 04–18/09):**
  - Chỉ B0 (lag pH) đạt ở 60 phút (skill 16 %) và 180 phút (10 %). B1/B2/B6 đạt ở 60 phút.
  - **B4 và B6_tide (đang ở shadow) không đạt ở 180/360/720**; B4 kém persistence 2–18 %. B3 ≡ B4: đặc trưng chéo sensor làm hỏng pH.
- **Kết luận:**
  - pH giúp nhiệt độ một chút khi đầu dò ổn, nhưng là rủi ro lớn khi đầu dò trôi hoặc được hiệu chuẩn lại → nên chạy song song bản nopH trong shadow.
  - Kết luận pH ở RL-08 bị bác bỏ: thủy triều (B6) không giúp pH ở 3–12 h trên dữ liệu sạch. Bundle pH dài hạn trong shadow **không có bằng chứng gate**.
- **Hạn chế:** lockbox nhiệt độ nằm trọn trong giai đoạn pH trôi; lockbox pH chứa bước nhảy COD/NH4 16/09; một trạm; chỉ ridge; thời tiết dựng lại.
- **Artifact:** `forecast-a1-temperature-nopH-20261017/`, `forecast-a3-ph-pre-drift-20261017/`, `sensor-history-20261015/`; commit 395eb8c.
- **Tiếp theo:** gắn nhãn/rút bundle pH dài hạn khỏi shadow (chờ chủ dự án); huấn luyện bundle nhiệt độ nopH chạy song song; thử B0 cho pH 3 h.

## RL-19 · 2026-10-17 · Khoảng tin cậy chuẩn hóa theo biên độ ngày–đêm (A4)

- **Câu hỏi:** chuẩn hóa sai số theo biên độ nhiệt 24 h trước đó (biết tại thời điểm phát hành) có sửa được việc PI hụt độ phủ từ 05/10 (RL-13) không?
- **Thiết lập:** `aci_amp`: điểm = |r| / max(A(t), sàn), A(t) = max−min 24 h của chuỗi đến issued_at, sàn = 0.25 × trung vị (0.775 °C); ACI γ = 0.005·15/h trên điểm chuẩn hóa. So với static, static_amp, aci_scaled, các biến thể std/72 h. Cùng giao thức v3 (calib fold 3–5, lockbox 30/09–14/10). Thêm Winkler score.
- **Kết quả (Temperature, ridge, 18 cấu hình):**
  - Đạt gate độ phủ: aci_amp PI80 18/18, PI90 18/18; aci_scaled 15/18 và 5/18 (PI90 tới 12 % khoảng vô hạn).
  - Sau 05/10: PI80 aci_amp 0.76–0.82 so với aci_scaled 0.69–0.80.
  - Giá: rộng hơn 0–11 % trước 05/10 (tăng theo chân trời); Winkler ngang hoặc hơi kém.
  - Ngày tệ nhất vẫn thấp: PI80 0.35 (aci_scaled 0.25).
- **Kết luận:** aci_amp cho độ phủ đúng danh nghĩa ổn định hơn, đổi lại khoảng hơi rộng. Đã thêm vào `core/forecast_intervals.py` dạng tùy chọn, **mặc định chưa đổi** (cần bundle mang điểm chuẩn hóa và ledger lưu A(t)).
- **Hạn chế:** cửa sổ 24 h chọn sau khi đã xem lockbox này (RL-13) và thử 4 biến thể → gần in-sample; cần shadow xác nhận.
- **Artifact:** `forecast-h1.3-conformal-20261017-amp/`; commit f3c30e7, 7753af0.
- **Tiếp theo:** nối aci_amp vào bundle + ledger; xác nhận bằng shadow ≥ 4 tuần.

## RL-20 · 2026-10-17 · H4.3: NERRS, 8 khu cận nhiệt đới/nhiệt đới (theo giờ)

- **Câu hỏi:** kết quả Jobos (RL-12) và "chế độ mặn > khoảng cách" (RL-14) có lặp lại ở nhiều khu NERRS khác không?
- **Thiết lập:** NCEI 0052765, 2007–2011, cờ `<0>`; 8 khu (job, rkb, apa, gtm, mar, gnd, wkb, sap), mỗi khu 4–5 trạm; 90 cặp có hướng ≤ 30 km. Giao thức chung H4 (dung sai Temp 0.5 °C, Sal 1 psu, DO 0.5 mg/L, pH 0.2, Turb max(2 NTU, 20 %); chuyển thô và hiệu chỉnh 30 ngày; bootstrap theo ngày). Mùa ướt = 6 tháng có độ mặn thấp nhất của từng khu. Mưa từ trạm khí tượng của khu.
- **Kết quả:**
  - Đạt 80 %: Temp/Sal/DO/Turb 0/90 cặp; pH hiệu chỉnh 39/90 (thô 14/90). Bán kính gộp 0 km cho mọi biến.
  - Hồi quy có hiệu ứng cố định theo khu: |Δ độ mặn| làm giảm độ tin cậy Sal/pH/Turb thô (β_z −0.11/−0.11/−0.04, CI không chứa 0); khoảng cách không có ý nghĩa trong mọi mô hình. Hệ số Sal âm ở 8/8 khu.
  - Mưa ≥ 20 mm/3 ngày: pH thô −0.16, Sal hiệu chỉnh −0.13; pH thô kém đi có ý nghĩa ở 8/8 khu.
  - Mã mới tái tạo đúng số liệu Jobos của RL-12.
- **Kết luận:** "chế độ mặn > khoảng cách" lặp lại ở 8 khu. Ở thang giờ gần như không chuyển được giá trị giữa các trạm; bán kính 5 km của HK (mẫu tháng) không áp dụng cho dữ liệu giờ.
- **Hạn chế:** chỉ 2007–2011; tệp met 2011 dán nhãn sai (không có tầng mưa 2011); máy đo mưa rkb đo thiếu; vài trạm cách tháp khí tượng 33–57 km.
- **Artifact:** `nerrs-multi-h4-reliability-20261017/`; dữ liệu `data/foreign/nerrs_ncei/` (~0.8 GB mới); commit 5c08e8a.

## RL-21 · 2026-10-17 · H4.4: Chesapeake, Maryland DNR ConMon (67 trạm, 15 phút)

- **Thiết lập:** 67 trạm, 2004–2009, triển khai theo mùa (4–10); 1.254 cặp ≤ 50 km (610 cặp ≤ 30 km); chồng lấn ≥ 90 ngày (630 cặp ≥ 365 ngày). Không có cột cờ: dùng dữ liệu đã QA của DNR + kiểm tra dải/gai/đường phẳng 12 h. Chế độ: trung vị độ mặn mùa nước lớn (4–6). Mưa ERA5.
- **Kết quả:**
  - Chỉ độ mặn chuyển được: hiệu chỉnh đạt 80 % tới ≥ 30 km ở cả hai chế độ; thô cùng chế độ 5 km (2 km nếu bỏ các cặp nước ngọt cả hai đầu).
  - Temp/DO/pH/Turb không đạt, kể cả ở 0–2 km (trạm nông 1–2 m, nóng ban ngày mạnh).
  - Chế độ mặn > khoảng cách chỉ với Sal và pH thô; Temp và DO theo khoảng cách.
  - Môi trường sống: Iron Pot ↔ Jug Bay (1.7 km, đầm lầy so với lòng kênh) lệch nhiệt ~1.7 °C.
  - Mưa lớn: Sal hiệu chỉnh −0.03/−0.04; DO/pH/Temp thô lại tốt hơn (giả thuyết: mây làm giảm chênh lệch nóng ban ngày; chưa kiểm chứng).
- **Kết luận:** xác nhận vai trò chế độ mặn với độ mặn và vai trò môi trường sống; không có bán kính cho Temp/DO/pH/Turb ở thang giờ; hiệu chỉnh giúp rõ (khác HK).
- **Hạn chế:** ôn đới, triển khai theo mùa; hồi quy coi các cặp độc lập (SE lạc quan). **Giấy phép:** không phát tán lại dữ liệu thô; phải ghi nguồn "Maryland Department of Natural Resources Tidewater Ecosystem Assessment Division".
- **Artifact:** `mddnr-h4-reliability-20261017/`; dữ liệu `data/foreign/chesapeake_mddnr/` (388 MB); commit 93cdcd8, 638be63.

## RL-22 · 2026-10-17 · H4.2: Texas TWDB (17 trạm, theo giờ)

- **Thiết lập:** 17 trạm ở 4 hệ cửa sông (Guadalupe, Trinity-Galveston, Colorado-Lavaca, Sabine), 2008–2019, 1 số đo/giờ (lệch giao thức: không có ≥ 2 số đo/giờ). Bỏ dữ liệu từ 2020 vì API làm tròn độ mặn đến 1 psu (bằng dung sai). QC theo ngưỡng của chính nhà cung cấp. 25 cặp ≤ 30 km, chỉ 3 cặp cùng chế độ.
- **Kết quả:**
  - Không biến nào đạt 80 % ở bất kỳ khoảng cách nào (Temp tốt nhất 0.78; Sal thô ≤ 0.29, hiệu chỉnh ≤ 0.48). Không có cặp DO ≤ 30 km, không có pH/độ đục.
  - Sal: chế độ > khoảng cách (với chuyển thô thì gần như đúng theo định nghĩa). Temp: khoảng cách > chế độ.
  - Mưa: không làm giảm nhất quán; Sal hiệu chỉnh −3…−5 điểm; Temp cùng chế độ +6…+12 điểm.
- **Kết luận:** cùng mẫu hình với Chesapeake: độ mặn theo chế độ, nhiệt độ theo khoảng cách; không có bán kính ở thang giờ.
- **Hạn chế:** vi triều, cận nhiệt đới; dữ liệu tạm thời; ít cặp cùng chế độ.
- **Artifact:** `twdb-h4-reliability-20261017/`; dữ liệu `data/foreign/texas_twdb/` (172 MB); commit a219b84.

## RL-23 · 2026-10-17 · H4.5: USGS vịnh San Francisco (13 trạm) + kiểm tra truy cập Hàn Quốc, IRLON

- **Thiết lập:** 13 trạm, WY2018–2025, chỉ giá trị đã duyệt "A"; độ mặn tính từ độ dẫn (PSS-78, sai 0.02–0.18 psu so với số báo cáo); 156 cặp có hướng, 34 cặp ≤ 30 km. DO/pH đã duyệt chỉ có ở 3 trạm.
- **Kết quả:**
  - Bán kính 80 %: Temp 10 km (cùng chế độ) / 5 km (khác); Sal 0 km khi gộp (chỉ P17↔ALC 3.4 km đạt riêng); Turb không có; pH hiệu chỉnh ≥ 20 km (3 cặp Suisun).
  - Sal: cùng chế độ tốt hơn khác chế độ ở mọi khoảng cách; chế độ > khoảng cách (R² 0.55 so với 0.15). Temp: khoảng cách > chế độ (R² 0.66 so với 0.19).
  - Môi trường sống: kênh đầm lầy FMB làm hỏng cặp ở 9.8 km, trong khi VSI↔GRZ 16 km đạt (pH thô 0.91).
  - Mưa ≥ 20 mm/72 h (mùa ướt): Sal hiệu chỉnh −0.09…−0.11, DO hiệu chỉnh −0.06; Sal/Temp thô lại tốt hơn.
- **Truy cập:** Hàn Quốc (KOEM, data.go.kr) tải không cần đăng nhập nhưng mỗi tệp chỉ 1 năm, 18 trạm theo cụm 1–3, không có tọa độ, không cờ QC → chỉ đủ thử nhỏ. IRLON: cổng chính cần đăng nhập, nhưng **SECOORA ERDDAP có bản sao mở**: 13 trạm, theo giờ từ 2014/15, có tọa độ, cờ QARTOD, cả nitrat/phosphat và mưa tại trạm.
- **Hạn chế:** hiệu chỉnh bất đối xứng (đích ít biến động ≈ "đoán trung bình"); chưa có baseline khí hậu; nhiều cặp lệch độ sâu sensor.
- **Artifact:** `usgs-sfbay-h4-reliability-20261017/`; dữ liệu `data/foreign/usgs_sfbay/` (31 MB), `data/foreign/probe_korea_irlon/NOTES.md`; commit 4217c8c.

## RL-24 · 2026-10-17 · Tổng hợp hướng 4 trên 6 bộ dữ liệu nước ngoài

| Bộ | Kiểu | Bán kính 80 % thô, cùng chế độ | Chế độ mặn > khoảng cách? | Mưa lớn |
| --- | --- | --- | --- | --- |
| Jobos (RL-12) | 4 trạm, giờ | không đạt | môi trường sống quyết định | hiệu chỉnh kém đi |
| HK EPD (RL-14) | 94 trạm, tháng | Temp 5, Sal 5, pH > 20 km | có (mọi biến) | Sal kém đi |
| NERRS 8 khu (RL-20) | 34 trạm, giờ | 0 km mọi biến | có (Sal, pH, Turb) | kém đi ở 8/8 khu |
| Chesapeake (RL-21) | 67 trạm, giờ | Sal 2–5 km, còn lại 0 | Sal, pH; Temp/DO theo khoảng cách | Sal hiệu chỉnh kém đi |
| Texas (RL-22) | 17 trạm, giờ | 0 km | Sal; Temp theo khoảng cách | không nhất quán |
| SF Bay (RL-23) | 13 trạm, giờ | Temp 10 km, Sal 0 | Sal; Temp theo khoảng cách | hiệu chỉnh kém đi |

- **Vững ở mọi bộ:** (1) với độ mặn (và phần lớn pH), chế độ mặn quyết định chứ không phải khoảng cách; (2) khác môi trường sống (rừng ngập mặn/đầm lầy so với vịnh/lòng kênh) làm hỏng cặp ngay ở 1–2 km; (3) DO và độ đục không chuyển được ở đâu; (4) mưa lớn làm chuyển giá trị có hiệu chỉnh kém đi.
- **Phụ thuộc thang thời gian:** bán kính 5 km của HK chỉ đúng với mẫu tháng. Ở thang giờ gần như không chuyển được giá trị (triều và nóng ban ngày làm lệch vượt dung sai). Nhiệt độ theo giờ phụ thuộc khoảng cách nhiều hơn chế độ.
- **Hiệu chỉnh:** có điểm đối chứng 30 ngày thì độ mặn và pH cải thiện mạnh (Chesapeake Sal ≥ 30 km), nhưng một phần là ảo (đích ít biến động) → cần baseline khí hậu.
- **Hàm ý cho VN:**
  - Bản đồ tin cậy không nên hứa giá trị theo giờ tại điểm khác; nên báo ở thang ngày/tháng hoặc theo **lớp ngưỡng** (đạt/không đạt QCVN), là thứ khuyến cáo thực sự dùng.
  - Vùng được phép chuyển = cùng chế độ mặn + cùng loại môi trường sống; ranh giới hành chính không dùng.
  - Không vẽ vùng tin cậy cho DO và TSS; hạ mức tin cậy sau mưa lớn.
  - Muốn chuyển theo giờ cần sensor đối chứng thứ hai để hiệu chỉnh (H4.4 VN).
- **Tiếp theo:** chạy lại giao thức ở thang ngày (trung bình, min/max) và theo lớp ngưỡng trên dữ liệu đã tải, kèm baseline khí hậu; thử IRLON (SECOORA ERDDAP); A6 lớp chế độ mặn HP/QN.

## RL-25 · 2026-10-17 · H4.1 (A6): lớp chế độ mặn HP/QN và P0/P1 tách theo chế độ

- **Câu hỏi:** dựng lớp chế độ mặn cho HP/QN từ quan trắc tỉnh; chạy lại P0/P1 tách cùng/khác chế độ, bỏ HSI rò rỉ.
- **Phát hiện chính:** **độ mặn và nhiệt độ trong bảng HP là số liệu mô hình** (lưới GLORYS 1/12°), không phải đo: 14 chữ số thập phân; 10 cặp trạm có chuỗi giống hệt nhau (NB1=NB2=NB25=NB27, NB16=NB19=NB6, NB17=NB26); khớp ô CMEMS r = 0.964, MAE 0.08 psu. DO, pH, TSS, NH3 của HP là số đo thật. → Kết quả cũ "1/36" (Sal 5–10 km; thực ra 2/36) là **ảo** do trạm chung ô lưới; `assets/spatial_applicability/haiphong_gate_v1.json` dựa trên số liệu này (chờ chủ dự án quyết định rút/gắn nhãn; research-map đã gắn nhãn "Legacy · chưa kiểm chứng").
- **Thiết lập:** HP 14 trạm, 22 đợt (2020-08 → 2024-11); QN 99 trạm (97 dùng được), 16 đợt theo quý (2021–2024). Tọa độ VN-2000 TM-3, kinh tuyến trục HP 105°45', QN 107°45' (khớp EPSG "VN-2000 to WGS 84 (2)"). Mùa ướt 5–10. Lớp: lưới 1 km trên mặt nước, gán lớp trạm đo gần nhất trong 10 km.
- **Kết quả:**
  - QN (đo thật): 4 cửa sông (< 20 psu), 16 chuyển tiếp (20–28), 77 biển (≥ 28). Mùa vụ rất yếu (chênh trung vị −0.2 psu). HP (mô hình): cả 14 trạm "biển" 31.3–32.0 psu — lưới 1/12° không thấy được vệt nước sông.
  - **NB1 (Cát Bà) thuộc chế độ biển**; trạm đo thật gần nhất là QN NB43 Cống Tầu 11.6 km (30.8 psu).
  - Gate chuẩn (≥ 30 đợt): **0/294 ô** — dữ liệu không thể đạt (22 và 16 đợt).
  - Chẩn đoán nới (≥ 10 đợt, không tính là đạt): QN cùng chế độ — pH ≥ 80 % mọi khoảng cách, Sal ≥ 80 % tới 10 km; khác chế độ — Sal chỉ 0.5–3 % trong ±1 psu, pH 0.57–0.69 (cùng chế độ 0.94–0.98). TSS, NH3, HSI không đạt ở đâu.
  - Conformal P1 (≥ 30 cặp, ≤ 10 km): QN cùng chế độ 24/108, khác chế độ 8/72 (bound thường vô dụng).
  - HSI chỉ từ trạm neo: đồng thuận nhãn 0.62–0.69 (QN cùng chế độ), "báo phù hợp sai" 0.1–0.3 % cùng chế độ so với 0.6–7.3 % khác chế độ.
  - So khí hậu tháng của chính trạm: lấy số trạm neo chỉ thắng ở nhiệt độ; thua ở Sal, pH, TSS, NH3 (QN rất ít biến động giữa các năm; khí hậu dùng cả năm sau nên là cận trên).
- **Lỗi dữ liệu:** QN NB74, NB78 lệch ~200 km (nghi gõ nhầm "21"/"23"), đã gắn `coordinate_suspect`, chưa sửa; `data/map/station_coordinates.csv` thiếu dịch datum (lệch đều ~224 m).
- **Kết luận:** xác nhận "chế độ mặn trước, khoảng cách sau" trên dữ liệu VN (QN). Lớp độ mặn HP cần số đo thật. Không vẽ vùng tin cậy cho TSS, NH3, DO. Muốn đạt gate cần thêm đợt đo hoặc sensor thứ hai (H4.4).
- **Artifact:** `vn-salinity-regime-h41-20261017/` (17 tệp, 8.6 MB, chạy lại cho kết quả giống hệt byte); commit 7396dd9 (lẫn 2 file đổi tên frontend, không ảnh hưởng).

## RL-26 · 2026-10-17 · H1.6: rút mô hình pH dài hạn, thêm nhiệt độ không dùng pH chạy song song

- **Quyết định chủ dự án (theo RL-18):** rút 6 bundle pH 3/6/12 h khỏi shadow; thêm bundle nhiệt độ nopH chạy song song; giữ mặc định conformal.
- **Thay đổi:** manifest đánh dấu pH `status: withdrawn` (giữ nguyên tệp); runtime bỏ qua với lý do `bundle_withdrawn`. 6 bundle nhiệt độ nopH (B4/B5 × 180/360/720) huấn luyện trên `sensor-history-20261014` như bundle hiện tại; bản ghi có `model_variant`, `bundle_role`, `ph_input_status`. nopH vẫn phát hành khi pH thiếu/nghi vấn.
- **Kiểm tra:** in-sample nopH trong 2 % so với bản có pH; trên cửa sổ hiệu chỉnh (10–30/09, chồng lên lúc pH trôi) nopH tốt hơn ở 360/720 phút. Chạy thử offline: chế độ cache bị chốt dữ liệu cũ chặn (đúng); bản phát lại có nhãn: 12 dự báo nhiệt độ, 6 pH bị bỏ qua `bundle_withdrawn`.
- **Artifact:** `sensor-future-v2-train-nopH-20261017/`; commit 04a93ae (414 test).
- **Tiếp theo:** so with_pH và nopH trên sổ ghi thật sau ≥ 4 tuần shadow.

## RL-27 · 2026-10-17 · H4.6: độ tin cậy theo thang ngày và theo lớp ngưỡng (4 bộ nước ngoài)

- **Câu hỏi:** RL-24 cho thấy theo giờ gần như không chuyển được giá trị. Ở thang ngày/tuần, hoặc khi chỉ cần đúng **lớp ngưỡng** (tốt / cần theo dõi / xấu) như khuyến cáo thực sự dùng, thì sao? Chuyển giá trị có thắng được khí hậu tháng của chính trạm và giá trị cũ của chính trạm không?
- **Thiết lập:** `experiments/h4_multiscale.py` dùng lại loader, QC và danh sách cặp của 4 lần chạy giờ (USGS SF Bay, Texas, NERRS 8 khu, Chesapeake); kiểm tra lại thang giờ khớp tuyệt đối (Δ = 0). Thang: giờ, trung bình/min/max ngày (≥ 18 giờ hợp lệ), trung bình 7 ngày. Lớp ngưỡng cá giò (bảng cobia + `core/alerts.py`): DO xấu < 4, theo dõi 4–5; nhiệt độ tốt 25–30, xấu < 18 hoặc > 33; độ mặn xấu < 15, tốt 26–32; pH tốt 7.5–8.2, xấu < 7.0 hoặc > 8.5. Lớp "suy biến" (lớp xấu < 5 % hoặc > 95 %, hoặc một lớp > 95 %) không được tính là bằng chứng. Mốc so sánh: khí hậu tháng của chính trạm (năm khác), giá trị chính trạm 1 ngày và 7 ngày trước. Chesapeake chồng lấn ≥ 90 ngày, các bộ khác ≥ 365 ngày.
- **Kết quả, giá trị:**
  - Lên thang ngày **gần như không cứu được** việc chuyển giá trị: bán kính 80 % (cùng chế độ) giữ nguyên ở hầu hết ô. Ngoại lệ: SF Bay trung bình ngày có hiệu chỉnh (DO, Sal, pH tới 30 km), trung bình 7 ngày (Temp Texas 20 km, NERRS 2 km).
  - Chuyển giá trị (hiệu chỉnh) thắng khí hậu tháng ở mọi bộ, nhưng **thua giá trị 1 ngày trước của chính trạm** ở Sal, pH, DO, độ đục (ví dụ NERRS Sal 0.54 so với 0.78; Chesapeake pH 0.60 so với 0.80). Riêng nhiệt độ ngang hoặc hơn ở Texas (0.74 so với 0.59), NERRS (0.62 so với 0.61), Chesapeake (0.54 so với 0.52); thua ở SF Bay (0.83 so với 0.93).
- **Kết quả, lớp ngưỡng (theo ngày, cùng chế độ, thô):**
  - **Nhiệt độ: đạt 80 % tới 20–30 km ở cả 4 bộ**, kappa 0.66–0.94, lớp không suy biến, thắng khí hậu tháng.
  - Độ mặn: NERRS 2–5 km (kappa 0.57–0.86); Chesapeake và SF Bay "đạt" tới 30 km nhưng suy biến (hầu hết ngày cùng một lớp) → không tính.
  - DO, pH: "đạt" chủ yếu vì lớp xấu hiếm (0.1–6 %) → suy biến; chỉ NERRS DO hiệu chỉnh 2 km và Chesapeake pH hiệu chỉnh 2 km là có tín hiệu.
- **Kết luận:**
  - Thông tin dạng **lớp ngưỡng nhiệt độ theo ngày** chuyển được xa (20–30 km) và vững qua 4 hệ thống: đây là thứ duy nhất bản đồ tin cậy có thể hứa ngoài vài km.
  - Với độ mặn, pH, DO, một số đo cũ (1 ngày) **của chính điểm đó** tốt hơn số chuyển từ trạm khác → nên ưu tiên lấy mẫu định kỳ tại điểm nuôi hơn là mượn sensor lân cận.
  - Đánh giá lớp ngưỡng phải báo kèm tỷ lệ lớp xấu và kappa; nếu không, các biến hiếm khi xấu (DO, pH) cho "độ tin cậy" giả.
- **Hạn chế:** lớp ngưỡng theo cá giò, áp sang hệ ôn đới/cận nhiệt đới làm lớp nhiệt độ mất cân bằng theo mùa; Chesapeake nới chồng lấn 90 ngày; persistence 1 ngày cần số đo hằng ngày tại điểm đích (thực tế VN là 2–3 tháng/lần).
- **Artifact:** `h4-multiscale-20261017/` (cells, radius, baseline_compare, hourly_check, manifest; commit ae7a0b7).

## RL-28 · 2026-10-17 · H4.7: IRLON, Indian River Lagoon (Florida)

- **Thiết lập:** SECOORA ERDDAP (bản sao mở của IRLON, HBOI-FAU), 13 trạm, 2014-05 → 2026-10, theo giờ, chỉ cờ QARTOD 1; 156 cặp có hướng, 21 cặp ≤ 30 km, chỉ 2 cặp cùng chế độ (NF–SF 2.5 km, LP–VB 6.3 km). Mưa: ERA5 (máy đo tại trạm chỉ bằng 19–63 % ERA5). Mùa ướt theo dữ liệu: 10–2.
- **Kết quả:**
  - Bán kính 80 %: theo giờ Temp 5 km, còn lại 0; theo ngày Temp 10 km (cùng chế độ), pH hiệu chỉnh 10 km; DO, độ đục 0 ở mọi thang.
  - Sal, pH: chế độ mặn giải thích độ tin cậy (R² 0.61, 0.67), khoảng cách ≈ 0 (r giữa hai biến 0.08 nên ít đa cộng tuyến).
  - Hiệu chỉnh thắng khí hậu tháng (Sal +0.22…+0.50), chuyển thô thua.
  - Mưa lớn: DO hiệu chỉnh −0.04…−0.08; độ đục lại tốt hơn.
  - Nitrat hiệu chỉnh (thăm dò): 0.78–0.86 theo ngày, bán kính 5–10 km; phosphat 0.
- **Kết luận:** bộ thứ 7 lặp lại kết quả RL-24 (chế độ mặn > khoảng cách cho Sal, pH; DO, độ đục không chuyển được).
- **Hạn chế:** quá ít cặp cùng chế độ; trạm phía bắc chỉ từ 2022; hai lần chạy đầu hỏng vì thiếu bộ nhớ để lại `irlon-h4-reliability-20261017/` và `-r2/` (không có manifest, không dùng).
- **Artifact:** `irlon-h4-reliability-20261017-r3/`; dữ liệu `data/foreign/irlon_secoora/` (33 MB); commit 37b9b50.

## RL-29 · 2026-10-22 · Bão: mức phơi nhiễm tại NB1 từ IBTrACS (hồi cứu, theory-only)

- **Câu hỏi:** từ 1980 đến nay, cơn bão nào đã đi gần lồng ở Cát Bà, gió tại lồng ước tính cỡ nào, và Yagi 2024 có được tái hiện đúng không?
- **Thiết lập:** `experiments/storm_hindcast.py` (`core/storm_advisory.py`), chạy cuối `storm-hindcast-20261022d`. 265 lượt bão trong 500 km quanh NB1, mùa 1980–2026. Cường độ lấy theo thứ tự TOKYO, HKO, USA×0.93, CMA. Gió tại lồng: từ bán kính gió (cận dưới) hoặc Rankine biến đổi (α 0.5), chặn ở 34 kt ngoài R34. Đường đi nội suy mỗi 30 phút. Loại bão / cấp độ QĐ 18 chỉ tính khi bão ở trong 200 km. Các lần chạy `-20261022`, `-b`, `-c` bị thay thế: b thêm gió CMA/HKO, c thêm nội suy 30 phút, d sửa lỗi nội suy làm đầy NaN gốc.
- **Kết quả:**
  - `exposure_method`: rankine 194, rankine_capped_by_r34 42, wind_radii 25, no_intensity 4.
  - Cấp Beaufort tại lồng: cấp 6–7: 92; 8–9: 21; 10–11: 8; ≥ 12: 0; không xác định: 4. Từ cấp 8 trở lên: 29 lượt = 0.62 lượt/năm.
  - Theo tháng (lượt/năm, ≥ cấp 8): T6 0.106, T7 0.128, T8 0.128, T9 0.149, T10 0.085, T11 0.021, T12–T5 là 0.
  - YAGI 2024: gần nhất 21 km lúc 2024-09-07 06Z; gió tại lồng ≥ cấp 11 (cận dưới theo bán kính gió, cả hai hệ số 0.93 và 0.88); bão cấp 15, cấp độ QĐ 18 tham khảo = 4. ~~ERA5 tại NB1: tối đa 29.56 m/s (cấp 11), giật 52.9 m/s.~~ **Đính chính (RL-31):** số này là archive best_match = ECMWF IFS 9 km, không phải ERA5; ERA5 thật: 18.86 m/s (cấp 8), giật 35.3 m/s. Khớp một dòng trong danh mục sự kiện. Ảnh SAR (VAST, sơ bộ): khoảng 80 % lồng bè phía nam Cẩm Phả bị phá hủy.
  - WIPHA 2025: 17 km, lồng cấp 7. MAYSAK 2026 (đỉnh 07-04 giờ địa phương, 74 km): lồng cấp 7, bão cấp 9. NARRA 2026 (đỉnh 08-23, 74 km): lồng cấp 7, bão cấp 8.
  - Cảm biến (mô tả, n = 2): NARRA, nhiệt độ giảm khoảng 3.3 °C từ ngày −3 (30.34) xuống ngày 0 (27.01) rồi hồi phục; TSS không có tín hiệu rõ. MAYSAK ngày −2 (2026-07-02) thiếu dữ liệu (1058 dòng).
- **Kết luận:** phương pháp tái hiện được mức gió cao ở Yagi (≥ cấp 11, phù hợp ERA5 và thiệt hại thực tế) và cho tần suất bão ảnh hưởng theo tháng: mùa nguy cơ là T6–T10, đỉnh T9. Đây là số liệu hồi cứu theo best track, không phải năng lực dự báo.
- **Hạn chế:** chỉ là cận dưới trong vùng bán kính gió (không có cấp ≥ 12 kể cả Yagi); Rankine bỏ qua che chắn của đất liền / vịnh và tính bất đối xứng; best track là oracle, không có tuyên bố về thời gian báo trước; mapping Điều 42 QĐ 18 lấy từ tóm tắt thứ cấp, cần đối chiếu bản gốc; bậc hành động chỉ là đề xuất; chưa có ngưỡng sóng; sensor n = 2 chỉ mô tả.
- **Artifact:** `storm-hindcast-20261022d/` (passages, climatology_year/month, yagi_check, events_check, sensor_response_2026, manifest).
- **Tiếp theo:** độ trễ báo trước bằng Open-Meteo Previous Runs cho Yagi/Maysak/Narra; nối vào shadow runner.

## RL-30 · 2026-10-22 · Nắng nóng: SST tại NB1, sai lệch với sensor và khí hậu 1982–2026

- **Câu hỏi:** nhiệt độ nước có từng chạm các mức stress của cá giò (31 / 33 / 34 °C) không, tần suất tăng chưa, và mùa nào rủi ro nhất?
- **Thiết lập:** `experiments/heat_hindcast.py` (`core/heat_stress.py`), chạy `heat-hindcast-20261022`. NOAA OISST v2.1, ô 20.625 N 107.125 E (~13 km từ NB1), 1982-01-01 → 2026-10-20, tải từ NOAA PSL THREDDS (ERDDAP NCEI chỉ có từ 2020). Sai lệch tính trên 129 ngày 2026-05-29 → 10-20. Mức theo trung bình ngày; mức 1 ("theo dõi") là ngày ≥ 31 °C; mức 2–3 (33 / 34 °C) chỉ được tính khi đã có ≥ 3 ngày liên tiếp ≥ 31 °C, nếu không bị hạ về mức 1; bản hiệu chỉnh cộng độ lệch trung vị +0.30 °C.
- **Kết quả:**
  - OISST: cực đại 31.93 °C (2023-07-15); trung bình tháng 7 là 29.55, tháng 1 là 20.05.
  - Sensor − OISST: trung vị +0.30 °C, MAE 0.82, r 0.44. Sensor − Open-Meteo marine: trung vị −0.73, MAE 0.88, r 0.62. Trung vị theo tháng so với OISST: T6 +0.15, T7 +0.35, T8 +0.28, T9 −0.05, T10 +0.45; p90 +1.18; max +1.91 (2026-09-23, sensor 31.25 so với OISST 29.34); ngày sensor nóng nhất 2026-08-17: 31.99 so với OISST 30.09 (+1.90).
  - Sensor 2026: 31/129 ngày có trung bình ngày ≥ 31 °C; 0 ngày ≥ 33. OISST: 0 ngày ≥ 31 trong cùng giai đoạn.
  - Khí hậu 1982–2025 (44 năm đủ), số ngày/năm ở mức cảnh báo ≥ 1 (ngày ≥ 31 °C): thô 5.75 (10 năm đầu 0.1; 10 năm cuối 17.3); hiệu chỉnh +0.30: 10.16 (0.9 → 28.5). Mức ≥ 2 (33 °C) và ≥ 3: 0 ở mọi năm, cả thô lẫn hiệu chỉnh. Với độ lệch p90 +1.18: tổng 8 ngày ≥ 33 °C, đều sau 2012; chưa có ngày ≥ 34 °C.
  - Xu hướng Theil–Sen của số ngày mức ≥ 1: thô +1.41 ngày/thập kỷ (KTC 95 % 0.0–3.08); hiệu chỉnh +3.94 (1.94–6.67).
  - Lịch (mức ≥ 1, hiệu chỉnh): tuần ISO 21–40, đỉnh tuần 29 (tỷ lệ năm có ngày nóng 0.295). Lịch stress (≥ 33 °C) trống.
  - Cờ nóng + lặng gió: 0.02 ngày/năm, gần như không bao giờ; giả thuyết chưa kiểm được vì không có DO.
- **Kết luận:** mức 31 °C tăng rõ trong 44 năm và tập trung giữa tuần 21 và 40 (khoảng tháng 5 đến tháng 10). Mức stress 33 °C chưa xuất hiện trong OISST. Sensor cho thấy nước ở lồng có thể nóng hơn sản phẩm vài phần mười °C, có ngày tới ~2 °C.
- **Hạn chế:** độ lệch chỉ ước từ một mùa (độ bất định ~1 °C, lớn hơn chính độ lệch) nên bản hiệu chỉnh chỉ là ca nhạy cảm, không phải hiệu chuẩn; ô OISST 0.25° ngoài khơi đọc thấp đỉnh nóng trong vịnh; mức nhiệt là rủi ro tăng trưởng/stress, không phải tử vong; tài liệu mâu thuẫn về nhiệt độ tối ưu (27–29 so với 33 °C).
- **Ghi chú quy trình:** thư mục `heat-hindcast-20261022` (lần chạy đầu, mới vài phút tuổi) đã bị agent triển khai xóa và tạo lại để thêm một file đầu ra. Đây là ngoại lệ so với quy tắc run dir ghi một lần; không mất dữ liệu nguồn nào. Manifest của lần chạy này có trước trường `offset_status` (code thêm sau; run dir không chạy lại).
- **Artifact:** `heat-hindcast-20261022/` (bias, trend, daily_oisst, climatology_year, heat_calendar, heat_calendar_watch, manifest).
- **Tiếp theo:** lịch thả giống (kết hợp `heat_calendar_watch.csv`); chỉ số bệnh (Vibrio/Streptococcus); thêm mùa sensor để ước độ lệch tốt hơn.

## RL-31 · 2026-10-23 · Đính chính nguồn "ERA5" và đánh giá thời gian báo trước của dự báo gió

- **Phát hiện (review độc lập):** file `data/hazards/era5/era5_nb1_1982_20261020.csv` tải từ archive Open-Meteo **không có `models=`**, tức `best_match` = ERA5 trước 2017, ECMWF IFS 9 km (ghép các lần chạy nghiệp vụ) từ 2017. Previous Runs lead 0 trùng 100 % với file này, nên lần đánh giá đầu (`storm-leadtime-20261023`, `-b`) dùng "giá trị thật" không độc lập. Con số Yagi 29.56 m/s cũng là IFS.
- **Sửa:** `hazard_data.py era5 --model era5` (tên file có model, manifest ghi model); `latest_era5(model)`; file cũ giữ nguyên, chỉ được coi là best_match. Chặn trong `storm_leadtime.py`: dừng nếu lead 0 trùng giá trị thật > 50 % số giờ. Mô hình dự báo cố định `ecmwf_ifs025` (lead 1–7 từ 2024-02-04); `gfs_seamless` và best_match làm đối chứng. Thêm "lead nhất quán" (mọi lead 1..N đều đạt).
- **Kết quả** (`storm-leadtime-20261023d`, 2024-02-10 → 2026-10-16, 980 ngày, 19 lượt bão; ERA5 thật: 23 ngày ≥ cấp 6, 1 ngày ≥ cấp 8, 0 ngày ≥ cấp 10):
  - Cấp 6, POD/FAR/CSI theo lead 1→7: 0.61/0.07/0.58 · 0.48/0.08/0.46 · 0.52/0.14/0.48 · 0.48/0.15/0.44 · 0.35/0.20/0.32 · 0.17/0.43/0.15 · 0.04/0.50/0.04.
  - CSI lead 1 theo mô hình: ifs025 0.58, gfs 0.45, best_match 0.22. MAE gió 0.90 → 1.47 m/s (lead 1→7), r 0.82 → 0.44; lệch ifs025 ổn định −0.13…−0.48 m/s các năm.
  - Lead nhất quán cấp 6 theo cơn: Wipha 7 ngày (134 h), Yagi 6 (115 h), Bualoi 6 (111 h), Kajiki 5 (100 h), Maysak 2 (49 h), Matmo 1, Nongfa 1, Narra không kịp; bỏ sót Prapiroon, Trami; Ragasa báo nhầm. Yagi cấp 8: 4 ngày (92 h); cấp 10 (so best track): 3 ngày (73 h).
- **Kết luận:** chỉ đọc gió tại lồng, mô hình ifs025 cảnh báo cấp 6 tốt tới khoảng 4 ngày (CSI ≥ 0.44), giảm mạnh sau 5 ngày. Cấp ≥ 8 chỉ có 1 cơn, chưa có cơ sở thống kê.
- **Hạn chế:** ERA5 0.25° đọc thấp lõi bão; giờ phát hành danh nghĩa ±12 h; ngày UTC; mẫu nhỏ, không có KTC.
- **Artifact:** `storm-leadtime-20261023d/`; dữ liệu `forecast_runs/previous_runs_{ecmwf_ifs025,gfs_seamless}_nb1_*`, `era5/openmeteo_era5_nb1_1982_20261016.csv`. Thay thế: `storm-leadtime-20261023`, `-b`; `yagi_check` trong `storm-hindcast-20261022d`, `-20261023c` (thay bằng `-20261023e`); cờ nóng + lặng gió trong `heat-hindcast-20261022` (thay bằng `-20261023b`: 0 ngày, vì nhiệt độ không khí tối đa ERA5 thật tại NB1 chưa từng đạt 35 °C).
- **Tài liệu:** `docs/eval/2026-10-23-storm-leadtime.md`.

## RL-32 · 2026-10-23 · Khả năng phát hiện ngày nóng ≥ 31 °C so với sensor lồng

- **Thiết lập:** `experiments/heat_skill.py`, chạy `heat-skill-20261023b`. Giá trị thật: trung bình ngày sensor (≥ 1296 dòng, 10–40 °C), 130 ngày, 31 ngày ≥ 31 °C. Hiệu chỉnh ngoài mẫu: split (train 05-29…07-31, test 08-01…10-21) và leave-one-month-out (LOMO). Nhiệt độ không khí = ERA5 thật.
- **Kết quả (LOMO, CSI):** OISST thô 0 (POD 0, OISST chưa bao giờ ≥ 31 °C mùa này); chỉ nhiệt độ không khí 0.44; marine + không khí 0.46; sensor hôm qua (persistence) 0.66. Lead 1–3 chỉ là persistence của sản phẩm (không có lưu trữ dự báo SST).
- **Kết luận:** OISST chỉ dùng cho khí hậu/lịch, không dùng để cảnh báo ngày. Kỹ năng chủ yếu đến từ nhiệt độ không khí; có sensor thì dùng giá trị hôm qua.
- **Hạn chế:** một mùa, ít ngày nóng, không KTC; không đánh giá được mức 33 °C.
- **Thay thế:** `heat-skill-20261023`. **Tài liệu:** `docs/eval/2026-10-23-heat-skill.md`. **Ghi chú quy trình:** agent xóa và tạo lại thư mục chạy đầu `heat-skill-20261023` (vài phút tuổi), ngoại lệ thứ hai với quy tắc ghi một lần.

## RL-33 · 2026-10-23 · Danh mục sự kiện và đối chiếu nguồn (QĐ 18, Harper 2010)

- **Kết quả:** `experiments/hazard_events.csv` 12 dòng (8 bão, 1 dịch bệnh, 2 cá/ngao chết, 1 nắng nóng thiếu oxy); 6 dòng xác thực đủ số liệu thiệt hại. Điều 42 QĐ 18 đối chiếu toàn văn .doc: hàm `qd18_risk_level` đúng cho vùng biển ven bờ / Đông Bắc Bộ (chỗ mơ hồ: ATNĐ cấp 6–7). Điều 50 (gió mạnh trên biển) và Điều 47 (nắng nóng, nhiệt độ không khí) ghi lại, chưa đưa vào code. Hệ số 0.93 xác nhận theo WMO/TD-1555 Bảng 1.2 (at-sea).
- **Kiểm tra nhất quán** (`storm-hindcast-20261023f`): 8/8 bão khớp tên, 8/8 gió lồng ≥ cấp 6, 1/8 ≥ cấp 8 (Yagi). Đây là kiểm tra nhất quán, không phải năng lực phát hiện (danh mục chọn từ bão đã biết). Kajiki: không có điểm quỹ đạo trong 200 km nên thiếu cường độ.
- **Tài liệu:** `docs/eval/2026-10-23-events-and-sources.md`.

## RL-34 · 2026-10-23 · Chỉ số nguy cơ dịch bệnh theo điều kiện môi trường (lý thuyết)

- **Thiết lập:** `core/disease_risk.py`, `experiments/disease_hindcast.py`, chạy `disease-hindcast-20261023b` (ERA5 thật cho mưa và nhiệt độ không khí). Nhóm: Vibrio, Photobacterium, Streptococcus, Amyloodinium, Cryptocaryon, rét (Nhu et al. 2011: ngừng ăn < 18 °C, ngừng lớn < 22 °C, ~15 °C > 5 tuần gây chết hàng loạt 2008).
- **Kết quả:** trên OISST mức "cao" 216.6 ngày/năm, không bao giờ "thấp", nên nhiệt độ nước một mình không tách được ngày rủi ro. 5 sự kiện chấm điểm: 3/5 có ngày "cao" trong 14 ngày trước so với kỳ vọng khí hậu 0.659 → `no_skill_over_climatology`, chưa vững với ±1 °C; chỉ 2 sự kiện có tên mầm bệnh → `insufficient_evidence`. OISST bỏ sót cả hai đợt rét 2008 và 2016; nhiệt độ không khí ERA5 bắt được (rủi ro rét 1.0 và 0.6).
- **Kết luận:** giá trị dùng được hiện tại là cảnh báo rét kéo dài; chỉ số nhiệt cho mầm bệnh cần DO / độ mặn / mật độ nuôi mới có ý nghĩa.
- **Thay thế:** `disease-hindcast-20261023`. **Tài liệu:** `docs/eval/2026-10-23-disease-risk.md`.

## RL-35 · 2026-10-23 · Lịch thả giống theo rủi ro (lý thuyết)

- **Thiết lập:** `experiments/stocking_calendar.py`, chạy `stocking-calendar-20261023c`. Chu kỳ 26 và 39 tuần, 1991–2025. Điều kiện cứng: 8 tuần đầu OISST(+0.30) ≥ 22 °C ở ≥ 80 % số năm (Nhu et al. 2011); cờ chết rét (≥ 14 ngày < 18 °C hoặc ngày ≤ 15 °C); điểm tổng hợp tương đối trên các tuần khả thi; lớp tháng theo ngưỡng điểm tuyệt đối.
- **Kết quả:** T12–T2 "tránh (lạnh lúc thả)"; T3, T11 biên. Cửa sổ tốt nhất: chu kỳ 26 tuần thả tuần 28–33 (cuối T7–giữa T8); 39 tuần thả tuần 35–40 (giữa T9). Không tuần nào ổn định với mọi bộ trọng số; kịch bản mùa đông lạnh hơn 1.5 °C đổi kết quả 39 tuần sang mùa xuân (tuần 13–15).
- **Hạn chế:** không có số liệu thật; độ dài chu kỳ, trọng số, phạt 0.5 là quy ước; OISST đọc thấp rét trong vịnh.
- **Thay thế:** `stocking-calendar-20261023`, `-b`. **Tài liệu:** `docs/eval/2026-10-23-stocking-calendar.md`.

## RL-36 · 2026-10-23 · Bản đồ độ sâu và hiển thị lớp lưới trên research-map

- **Chẩn đoán:** lớp độ sâu cũ chỉ dùng Copernicus SDB 100 m: 0 ô hợp lệ ở Cát Bà/Lan Hạ, Hạ Long, quanh NB1; 3.829/1.115.136 ô toàn tile, chủ yếu bãi triều cửa sông Hải Phòng; "phủ 83 %" là do mẫu số đã loại ô thiếu. Lớp mưa / mực nước vẽ mỗi điểm lưới truy vấn ~1.2 km thành một ô vuông dù lưới mô hình thô hơn (~8 km).
- **Sửa:** NOAA ETOPO 2022 15″ (~460 m, `data/depth/etopo2022-20261023/`), vẽ dải độ sâu + đường đẳng sâu 2/5/10/20/30 m cắt theo mặt nước OSM, cờ "thô" và "nghi ngờ" (hố > 30 m tách khỏi biển mở); lớp vô hướng thành bề mặt nội suy, chú giải ghi độ phân giải nguồn. Độ sâu trung vị: NB1 6 m, Lan Hạ 11.5, Hạ Long 5, Bái Tử Long 6.
- **Hạn chế:** sai nguồn ở Cửa Lục, Vân Đồn/Cửa Ông (60–149 m, đã đánh dấu); không thấy luồng hẹp; cần GEBCO 2024 (TID) hoặc hải đồ / đo sâu tại lồng.
- **Tài liệu:** `docs/eval/2026-10-23-bathymetry-map.md`; giao diện: `docs/eval/2026-10-23-ui-ux.md`.

## RL-37 · 2026-10-23 · Cảnh báo bão nhìn toàn vùng (Tây Thái Bình Dương – Biển Đông)

- **Câu hỏi:** theo dõi tâm bão từ khi còn ở Thái Bình Dương / Philippines / Biển Đông có báo sớm hơn cách chỉ đọc gió dự báo tại lồng không?
- **Thiết lập:** `experiments/storm_basin.py`, `experiments/tigge_tracks.py`, chạy `storm-basin-20261023b`. IBTrACS 1980–2026 (1511 hệ thống). Mô hình xác suất P(tâm bão ≤ 200 / 500 km NB1 trong 24–120 h) từ vị trí, hướng di chuyển 12 h, cường độ, tháng; kiểm định chéo để riêng từng mùa. Quỹ đạo dự báo thật: ECMWF ensemble từ TIGGE (NCAR d330003, tải không cần đăng nhập), 531 lần chạy 2024–2026.
- **Khí hậu:** 2.5 cơn/năm vào ≤ 200 km NB1; 43 % hình thành ngay trên Biển Đông, 24 % biển Philippines, 33 % xa hơn 135°E; 42 % đi qua đất liền Philippines. Thời gian trung vị tới ≤ 200 km: từ 130°E 123 h, 125°E 95 h, 120°E 72 h, 115°E 45 h; bão sinh trên Biển Đông trung vị 72 h từ khi hình thành.
- **Mô hình thống kê:** Brier skill 0.21–0.28, AUC 0.87–0.905 (200 km, 120 h); báo trước trung vị 57 h ở ngưỡng 0.3, đổi lại 1.8 báo nhầm/mùa (không vào 500 km) và 2.4 lần/mùa chỉ vào 200–500 km.
- **ECMWF ensemble:** cùng thời điểm, skill 0.78, AUC 0.99; 7/7 cơn vào 200 km được báo, trung vị 93 h, 2 báo nhầm + 3 suýt trúng trên 60 cơn. Sai số quỹ đạo deterministic gần Việt Nam: 40/76/102/147/215 km ở 24/48/72/96/120 h.
- **So với đường gió tại lồng (2024–2026):** bão mạnh từ xa (Yagi, Wipha, Kajiki, Bualoi) hai cách ngang nhau (4–5 ngày). Lợi ích chính: bắt được các cơn đường gió bỏ sót hoặc muộn (Prapiroon 69–93 h, Matmo 102 h, Trami). Bão sinh trên Biển Đông (Maysak, Wutip, Nongfa): tối đa ~2.5 ngày với mọi cách; Narra sinh cách NB1 157 km, không báo trước được.
- **Kết luận:** đề xuất hai bước (chưa vận hành): "theo dõi" theo ECMWF ensemble P(≤ 500 km, 120 h) ≥ 0.3; "cảnh báo" theo gió tại lồng. Mô hình thống kê chỉ dự phòng.
- **Hạn chế:** best track là phân tích lại; "≤ 200 km" là khoảng cách, không phải mức gió (Ragasa 128 km chỉ cấp 4); ensemble chỉ 3 mùa, 7 cơn; ghép bão với quỹ đạo theo vị trí ban đầu.
- **Thay thế:** `storm-basin-20261023`. **Tài liệu:** `docs/eval/2026-10-23-storm-basin.md`.

## RL-38 · 2026-10-23 · Bằng chứng thiệt hại lồng bè do bão và ngưỡng gió gây hại

- **Thiết lập:** `experiments/storm_damage.py`, chạy `storm-damage-20261023b`. 34 sự kiện có nguồn (20 Quảng Ninh/Hải Phòng, 8 miền Trung, 6 vùng tương tự), mỗi dòng có trích nguyên văn đối chiếu với bản lưu cục bộ (`data/references/storm_damage/`, sha256) và Wayback nếu có sẵn (25/34). 10 nguồn kỹ thuật. Sổ nguồn: `docs/references/storm-damage-sources.md`.
- **Kết quả (22 dòng phân tích, 16 cơn):** lồng gỗ/hỗn hợp không thiệt hại ở gió tại lồng ≤ cấp 7; thiệt hại bắt đầu từ cấp 8; từ cấp 10 mọi trường hợp thiệt hại nặng/mất trắng. Đường cong thiệt hại (logistic, thăm dò): P(thiệt hại nặng) = 50 % ở cấp 9.0 (bootstrap 90 %: 7.8–10.4); P(có thiệt hại) = 50 % ở cấp 8.4.
- **Kỹ thuật:** FAO/NACA 1989 tiêu chí đặt lồng nổi: gió < 10 kn, sóng < 1 m; FAO: lồng nổi đơn giản chịu sóng ~2 m, trong bão gần như không vị trí nào an toàn. "HDPE chịu cấp 12" chỉ là tuyên bố của người bán. TCVN 13997:2024 có nhưng chưa mở được văn bản.
- **Đề xuất (chưa sửa code):** đưa "thu hoạch sớm" xuống bậc cấp 8, kích hoạt khi dự báo cấp 8 trong 48–72 h; cân nhắc "người rời lồng" từ cấp 9.
- **Hạn chế:** nguồn báo chí; 6/8 trường hợp "không thiệt hại" chỉ là tìm không thấy tin; gió tại lồng phần lớn là cận dưới; 5/22 dòng cùng cơn Yagi; thiên lệch đưa tin.
- **Thay thế:** `storm-damage-20261023` (không có bootstrap). **Tài liệu:** `docs/eval/2026-10-23-storm-damage.md`.

## RL-39 · 2026-10-23 · Mức phơi nhiễm theo từng điểm nuôi (đà gió, che chắn, sóng, dòng chảy)

- **Thiết lập:** `core/site_exposure.py`, `experiments/site_exposure.py`, chạy `site-exposure-20261023`. Đà gió 16 hướng trên mặt nước OSM (bước 100 m, tới 200 km); che chắn từ DEM Copernicus GLO-30 (DSM, ~30 m, `data/terrain/copernicus-glo30-20261023/`) theo đường cong chắn gió EC1763 (sàn 0.5 là giả định); sóng giới hạn theo đà gió và độ sâu theo SPM 1984 (thời gian gió 3 h giả định); lớp sóng/dòng chảy theo NS 9415; dòng chảy Open-Meteo SMOC ~8 km.
- **Kết quả 14 trạm:** 9 trạm hở (NB1, NB4, NB5, NB6, NB16, NB19, NB25, NB27, NB28), 2 bán kín (NB15, NB3), 3 kín (NB2, NB17, NB26). Gió cấp 10 từ hướng xấu nhất: trạm hở Hs ~3 m (NB16 ~1.6 m), trạm kín 0.4–0.7 m. NB1 nguy hiểm nhất với gió tây nam (đà gió 66 km); trong Yagi gió tại NB1 chuyển từ 319° sang 200° sau khi mắt bão qua. Dòng chảy p95 ≤ 0.47 m/s ở cả 14 trạm (mô hình 8 km không thấy dòng siết; Delft3D công bố: Cửa Lục > 1 m/s khi triều rút). Trại nuôi OSM (33): 12 kín, 17 bán kín, 4 hở.
- **Yagi:** thiệt hại gần như mất trắng ở mọi nơi nên không kiểm chứng được thứ hạng phơi nhiễm (n = 1); bảng hướng nguy hiểm theo trạm là sản phẩm dùng được.
- **Hạn chế:** chưa có đo sóng/gió/dòng tại lồng; công thức SPM ngoại suy ở cấp 10–12, không tính sóng lừng; đường cong chắn gió 2-D cho núi đá vôi 3-D; kết quả nhạy với vị trí vài trăm mét (NB16 dịch 884 m vào mặt nước OSM); `stations.json` của run này còn 7 giá trị NaN (code đã sửa cho lần sau).
- **Tài liệu:** `docs/eval/2026-10-23-site-exposure.md`.

## RL-40 · 2026-10-24 · Cảnh báo shadow theo trạm, cấu hình bậc do admin chỉnh

- **Thiết lập (Đợt 0–2, kế hoạch `docs/superpowers/plans/2026-10-23-phase1-parallel.md`):** cấu hình mặc định `config/alert_tiers.default.json`; phiên bản admin ghi thêm vào `runtime/alert-config/` (decisions #20); `core/alert_config.py` (kiểm tra hợp lệ, khóa cấu trúc: chỉ sửa ngưỡng, hành động, số ngày kéo dài, ghi đè theo lớp vị trí / trạm); API `/api/v1/admin/alert-config*`; trang `#/settings/alerts`. `core/hazard_runner.py` tạo bản ghi shadow theo trạm cho gió bão, sóng (theo đà gió), nắng nóng, rét, nguy cơ dịch bệnh; điều kiện "kéo dài N ngày" dùng cả ngày quan trắc (sensor NB1, nếu không có thì Open-Meteo marine các ngày trước). Gọi từ `shadow_runner` qua cờ `HAZARD_RUNNER_ENABLED` (mặc định tắt).
- **Phát lại** (`hazard-replay-20261023`, `-20261024`; dữ liệu tái phân tích dùng như dự báo, chỉ kiểm logic): Yagi — gió tại lồng bậc tối đa 2 ở NB1, NB25, NB27, NB28; sóng bậc 3 ở NB4; các trạm kín ở bậc 0–1. Hè 2026: nắng nóng bậc 1 trong 47/77 ngày (Open-Meteo marine), bậc 2 (≥ 33 °C ≥ 3 ngày) không bao giờ đạt kể cả khi có ngày quan trắc (sensor cao nhất 31.99 °C).
- **Sửa mặc định:** cấu hình rét bị ngược (bậc 3 không cần kéo dài, bậc 2 cần 14 ngày) → bậc 2/3 đều cần 3 ngày.
- **Hạn chế:** chưa chạy thật (cờ tắt, chưa có task); ngưỡng 33 °C có thể quá cao cho vùng này (admin chỉnh được); nhiệt độ gieo từ sensor lồng, ngày dự báo là SST thô.

## RL-41 · 2026-10-24 · Theo dõi bão thời gian thực từ ECMWF Open Data

- **Thiết lập:** `core/storm_tracks.py`, `experiments/ecmwf_opendata.py`; file quỹ đạo BUFR ENS (51 thành viên) và HRES từ data.ecmwf.int (CC BY 4.0, giữ ~4 ngày), đọc bằng `eccodes` (`requirements-hazards.txt`). Gộp bản trùng `7xX` vào bão đã quan sát (cùng thành viên, bắt đầu ≤ 300 km); bão mới hình thành tính riêng, không đặt bậc.
- **Kết quả:** lần chạy 2026-10-23 00 UTC không có bão gần NB1 (CHAMPI cách ~1600 km, đi lên đông bắc); 14 trạm bậc 0. Đối chiếu TIGGE: 414/414 cặp (lần chạy, bão) cho cùng xác suất; Yagi 2024-09-03 00Z: P(≤ 200 km, 120 h) 0.882, P(≤ 500 km) 1.0.
- **Tiếp theo:** task chạy 6 giờ/lần (cần chủ dự án đồng ý); lỗi tải / giải mã ghi bản ghi bỏ qua có lý do.

## RL-42 · 2026-10-24 · Bằng chứng dịch bệnh từ nguồn công khai

- **Kết quả:** `experiments/disease_events.csv` thêm 6 sự kiện (tổng 12; 3 có tên mầm bệnh, chỉ Cái Chiên 2025 có xét nghiệm). Sổ nguồn `docs/references/disease-sources.md`. Chạy lại `disease-hindcast-20261024`: 8/11 so với kỳ vọng khí hậu 0.789 → vẫn `no_skill_over_climatology`, nay vững với ±1 °C; 3 lần bỏ sót đều là đợt rét/giao mùa và thành phần rét đều bắt được.
- **Ghi chú quy trình:** agent đã xóa 5 bản sao trang vừa tải nhầm trong `data/references/disease/` (ngoại lệ thứ ba với quy tắc ghi một lần; không ảnh hưởng file cũ).

## RL-43 · 2026-10-24 · TCVN 13997:2024 và tiêu chuẩn lồng nuôi

- **Kết quả:** TCVN 13997:2024 "Lồng tròn HDPE nuôi cá biển quy mô công nghiệp — Yêu cầu kỹ thuật": phạm vi (độ sâu ≥ 20 m, dòng > 0.3 m/s, đường kính 10–40 m) và vài thông số dây/phao từ bản tóm tắt; văn bản đầy đủ phải mua, không vượt tường phí. NS 9415 (qua FAO TP 593): lớp sóng Hs 0.5/1/2/3 m — **trùng các bậc sóng mặc định**; lớp dòng 0.3/0.5/1.0/1.5 m/s. Không tiêu chuẩn đọc được nào có ngưỡng gió cho lồng. Sổ: `docs/references/cage-standards.md`.

## RL-44 · 2026-10-24 · Copernicus Marine tại các trạm (GLORYS12, GLO12, MFWAM)

- **Kết quả** (`cmems-sites-20261024c`): nhiệt độ so với sensor (101 ngày): GLORYS12 0.49 m bias +0.39, MAE 0.65, r 0.72, POD ≥ 31 °C 0.86, FAR 0.40 (tốt nhất); GLO12 nóng hơn ~1 °C. Độ mặn GLORYS12 không xuống dưới 28.2 psu (1993–2026); Vân Đồn 10/2025 là tháng 10 thấp nhất trong chuỗi (−2.6 psu so với khí hậu) nhưng không thấy mức 20 psu đã báo. Sóng MFWAM Yagi 2.4–3.1 m (cận ngoài khơi). Không có sản phẩm khu vực cho vịnh Bắc Bộ.
- **Đề xuất:** yếu tố độ mặn trong chỉ số dịch bệnh dùng độ lệch so với khí hậu từng ô, không dùng ngưỡng tuyệt đối.

## RL-45 · 2026-10-24 · GEBCO 2024 so với ETOPO 2022

- **Kết quả:** GEBCO 2024 (15″, kèm lớp TID) không có các hố sâu sai của ETOPO (Cửa Lục 45 → 6 m, Vân Đồn 72 → 10 m); vịnh nông sâu hơn (Hạ Long trung vị 11 vs 5 m); chỉ 2.7 % ô có đo trực tiếp (TID 10–17). Đề xuất GEBCO làm mặc định (decisions #21). Tài liệu: `docs/eval/2026-10-24-gebco-vs-etopo.md`.

## RL-46 · 2026-10-24 · Bản đồ: phơi nhiễm theo trạm, trạm cũ, H3 mượt

- **Kết quả:** lớp phơi nhiễm (hoa hướng 16 hướng, Hs ≥ 1 m) từ `site-exposure-20261023`; điểm trạm chuyển xám gạch chéo khi khuyến nghị cũ > 90 phút (hard rule 4); H3 vẽ thành bề mặt nội suy kèm ghi chú lưới (VN ~9 km); bố cục máy tính bảng thu gọn bảng bên.


## RL-47 · 2026-10-24 · Kiểm thử đầu-cuối Phase 1 (shadow)

- **Chạy thật trên runtime tạm:** ECMWF Open Data 2026-10-23 00Z — 5 bão toàn cầu, không bão gần NB1, 14 bản ghi theo dõi bão bậc 0. `run_once` với Open-Meteo trực tiếp (marine chỉ bật trong phiên kiểm thử): 280 bản ghi/lượt, mọi bản ghi có cờ shadow; gió và nắng nóng bậc 0; sóng bậc 1 ở NB4/NB27/NB28 hai lượt đầu; **nguy cơ dịch bệnh bậc 2 ở cả 14 trạm** (chỉ số 0.80–0.86 ở SST ~29.7 °C) → ngưỡng mặc định 0.4/0.75 bão hòa, cần quyết định.
- **Quy trình admin:** sửa → xem trước → lưu (v0001: gió bậc 2 8→7) → lượt chạy sau dùng v0001; v0002, khôi phục, v0003; chỉ ghi vào runtime tạm. Thử truy cập ngoài thư mục, JSON lồng sâu, thân yêu cầu lớn: đều bị chặn (đã thêm giới hạn kích thước và độ dài trường).
- **Đã sửa:** chip theo dõi bão trung tính trên trạm dữ liệu cũ; nhãn "Hôm nay" chỉ khi đúng ngày; ngày triển vọng theo quy tắc trưa địa phương; chặn mất chỉnh sửa chưa lưu khi quay lại/tiến tới; ETOPO luôn nằm dưới GEBCO; mount ghi được `runtime/alert-config` trong docker-compose (chưa thử vì Docker tắt); bộ chạy nguy cơ chạy trong luồng nền để không chặn vòng đọc sensor.
- **Còn mở:** ngưỡng dịch bệnh bão hòa; `RESEARCH_RUNTIME_DIR` và `HAP_RUNTIME_DIR` có thể trỏ khác nhau; mặc định đường dẫn độ sâu chưa theo `HAP_DATA_DIR`; khung đường thời tiết bị cắt nhãn ở 1440 px.

## RL-48 · 2026-10-24 · Giao diện: làm rõ chữ theo skill UI/UX (ui-ux-pro-max, Impeccable)

- **Nguồn tham khảo:** skill `ui-ux-pro-max` (nextlevelbuilder/ui-ux-pro-max-skill @d14efff, cài ở `~/.claude/skills`, chỉ Python và dữ liệu cục bộ); Impeccable (pbakaus/impeccable @7e51b1e) chỉ đọc `operate.md`, `clarify.md`, không chạy launcher (launcher tự tải binary). Không áp dụng gợi ý phong cách mới của skill (glassmorphism, nền tối): đây là trang vận hành, nên sửa theo hướng rõ chữ, không đổi theme.
- **Đánh giá trên Docker đầy đủ** (api 8010, giao diện 8083, Postgres, worker; lớp GEBCO dựng xong): mã nội bộ lộ ra người dùng (`scalar_grid · 358 ô · open_meteo`, `copernicus_not_configured`, `UNCHECKED`, `degC`, `vendor_unit_unknown`, `captured_live`, `lockbox`, `A3`, `bundle`, `export`, `Legacy`, `Context`); nhãn bị cắt (`Temp…`, ngày trên lưới thời tiết ở 1440 px, thanh điều hướng điện thoại); dấu thập phân lẫn `0.15` / `0,5`; chip "Không rõ" ở mọi trạm; trang Cảnh báo trống chỉ in đường dẫn file; badge H1–H4 đè icon; nhãn lớp vị trí chồng nhau.
- **Đã sửa:**
  - `lib/format.ts`: nhãn nguồn dữ liệu, lý do không khả dụng, tên chỉ số, đơn vị, trạng thái QC, kích thước lưới mô hình (không dùng lưới hiển thị ~1,2 km); mọi số hiển thị dùng dấu phẩy thập phân.
  - Thẻ cảm biến: ghi một lần "Chưa kiểm tra chất lượng" thay cho chip `UNCHECKED` trên từng ô; "Temperature / degC" → "Nhiệt độ / °C"; "đv. chưa rõ" → "đơn vị ?".
  - "Không rõ" → "Thiếu dữ liệu"; "Context" → "Thời tiết vùng"; "Legacy" → "Lưu trữ".
  - Trang Cảnh báo trống: nói trang sẽ hiện gì, bật bằng cờ nào, liên kết tới Cấu hình cảnh báo.
  - H1: "gate #16 / bundle / lockbox / A3" → "kiểm định / mô hình / tập kiểm tra giữ riêng / dữ liệu trước khi đầu dò pH trôi" (giữ "gate #16" trong phần giải thích). Chip export → "Kết quả 24/10 03:27".
  - Lưới thời tiết không cắt nhãn ngày; nhãn điều hướng điện thoại xuống dòng thay vì cắt; badge H1–H4 dời khỏi icon; ngưỡng chống chồng nhãn lớp vị trí 20 → 34 px; sửa lỗi mã hóa có từ Track B trong `views/settings/model.ts` (12 dòng: nhãn Mặc định / Lớp / Trạm trong lịch sử phiên bản, thông báo lỗi khi nhập ngưỡng, dấu —).
  - Chạy lại export (`artifacts/research-map/20261024-0330`) để đổi chữ giai đoạn H2 và câu kết luận H1.
- **Kiểm tra:** `npm run build`; test backend 94 đạt, test lõi 766 đạt; ảnh 1440 và 390 px trước / sau.
- **Còn mở:** điện thoại có 7 mục điều hướng (khuyến nghị ≤ 5), cần quyết định gộp mục; trang H1 vẫn nhiều thuật ngữ nghiên cứu trong phần mở rộng; trang Cảnh báo trên Docker trống vì `runtime/hazard-shadow` chưa có (bộ chạy chưa bật).

## RL-49 · 2026-10-24 · Đánh giá độ tin cậy nguồn dữ liệu mở

- **Câu hỏi:** các nguồn mở đang dùng có đủ tin cậy không, có nguồn chính thống hơn không? Chỉ đọc tài liệu + đối chiếu RL-29…RL-48; không chạy thí nghiệm, không sửa code. Trang web mở thử ngày 24/10.
- **Kết quả:** gió `ecmwf_ifs025` giữ (RL-31). Open-Meteo marine là MFWAM / SMOC / SST 0.08° của Météo-France, cũng là sản phẩm CMEMS, nên hai nguồn không độc lập; đổi sang CMEMS không mịn hơn nhưng có phiên bản, QUID và tải cả vùng một lần (`app/copernicus.py` đã có). Research-map không truyền `models=` (trái decisions #18).
- **Hạn mức Open-Meteo:** nếu mỗi địa điểm tính 1 lượt, bản đồ ở HEAD (358 điểm × 2 API, 30 phút) dùng ~34.400 lượt/ngày, bản đang sửa (154 + 108 nút) ~12.600, đều trên mức 10.000; theo công thức blog 2023 chỉ ~2.450 / ~870. Chưa rõ cách đếm. Worker nuốt lỗi HTTP nên bị chặn chỉ thấy là snapshot cũ.
- **Nguồn chính thống:** tin bão NCHMF (bảng 24/48/72 h có cấp độ rủi ro; HTML, RSS 404, không API); bản tin thủy triều 10 ngày NCHMF dạng PDF có Hòn Dáu (~26 km từ NB1); JMA có luồng XML mở; HKO có XML trên data.gov.hk. VNDMS cần đăng nhập; vms-north.vn, imer.ac.vn không kết nối được; không tìm thấy bản tin quan trắc vùng nuôi cho Hải Phòng / Quảng Ninh; không có trạm triều thời gian thực mở.
- **Hạn chế:** DO, độ mặn, NH4 tại lồng, dòng trong luồng hẹp, sóng vịnh kín vẫn không tin được với mọi nguồn (RL-14, RL-39, RL-44). Chưa xác minh: cách đếm lượt Open-Meteo, mốc độ cao bản tin triều, thời gian ECMWF giữ file (2–3 so với ~4 ngày).
- **Tài liệu:** `docs/eval/2026-10-24-data-sources.md`. **Tiếp theo:** giảm tần suất / ghi log lỗi research-map; cấu hình CMEMS; lưu bản tin NCHMF + JMA và bản tin triều Hòn Dáu làm tham chiếu; thử MUR SST.

## RL-50 · 2026-10-24 · Bản đồ giám sát: thời tiết & biển toàn vùng, kiểu Windy; độ dốc từ GEBCO; bãi triều mượt

- **Chẩn đoán (ảnh từng lớp trên Docker):** mưa, gió, sóng, mực nước, dòng chảy chỉ lấy trong vùng đệm 5 km quanh 14 trạm Cát Bà, lưới truy vấn ~1,2 km (358 điểm × 2 API mỗi 30 phút) — không phủ Hạ Long và tạo chi tiết giả (mô hình gốc ~8–25 km). Sóng vẽ thành rừng mũi tên; hạt gió màu xám trên nền xám, và vùng tìm điểm lân cận cố định 120–360 px nên hạt biến mất khi lưới thưa. Lớp "Dự báo khuyến nghị" (mưa cộng 6 giờ, gió mạnh nhất 6 giờ — đầu vào của bảng khuyến nghị) không có lớp vẽ. Bãi triều, đường đồng mức, độ dốc đều từ SDB 100 m chỉ phủ vài bãi ven bờ Hải Phòng, và bị gộp thành khối vuông 1,6 km / 800 m ở mức xa / vừa.
- **Sửa:**
  - Lưới vùng riêng 0,125° (~14 km) trên bbox GEBCO (106,5–108,2°E, 20,3–21,6°N): 165 nút thời tiết, ~110–120 nút biển (chỉ ô chạm mặt nước OSM). Vùng đệm 5 km giữ nguyên cho mạng trạm, tia dòng chảy, khuyến nghị. Bản tin mỗi 60 phút (~6,8 nghìn lượt gọi/ngày nếu mỗi điểm tính 1 lượt). Endpoint `/api/v1/context-region` (vùng + mặt nước giản lược ~200 m). Worker ghi log khi Open-Meteo lỗi (trước đây im lặng).
  - Giao diện: một lớp màu mỗi lúc với thang cố định kiểu Windy (mưa, mưa 6 giờ, gió, sóng, mực nước, dòng chảy) nội suy song tuyến theo giá trị; hạt trắng cho hướng gió / sóng / dòng; lớp biển cắt theo mặt nước, mưa và gió phủ cả đất liền. "Mưa & gió 6 giờ tới" vẽ mưa cộng dồn + vòng cam ở nút vượt ngưỡng cá giò (15 mm / 40 km/h).
  - Độ dốc đáy tính từ GEBCO (~460 m, lớp 0,5 / 1 / 2°) phủ toàn vùng; GEBCO artifact v2. Bãi triều SDB vẽ đường viền mượt (tích chập chuẩn hóa, ngưỡng phủ 0,5) thay cho khối vuông; SDB artifact v7; đường mức bãi triều gộp dưới "Bãi triều chi tiết".
  - Phơi nhiễm sóng gió tắt mặc định, chuyển vào "Phân tích (lý thuyết)".
- **Độ sâu (trả lời):** GEBCO 2024 là mặc định đã đánh giá (decisions #21, RL-45); ETOPO 2022 chỉ để so sánh (hố sâu sai ở Cửa Lục, Vân Đồn); SDB là nguồn thứ ba, chỉ bãi triều. Đường đẳng sâu 2–30 m từ GEBCO bổ sung cho đường mức 0,25–1 m của SDB ở vùng có SDB.
- **Kiểm tra:** test backend 97 đạt (thêm `test_regional_grid.py`, độ dốc GEBCO); `npm run build`; ảnh từng lớp trên Docker; đếm điểm ảnh của canvas hạt (gió ~16 nghìn, sóng ~2,5 nghìn, dòng ~1,5 nghìn).
- **Còn mở:** bản đồ vẫn dùng Open-Meteo `best_match` (không ghim `models=`); dòng chảy / mực nước / sóng nên lấy từ CMEMS (adapter có sẵn, cần quyết định cách cấp thông tin đăng nhập cho container); chưa rõ Open-Meteo đếm lượt theo điểm hay theo request (RL-49).

## RL-51 · 2026-10-24 · Dòng chảy và sóng trên bản đồ lấy từ Copernicus Marine

- **Thiết lập:** worker research-map dùng `cmems_mod_glo_phy_anfc_0.083deg_PT1H-m` (uo, vo bề mặt) và `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i` (VHM0, VMDR, VTPK) trên cả bbox vùng; lưới gốc 1/12° (~9 km), không lọc theo vùng đệm 5 km; file tải về dùng lại 3 giờ (sản phẩm cập nhật theo ngày). Đăng nhập: file của `copernicusmarine login` trên máy gắn chỉ-đọc vào container (`COPERNICUS_CREDENTIALS_PATH`), không chép mật khẩu vào `.env`; không có file thì CMEMS tắt, bản đồ dùng Open-Meteo như cũ.
- **Kết quả (24/10 02 UTC):** dòng chảy 240 điểm, 0,003–0,185 m/s; sóng 225 điểm, Hs 0,05–0,43 m; tải lần đầu ~40 s, lần sau dùng lại 0 s.
- **Giữ Open-Meteo cho mực nước:** `zos` của CMEMS đo so với geoid (~0,93–0,99 m quanh Cát Bà), không cùng mốc với `sea_level_height_msl` (so với mực nước trung bình) của Open-Meteo; đổi nguồn sẽ làm chú giải sai nghĩa. Mưa và gió vẫn từ Open-Meteo.
- **Hạn chế:** CMEMS báo dataset GLO12 "đang cập nhật", dữ liệu sau 23/10 00 UTC có thể chưa đầy đủ; mô hình ~9 km vẫn không thấy dòng siết ở luồng hẹp.

## RL-52 · 2026-10-24 · Bản đồ: vùng tin cậy mặc định, cờ hố sâu GEBCO, tô bóng đáy, đồng bộ dữ liệu, điều hướng 4 mục

- **Cờ "nghi lỗi nguồn / hố sâu" (GEBCO):** quy tắc cũ (giống ETOPO: sâu > 30 m, không nối ra biển mở) gắn cờ 31 cụm / 772 ô. Kiểm tra từng cụm: ~22 cụm ngoài khơi phía nam chỉ sâu 31–34 m cạnh nước ~29 m (đáy nhấp nhô quanh ngưỡng, không phải hố); các cụm trong vịnh sâu 32–55 m cạnh nước 15–23 m, nhiều cụm có ô đo trực tiếp (TID 17) nên nhiều khả năng là rãnh triều thật giữa đảo. Quy tắc mới: chỉ gắn cờ khi sâu hơn vòng xung quanh ≥ 12 m, vòng xung quanh < 25 m và không có ô đo trực tiếp → còn 24 ô. GEBCO artifact v3; thêm test.
- **Bản đồ mặc định:** "Độ tin cậy & trạng thái nuôi" — ô 1 km (H4) tô theo chế độ mặn so với NB1 (cùng chế độ = tin cậy, chuyển tiếp = kém, cửa sông = không đại diện) + quầng 2,5 km quanh mỗi điểm nuôi theo trạng thái khuyến nghị. Dải độ sâu GEBCO tắt mặc định, giữ đường đẳng sâu. Hạn chế: quanh Cát Bà phần lớn ô chưa được tô vì không có trạm quan trắc QN trong 10 km.
- **Độ dốc đáy → tô bóng địa hình đáy:** bóng đổ (hillshade) từ lưới GEBCO, chiều sâu phóng đại ×30 (vịnh đa số dốc < 0,5°), phủ lên các tầng độ sâu; endpoint `/api/v1/bathymetry/gebco/hillshade`.
- **Sóng, dòng chảy:** hạt chạy với tốc độ màn hình ổn định theo hướng (độ lớn thật quá nhỏ nên trước đây gần như đứng yên), vệt dài như gió; thang màu chia mịn ở giá trị nhỏ (sóng < 1 m, dòng < 0,5 m/s).
- **Đồng bộ dữ liệu:** mở trang hoặc bấm "Đồng bộ" gửi `POST /api/v1/refresh`; worker (nơi duy nhất ghi dữ liệu, có quyền Copernicus) thấy yêu cầu trong ≤ 5 s và lấy bản tin ngay; bản tin < 10 phút thì không lấy lại (hạn mức Open-Meteo). Worker vẫn lấy ngay khi khởi động và mỗi 60 phút.
- **Giao diện:** chữ khi rê chuột chỉ còn giá trị (ví dụ "5–10 m"); nguồn và độ tin cậy chuyển vào thẻ khi bấm. Điều hướng còn 4 mục: Bản đồ · Cảnh báo · Phân tích (tab Dự báo / Thời tiết / Phân vùng / Độ tin cậy) · Cấu hình.
- **Kiểm tra:** test backend 104 đạt; `npm run build`; ảnh 1440 và 390 px trên Docker.

## RL-53 · 2026-10-24 · Cảm biến trên bản đồ dừng ở 14/10: nguyên nhân và nạp lịch sử; bản đồ mặc định là vùng HSI + hiện trạng

- **Nguyên nhân:** `research-map/.env` không có `TK_DHTB` / `MK_DHTB`, nên worker Docker chưa từng gọi GreenLab; trạm vẫn phát (bộ thu hằng ngày trên máy đã có tới 23/10). Vì số đo cuối trong Postgres là 14/10 (quá hạn 10 phút), khuyến nghị coi NH3 và nhiệt độ là thiếu → cả 14 điểm "Thiếu dữ liệu".
- **Sửa:** chép tài khoản từ `.env` gốc sang `research-map/.env` (không in ra, không vào git). Worker nạp lịch sử bằng `/Datums/DataByDate` (giờ địa phương +07, decisions #12) từ ngày mới nhất đã lưu tới hôm nay (tối đa 30 ngày, khối 7 ngày) khi khởi động, mỗi 30 phút và khi bấm "Đồng bộ"; vẫn đọc số mới nhất mỗi 60 s. Lần đầu nạp 75.315 bản ghi; số đo mới nhất cách ~25 s; cả 14 điểm "Bình thường" với số đo đủ.
- **Bản đồ mặc định:** vùng HSI lịch sử (nền = phân loại phù hợp, chưa kiểm chứng) có viền đậm theo hiện trạng nuôi lúc này của điểm trong vùng (cảm biến + dự báo mưa, gió 6 giờ); dải độ sâu GEBCO bật lại như trước; lớp độ tin cậy NB1 (H4) chuyển thành tuỳ chọn vì chỉ phủ quanh trạm quan trắc Quảng Ninh.
- **Sóng:** hạt sóng vẽ thành gợn ngắn vuông góc với hướng truyền, trôi chậm (kiểu Windy), gợn dài hơn khi sóng cao.
- **Lưu ý:** pH cảm biến ~6,66 vẫn là trôi đầu dò đã biết (H1 pH drift), không phải nước thật chua.

## RL-54 · 2026-10-24 · H1 chạy lại trên lịch sử đến 24/10 (lockbox 10–24/10)

- **Thiết lập:** `sensor-history-20261024` (204.861 dòng, 29/05 → 24/10, sha256 dad97fd3…); bản tin dựng lại mở rộng tới 24/10 (trùng khớp bản cũ trên phần chồng lấn); ridge; 5 fold × 7 ngày + lockbox 14 ngày; gate #16; cửa sổ lockbox giống nhau giữa các bộ đặc trưng.
- **Nhiệt độ:** đạt gate ở mọi chân trời 15 phút–12 giờ với mọi bộ (B0, B4, B4_nopH, B5, B5_nopH). Skill B5: 14,9 / 18,3 / 23,4 / 33,0 / 41,3 / 46,4 % (RL-08: 13,5…45,5 %); MAE B5 12 h 1,29 °C (persistence 2,40). Thời tiết so với B4: −6,5 % MAE (3 h, p = 0,013), −11,0 % (6 h), −11,5 % (12 h). Bỏ pH làm MAE tăng 1–5,6 % (DM p ≤ 0,008) dù lockbox nằm trọn trong giai đoạn pH trôi → tiêu chí đổi sang nopH của RL-18 không đạt; runtime giữ nguyên. Lag pH trôi tương quan −0,81 với nhiệt độ trong ngày → lợi ích có thể đảo dấu khi hiệu chuẩn lại đầu dò.
- **pH:** trôi nặng hơn RL-13 (trung vị 7,96 → 7,00 sau 19/09, 6,91 trong lockbox; 68 % lockbox ngoài 7,0–8,6; 15/15 ngày SUSPECT; luật tốc độ không bắt được trôi chậm). B0 60 phút "đạt gate" chỉ là quán tính của tín hiệu đầu dò; có QC (`--ph-qc`) chỉ còn 22 % mốc → không đạt. Không có dự báo pH có ý nghĩa khi đầu dò trôi.
- **NH4:** B4 lockbox +22/+18 % nhưng 1/5 fold → không đạt (NH4 nhảy bậc 16/09, lockbox tăng 1,9 → 10,2). **TSS:** thua persistence mọi ô (lockbox gần đứng yên ~3 mg/L).
- **Khuyến nghị:** giữ bundle nhiệt độ có pH làm chính, nopH song song; chuyển nopH khi hiệu chuẩn/thay đầu dò pH; huấn luyện lại cả hai biến thể trên lịch sử 24/10 (chờ chủ dự án); NH4/TSS giữ persistence.
- **Artifact:** `forecast-h1-rerun-20261024-{Temperature,pH,pH-qc,pH-drift,NH4,TSS}/`; `experiments/forecast_gate16_report.py`, `experiments/ph_drift_report.py`.

## RL-55 · 2026-10-24 · H1.5 bảng chấm điểm shadow

- `experiments/shadow_scorecard.py` chỉ đọc sổ `long_*.jsonl`, ghép kết quả bằng `core.forecast_evaluation.long_outcome` (±2 phút, dùng chung với runner). Nhóm B4/B5 × pH/nopH × 180/360/720 phút và theo tuần ISO: MAE, MAE persistence, skill, độ phủ và độ rộng PI80/PI90, chênh lệch cặp pH−nopH; DM chỉ khi ≥ 200 dự báo đã chấm trong ≥ 7 ngày; gate 28 ngày tính bằng số giờ có dự báo / 24. Endpoint `/api/v1/research/forecast/long/scorecard`; khối "Chấm điểm shadow" trên trang H1.
- `HAP-ShadowRunner` bật 24/10 05:18 UTC (live GreenLab, wrapper `scripts/run_shadow_runner.ps1`). 13:04 giờ VN: 84 dự báo, 0 đã chấm (mốc 3 h đầu tiên đến hạn 08:19 UTC) → `insufficient_evidence`.
- **Sự cố đầu tiên:** runner dừng phát 05:28–06:08 UTC vì endpoint "latest" của GreenLab lỗi → rơi về cache cũ → guard chặn (đúng thiết kế), tự hồi phục. Sổ dài cần lịch sử gần: `refresh_recent_history` nạp hôm qua + hôm nay bằng DataByDate mỗi 15 phút vào `live-cache/`. Thời gian một lượt giảm ~40 s → ~2 s nhờ cache phân tích theo file trong `load_cached_history`.
- **Tiếp theo:** chấm điểm hằng ngày; đánh giá ở 7 và 28 ngày (~21/11).

## RL-56 · 2026-10-24 · Nhật ký sự kiện ngoài lồng (ground truth H2.4/H2.5)

- Trang Cấu hình → "Nhật ký sự kiện" (`#/settings/events`); API `/api/v1/events` (POST, GET, `export.csv`). Mỗi sự kiện một file JSON trong `runtime/events/`, tạo độc quyền (không ghi đè); sửa = sự kiện mới có `supersedes`, mỗi sự kiện chỉ bị thay một lần (file khóa `.superseded.claim`). Logic ở `core/field_events.py`; loại sự kiện theo `docs/guide/09-ground-truth-protocol.md`.
- H2.4 cần ≥ 10 sự kiện; hiện 0. Đây là đường ghi thứ hai của API (decisions #25).

## RL-57 · 2026-10-24 · H2.5 xác suất sự kiện nhiệt độ trong 24 h (không cần DO)

- E1 ngày nóng (TB ngày ≥ 31 °C), E2 tăng ≥ 1,5 °C trong 6 h, E3 giảm ≥ 1,5 °C trong 6 h; định nghĩa cố định trong commit 78bba6e trước khi fit. Logistic trên trạng thái sensor / + thời tiết dựng lại / + Platt; lockbox 10–23/10; bootstrap khối 3 ngày.
- E1: `insufficient_evidence` (lockbox 0 ngày nóng; fold trượt thắng khí hậu, không thắng persistence). E2: `insufficient_evidence` (lockbox 55/55 ngày là sự kiện). E3: chỉ thắng khí hậu (BSS 0,44 [0,37; 0,51]), không thắng persistence (−0,25 [−2,92; 0,33]). Thời tiết (kể cả ERA5) không thêm gì so với trạng thái sensor.
- **Cờ dữ liệu:** biên độ ngày–đêm của sensor nhiệt độ tăng ~5 lần từ giữa 08 (0,5–1,2 → 3,7–4,05 °C), lớn hơn biên độ không khí ERA5 (3,0–3,5 °C); đỉnh 11–14 h; tương quan với mực nước giảm 0,5–0,6 → 0,02. Cần hỏi đơn vị vận hành: độ sâu / vị trí / vỏ đầu dò có đổi quanh 15–20/08, hay bị bám bẩn. Ảnh hưởng H1.2, A1 và conformal.
- **Tiếp theo:** ngưỡng tương đối theo chu kỳ ngày–đêm, đặt trước, chạy lại.

## RL-58 · 2026-10-24 · H2.3 độ trễ mưa → cảm biến tại NB1

- ERA5 ghim (`models=era5`) 28/05–18/10; trung vị giờ (≥ 30 phút hợp lệ), loại ngày `sensor_day_health` không OK; tách 2 chế độ quanh bước nhảy 31/07; trừ trung vị trượt 7 ngày, chu kỳ ngày, 5 thành phần triều, mực nước mô hình. Distributed-lag 0–72 h (9 khoảng) + CCF; bootstrap khối 48 h; hoán vị dịch vòng (p nhỏ nhất 0,002); sự kiện ≥ 10 mm/6 h cách nhau 72 h (12 sự kiện, 1 "sạch").
- **Nhiệt độ (đối chứng dương):** giảm 0,08–0,20 °C mỗi 10 mm (tùy sản phẩm mưa), đỉnh trễ 6–11 h, DLM/CCF p = 0,002 → `detectable_effect`; giữ nguyên qua các phân tích độ nhạy.
- **NH4:** không có tác động tuyến tính (p = 0,46) → `insufficient_evidence`; so sánh sự kiện gợi ý tăng +11 % (1–6 h) và +22 % (25–48 h) nhưng sự kiện chồng nhau. **TSS:** p = 0,88, CI quá rộng (+17 %/10 mm ≈ +75 % cho trận lớn nhất) → `insufficient_evidence`.
- **Quy tắc kết luận:** quy tắc gốc (đặt trước) đòi cả cửa sổ sự kiện sạch loại trừ 0 — đối chứng nhiệt độ không đạt vì chỉ có 1 sự kiện sạch; quy tắc sửa (sau lượt debug, ghi rõ) cho phép hai kiểm định toàn cục cùng dấu. Cả hai kết luận nằm trong `dlm_tests.csv`. NH4/TSS bị hạ từ `no_detectable_effect` xuống `insufficient_evidence` vì mô hình tuyến tính không đủ lực với mưa dạng đợt.
- **Phát hiện mới:** NH4 và TSS cùng tụt bậc ~13:30–14:00 ngày 31/07 (NH4 ~106 → 5,3, ÷20; TSS ~70 → 10–15 → 3–4); nhiệt độ, pH không đổi → nhiều khả năng bảo dưỡng / hiệu chuẩn / đổi thang đo; cần hỏi GreenLab. Chưa có trong RL-02/RL-10.
- **Dữ liệu mới:** `data/hazards/era5/openmeteo_era5_precip_nb1_1982_20261018.csv` (write-once); `hazard_data.latest_precip("era5")` giờ trỏ file này. Lệnh ablation cũ trong cùng script vẫn gọi archive không có `models=` (best_match) — mới chỉ ghi chú.

## RL-59 · 2026-10-24 · H2.1 nguồn bản tin thứ hai và độ phủ B5

- Worker research-map thu bản tin NB1 mỗi giờ (cùng định dạng, `capture_source = research_map_worker`) vào `artifacts/experiments/forecast-v2/worker-capture/weather-snapshots-worker.jsonl` (append-only). B5 hợp nhất theo trạm × giờ phát (task Windows ưu tiên, worker lấp chỗ thiếu); `core/b5_coverage.py`; endpoint `/api/v1/research/weather/b5-coverage`; thẻ độ phủ trên trang Thời tiết; `forecast_sensor_v2.py --extra-snapshots`.
- **Số liệu (24/10 06:30 UTC, `b5-coverage-20261024-0630`):** 405 bản tin; độ phủ 7 ngày 50 %, từ đầu 18,8 %; origin B5 đủ điều kiện 28.288/204.005; 15/63 ngày đủ; tốc độ 14 ngày gần nhất 64 % < 90 % → chưa có ngày dự kiến; sớm nhất 09/12/2026 nếu không lỡ thêm ngày nào. 144 bản tin 01/08–26/09 thiếu `provenance_class` nên không được tính (chờ chủ dự án quyết). Sửa lỗi `coverage()` cũ (`frame_missing_station`).
- Wake timers đã bật (RTCWAKE AC/DC) để task mỗi giờ không lỡ khi máy ngủ.

## RL-60 · 2026-10-24 · Bản đồ nhiệt trên bản đồ giám sát

- Hai lớp màu mới trong nhóm "Thời tiết & biển (toàn vùng)", mỗi lúc một lớp như các lớp khác: **Nhiệt độ nước** (SST Open-Meteo marine, chỉ ô có mặt nước) và **Nhiệt độ không khí** (2 m, cả đất liền); cùng lưới 0,125°, cùng nhịp mỗi giờ, không tốn thêm lượt gọi.
- Thang màu cố định: nước chuyển cam ở 31 °C, đỏ ở 33 °C, đỏ sẫm ở 34 °C, đúng các mốc theo dõi / stress / nặng của cá giò (docs/guide/27). Chỉ để quan sát; không đưa vào cảnh báo.
- Kiểm tra 24/10 14:07: SST mô hình 29,3–30,7 °C, cảm biến NB1 30,3 °C (cùng dải); không khí 25,2–32,7 °C.

## RL-61 · 2026-10-24 · Phát lại bão trên trang Cảnh báo; mô hình gió theo đường đi bão; mô phỏng theo độ phơi nhiễm

- **Vấn đề 1 (phát lại bão):** bản phát lại cũ (`hazard-replay-20261024`) dùng gió ERA5 tại ô 0,25°. ERA5 làm mượt lõi bão: tại NB1 chỉ 18,9 m/s (cấp 8) trong khi bão đi qua cách 21 km ở cấp 15 và phá phần lớn lồng bè (RL-31, RL-37). Các trạm phía tây bắc (NB5, NB6, NB16, NB19) rơi vào ô có gió 13,9 m/s (cấp 7), nên phao 21 (NB6) giữa luồng chỉ bậc 1.
- **Sửa:** `hazard_runner_replay.py --wind-source best_track`: gió tại lồng = max(ERA5, gió từ best track IBTrACS tại vị trí lồng — bán kính gió hoặc Rankine biến đổi của `core/storm_advisory.py`), hướng = tiếp tuyến xoáy thuận + 20° hướng vào tâm; cùng bộ chạy, che chắn và sóng như cũ. Vẫn là cận dưới (không có cấp ≥ 12) và best track là oracle → chỉ minh họa logic, không phải kỹ năng dự báo.
- **Kết quả (`hazard-replay-20261024b`):** gió bậc 3 ở cả 14 trạm; sóng: trạm hở 2–4, kín / bán kín 0–1. Ngày bão vào: 5 trạm hở bậc 4 (NB1, NB4, NB5, NB25, NB27), 9 trạm bậc 3; 1 ngày trước: 5 trạm bậc 2, 8 bậc 1, NB3 bậc 0; 3 ngày trước: bậc 0–1. Trạm kín vẫn bậc 3 khi bão vào (gió cấp 10 sau che chắn) — khớp thực tế Yagi phá lồng ở mọi nơi.
- **Giao diện:** trang Cảnh báo có lựa chọn Hiện tại / Phát lại bão và mốc 3, 2, 1 ngày trước / ngày bão vào; nhãn "Dữ liệu phát lại, không phải hiện tại" và chip "Phát lại" trên mọi thẻ, bỏ chip "Mới · x phút", không ghép với theo dõi bão hiện tại; không hiện tên bão. API `/research/hazards/stations?source=replay&days_before=0..3` chỉ đọc run có `yagi_wind_source = best_track`.
- **Vấn đề 2 (mô phỏng trên bản đồ):** kịch bản mô phỏng đổi giá trị theo thứ tự trạm (`i % 3`), nên phao 0 (NB4) ngoài khơi xanh trong kịch bản "Tổng hợp". **Sửa:** gió mô phỏng nhân hệ số theo lớp phơi nhiễm của lồng (hở 1,0 / bán kín 0,7 / kín 0,45, từ `site-exposure`); số đo cảm biến giữ chung (một sensor thật). Kịch bản "Mưa + gió" đổi thành dẫn bởi gió (mưa 12 mm, gió 50 km/h): trạm hở "Cần theo dõi", trạm kín / bán kín "Bình thường". "Tổng hợp" (nước 35 °C, mưa 45 mm) đỏ ở mọi trạm vì mưa và nhiệt phủ cả vùng.
- **Khác:** chip "Mô phỏng" trên thanh trên cùng chỉ hiện ở trang Bản đồ (trang khác không dùng dữ liệu mô phỏng). Test backend 159 đạt.

## RL-62 · 2026-10-24 · H1.4 mô hình nền zero-shot (Chronos-Bolt, TimesFM) so với ridge

- **Thiết lập:** `experiments/foundation_zero_shot.py` (venv riêng `.venv-fm`, torch CPU; không đụng `requirements.txt`). Baseline gọi thẳng `forecast_sensor_v2.run_benchmark` → cùng fold, cùng lockbox 10–24/10, cùng `issued_at` và `actual` với ridge B4 / B4_nopH. Ngữ cảnh kết thúc ở `issued_at − 1 phút` (assert trên 20 mốc ngẫu nhiên). Bước 2 / 5 / 15 phút, ngữ cảnh 2,8–7 ngày; mốc thưa (phút chia hết 15; MAE ridge trên tập thưa khớp tập đủ). Thêm đối chứng không học `diurnal-anomaly-7d` (giá trị cuối + chênh lệch biên dạng ngày trung bình 7 ngày). Gate #16 như cũ.
- **Nhiệt độ (lockbox, MAE °C, bước mốc 15 phút):** ridge B4 0,176 / 0,308 / 0,704 / 1,155 / 1,453 (15 ph / 1 h / 3 h / 6 h / 12 h); Chronos-Bolt base 0,159 / 0,273 / 0,396 / 0,556 / 0,630; TimesFM 2.5 (bước mốc 60 phút) 0,152 / 0,225 / 0,359 / 0,559 / 0,630. Chronos-Bolt base và TimesFM **đạt gate #16 so với ridge B4 và B4_nopH ở mọi khung 15 phút – 12 giờ** (DM p ≤ 0,026); mức cải thiện so với persistence 24 % (15 ph) → 74 % (12 h), so với ridge −10…−26 % ở ≤ 1 h và −44…−57 % ở 3–12 h. Chronos-Bolt small trượt ở 30 / 60 phút.
- **Phần lớn lợi thế đến từ chu kỳ ngày:** đối chứng `diurnal-anomaly-7d` một mình đã thắng ridge 36–41 % ở 3–12 h (đạt gate), chiếm ~70–80 % lợi thế của mô hình nền → ridge đang thiếu đặc trưng chu kỳ ngày nhiều ngày (lag 24 / 48 h, biên dạng 7 ngày). Chronos vẫn thắng đối chứng này thêm 18–27 % ở 6–12 h. Các fold thua ridge (05–19/09) là giai đoạn biên độ ngày–đêm nhỏ; lockbox nằm trong giai đoạn biên độ lớn — đúng giai đoạn RL-57 nghi đầu dò nhiệt bị ảnh hưởng (nắng / vị trí). Nếu chu kỳ lớn là do đầu dò, mô hình đang dự báo tốt **tín hiệu đầu dò**, không chắc là nhiệt độ nước.
- **NH4 (60 / 180 phút):** Chronos-Bolt small đạt gate so với persistence cả hai khung; so với ridge thua ở 60 phút, thắng 38 % ở 180 phút (5/5 fold, p = 5e-5). **pH giai đoạn sạch (trước 19/09):** Chronos small đạt gate so với persistence và ridge ở 60 / 180 phút — mô hình đầu tiên đạt pH 180 phút (RL-18 không có).
- **Chi phí CPU (i7-1185G7, pilot sạch):** Chronos-Bolt small ~0,2 s / mốc (đủ 6 khung), base ~0,84 s, TimesFM ~1,65 s; với 1 mốc / phút là không đáng kể. Chi phí thật là thêm torch + transformers (~1,4 GB) vào môi trường runtime.
- **Hạn chế:** một trạm, một lockbox 14 ngày ở giai đoạn biên độ lớn; chưa đánh giá khoảng tin cậy; TimesFM chỉ chạy nhiệt độ; Chronos base chưa chạy NH4 / pH; chưa thử Chronos-2 có thời tiết / triều.
- **Đề xuất (chủ dự án quyết):** (1) rẻ, làm ngay được: thêm đặc trưng chu kỳ ngày nhiều ngày vào ridge rồi chạy lại; (2) chạy song song Chronos-Bolt (small hoặc base) ở shadow ≥ 4 tuần — cần quyết định đưa torch vào runtime (ghi vào decisions khi chốt); (3) hỏi đơn vị vận hành về đầu dò nhiệt trước khi tin kết quả 3–12 h.
- **Artifact:** `foundation-zero-shot-20261024/` (NOTES.md, `eval-*`, `baseline-*`, `fm-*`); các file `metrics-/dm_tests-/gate16-*-stride15.csv` phẳng là lượt chấm đầu không có đối chứng chu kỳ ngày, được `eval-*/` thay thế.

## RL-63 · 2026-10-25 · Khảo sát dữ liệu giống Cát Bà để học trước rồi tinh chỉnh

- **Câu hỏi:** có bộ dữ liệu nào giống Cát Bà để huấn luyện trước rồi tinh chỉnh trên VN, cho (a) dự báo tần suất cao và (b) mô hình nội suy chéo biến?
- **Phương pháp:** khảo sát web + repo; thang điểm chốt trước (a tối đa 36, b tối đa 33: mùa lạnh, triều, biến, tần suất, độ dài, truy cập, nuôi trồng); mỗi nguồn ≤ 1 truy vấn nhỏ; ghi mức kiểm chứng.
- **(b) nội suy:** HK EPD 97 % (đủ 5 đích + 4 đầu vào cùng mẫu, trung vị tháng 2 17,8 °C, có sẵn trong repo, mở rộng được về 1986), Đài Loan OCA 91 % (265 trạm, 2002→, SS mg/L, NH3_N, PO4), tệp dinh dưỡng NERRS 79 %.
- **(a) dự báo:** không bộ nào > 75 % (IRLON 75, NERRS 72); không bộ mở nào có cùng lúc mùa đông 15–20 °C, triều ≥ 3 m và NH4 liên tục. Mốc phải vượt là Chronos zero-shot (RL-62), không phải ridge. GLORYS12 tại NB1 (1993–2026) là cách rẻ nhất để mô hình nhiệt "thấy" mùa đông.
- **Không mở / bị chặn:** vịnh Bắc Bộ phía Trung Quốc, phao HK EPD, AFCD, Singapore, Thái Lan; Ariake (Nhật, giống nhất về triều và nuôi) bị chặn truy cập.
- **Tài liệu:** học chuyển giao giúp 10–70 % ở sông/hồ khi nguồn giống đích; bằng chứng cho ven biển/lồng nuôi yếu.
- **Artifact:** `docs/eval/2026-10-25-transfer-datasets.md`.

## RL-64 · 2026-10-25 · Sửa dự báo cảm biến +15 phút: ridge B4 có chặn thay XGBoost, TSS persistence

- **Vấn đề:** bundle XGBoost +15 phút (huấn luyện 05–07) không ngoại suy: nhiệt độ dự báo không bao giờ < 29,15 °C; từ tháng 8 thua persistence xa (MAE tháng 10: 0,761 so với 0,205 °C). TSS học chế độ ~70 mg/L trước 31/07 (tháng 10: 3,72 so với 0,24 mg/L).
- **Thiết lập:** `sensor-history-20261024`; `forecast_sensor_v2.run_benchmark` + `forecast_gate16_report` (ridge, 15 phút, B0 / B4 / B4_nopH; Temperature + TSS); backtest theo tháng cùng mốc phát hành (ridge fit lại mỗi tháng trên dữ liệu trước tháng).
- **Kết quả:** nhiệt độ B4 đạt gate #16 (lockbox 0,178 so với 0,208 °C, skill 14,5 %, 5/5 fold, DM p = 4e-154); có chặn 0,179 (1/20.000 mốc rơi về persistence). Theo tháng 07–10, ridge có chặn 0,144 / 0,148 / 0,168 / 0,178 so với persistence 0,181 / 0,183 / 0,201 / 0,205 và XGBoost cũ 0,143 / 0,450 / 0,536 / 0,761. TSS thua persistence ở mọi bộ (0/5 fold).
- **Runtime:** `haiphong_temperature_ridge_B4_quality_15m_v2.pkl` (`hp-temperature-ridge-b4-15m-v2`, 43 đặc trưng B4, fit toàn bộ lịch sử tới 24/10). Chặn cố định trước khi xem lockbox: đầu vào hoặc dự báo ngoài 20,5–34,5 °C ± 1,5 °C, hoặc |dự báo − hiện tại| > 1,5 °C → persistence có nhãn. TSS / pH / NH4: persistence. Sổ ghi có thêm `model_version`; nguồn mới `ridge_b4`. Shadow runner khởi động lại 25/10 sau khi merge.
- **Hạn chế:** một trạm, một lockbox; XGBoost cũ ở 05–07 là trong mẫu; chặn chỉ xét đầu vào nhiệt độ. Biến thể không pH kém hơn ~1 %.
- **Artifact:** `sensor-future-15m-fix-20261025/`; `experiments/sensor_future_15m_fix.py`.

## RL-65 · 2026-10-25 · Dữ liệu công khai Việt Nam cho vùng nuôi Cát Bà – Hạ Long

- **Nguồn đo tại vùng lồng duy nhất:** Viện Nghiên cứu Hải sản (RIMF). Cát Bà 2005–2013 và 2016–2021 (2 đợt/năm, mặt + đáy, nước lớn + ròng); năm 2024 (T5–T11) có 27 bản tin, 7 báo cáo tháng và bộ số liệu; điểm Hang Vẹm – Vụng O cách NB1 2,8 km; chỉ tiêu DO, N-NH4, NO2, NO3, PO4, COD, TSS, Vibrio, Coliform, tảo độc. Không công khai, cần công văn (mẫu trong tài liệu). Sửa mục 9 của eval 24/10 (RL-49).
- **CMEMS ocean colour (đã tải, ~10 MB):** ô 4 km cách NB1 2,3 km có số liệu 31,7 % số ngày (≈ 440 ngày, 2023–10/2026), rất ít vào T2–T4; ô 300 m sát NB1 chỉ 0,7 %; không có SPM 300 m. Phiên bản dataset ngừng 24/11/2026.
- **SPM vệ tinh so với TSS cảm biến:** Spearman 0,13 (n = 54); T6–T7/2026 cảm biến 35–100 mg/L, vệ tinh 1,5–17 g/m³ → thêm một cờ nghi ngờ chất lượng TSS (cùng bước nhảy 31/07, RL-58), chưa kết luận.
- **Không công khai:** trạm tự động nước biển (Quảng Ninh 6, quốc gia 120); RIA1 (chỉ bản tin, > 60 km); bản tin triều NCHMF chỉ có nước lớn/ròng (PDF); UHSLC Hòn Dấu chỉ 1959–1960; không có bộ dữ liệu nghiên cứu mở cho Hạ Long/Cát Bà. Chưa kiểm: data.gov.vn (không truy cập được), cổng mở cấp tỉnh, báo cáo hiện trạng môi trường.
- **Sự kiện ứng viên cho ground truth:** thủy triều đỏ Cát Bà 2011–2012 (5 đợt); cá lờ đờ, lở loét ở vùng nuôi Quảng Ninh T5–T8/2024.
- **Rủi ro:** đơn vị NH3 (tỉnh) / N-NH4 (RIMF, QCVN) / NH4 µg/L (cảm biến) khác nhau; phương pháp phòng thí nghiệm khác điện cực liên tục; tần suất thưa.
- **Artifact:** `docs/eval/2026-10-25-vn-public-data.md`; `scripts/vn_public/`; `paths.VN_PUBLIC_DIR`; `data/vn_public/` (~12 MB, ghi một lần, có manifest).

## RL-66 · 2026-10-25 · H1.9 Ridge + khối ngày–đêm nhiều ngày (B4D/B5D)

- **Câu hỏi:** RL-62 cho thấy ridge thiếu thông tin ngày–đêm nhiều ngày. Thêm khối này thì ridge có đạt gate so với B4 và bắt kịp mô hình nền không?
- **Thiết lập:** khối 11 cột cố định trước khi chạy (`preregistration.json`): y(t+h−24 h), y(t+h−48 h), dị thường biên dạng 7 và 3 ngày, biên độ 24 h, biên độ × dị thường, điều hòa giờ đích, cờ điền thiếu; chỉ đọc dữ liệu trước `issued_at − 1 phút`; luật điền thiếu giữ nguyên origin của B4. Fold, lockbox 10–24/10, gate #16, DM-HLN như RL-54; so với H1.4 trên đúng các origin; thêm phép thử lệch mùa (train trước 01/09, test 15/09–24/10).
- **Nhiệt độ:** B4D đạt gate so với B4 ở 6/6 khung (MAE −8 … −60 %, p ≤ 4e-7) và so với persistence 6/6; MAE lockbox 15 ph / 1 h / 3 h / 6 h / 12 h: 0,164 / 0,231 / 0,421 / 0,586 / 0,579 (B4 0,176 / 0,308 / 0,704 / 1,155 / 1,453); skill 21–76 %. Tỉ số MAE B4D / Chronos-base 0,85–1,06, Chronos không còn đạt gate so với B4D; TimesFM chỉ còn hơn ở 30 phút (−7 %) và 180 phút (−14 %). Thời tiết trên nền khối ngày–đêm (B5D so với B4D): −8,7 % ở 6 h (p = 0,005), không ý nghĩa ở khung khác.
- **Lệch mùa:** biên độ ngày–đêm của tập test phần lớn ngoài dải huấn luyện (trung vị 4,5 so với 2,0 °C), vậy mà B4D vẫn tốt hơn B4 ở mọi khung. Rủi ro đến từ lag pH trôi (bắt đầu 19/09, nằm trong tập test): B4D_nopH tốt nhất (MAE 12 h 0,70 so với persistence 1,89), còn B4D có pH thua đối chứng chu kỳ ngày ở 3–12 h.
- **pH / NH4:** khối ngày–đêm không mang lợi ích thật; Chronos-Bolt small vẫn đạt gate so với B4D (pH −9 / −16 %, NH4 180 ph −39 %).
- **Kết luận:** B4D thay B4 theo luật đặt trước. Đề xuất (chờ chủ dự án): huấn luyện lại bundle nhiệt độ 3–12 h bằng B4D_nopH / B5D_nopH và chạy shadow song song với bundle hiện tại. Runtime chưa đổi.
- **Hạn chế:** một trạm, một lockbox 14 ngày ở giai đoạn biên độ lớn (có thể do đầu dò, RL-57); fold biên độ nhỏ (12–19/09) B4D kém B4 1–3 %; TimesFM chỉ có ở bước mốc 60 phút; phép thử lệch mùa là một lần chia, không có fold.
- **Artifact:** `forecast-h1-diurnal-20261025/`; `experiments/forecast_h1_diurnal.py`; `tests/test_forecast_diurnal.py`.

## RL-67 · 2026-10-25 · H1.8 Học chuyển giao cho mô hình nội suy chéo chỉ số (HK EPD / NERRS → VN)

- **Câu hỏi:** dữ liệu tỉnh ít đợt, thiếu chu kỳ năm. Học trước trên dữ liệu nước ngoài tương tự rồi tinh chỉnh trên VN có tốt hơn mô hình chỉ học từ VN không?
- **Thiết lập:** `experiments/transfer_impute.py`, thiết kế đăng ký trước trong docstring. Đầu vào: nhiệt độ, pH, amoni tổng (TAN), TSS và mùa; đích DO HP/QN, độ mặn QN (chính), PO4 HP, độ trong QN (phụ); độ mặn HP chỉ là proxy GLORYS. Ba kiểu chia: bỏ trạm (trạm GLORYS trùng gộp nhóm), thời gian (thử 2024), mùa (học T5–T10, thử T11–T4). Biến thể: VN-only/runtime, zero-shot HK (và HK + NERRS), gộp có trọng số (`pool_w`, chính), warm-start, stacking, chuẩn hóa theo miền. Luật "có ích": thắng VN-only về MAE ở ≥ 2/3 kiểu chia với CI bootstrap khối trạm-tháng không chứa 0. Công thức `impute.py` tái lập đúng `cv_r2.json`.
- **Kết quả:** 0/5 đích đạt luật. `pool_w` chỉ thắng độ mặn QN khi bỏ trạm (1,203 so với 1,273 psu, CI −0,115…−0,024); ở phép thử mùa thì tệ hơn (độ mặn QN 2,04 so với 1,15 psu; độ trong +1,58 m). Zero-shot HK lệch mạnh (độ trong +1,5 m, độ mặn HP −5 psu). Trọng số VN chạm biên trên (100) ở 66/66 fold. Đường học (10–100 % dữ liệu VN) không có điểm giao: càng ít dữ liệu VN thì chuyển giao càng tệ. Thêm NERRS không đổi kết luận.
- **Ngưỡng:** DO < 5 mg/L có 0 sự kiện trong 1.763 hàng VN (thấp nhất 5,01 QN, 5,6 HP) → không chứng minh được mô hình nội suy báo được DO thấp. Mọi biến thể dự báo độ mặn cao hơn 3–6 psu ở trạm cửa sông QN (< 20 psu).
- **Phát hiện phụ (chưa sửa, cần chủ dự án quyết):** runtime đưa NH3 không phân ly (Emerson, `core/fetch.py` → `pipeline.py` → `impute.py`) vào mô hình học trên cột "NH3" của tỉnh, nhiều khả năng là TAN (ngưỡng QCVN 0,1 mg/L là N-NH4; trung vị HP 0,12 mg/L sẽ gây độc cấp nếu là NH3). Ở pH 8, 28 °C phần không phân ly ~6 % → đầu vào thấp hơn ~15 lần so với lúc huấn luyện. Cần xác nhận tên chỉ tiêu trong báo cáo tỉnh rồi đổi đầu vào sang TAN và huấn luyện lại.
- **Kết luận:** không dùng chuyển giao cho bộ nội suy; nút thắt là lượng thông tin của 4 đầu vào cảm biến và trạm cửa sông, không phải số mẫu VN. Giữ tỷ lệ chỉ số nội suy trong báo cáo, ghi thêm: DO nội suy không báo được DO thấp; độ mặn nội suy chỉ tin ở vùng ≥ 28 psu.
- **Hạn chế:** HP độ mặn / nhiệt độ là GLORYS; phép chia thời gian và mùa giữ cùng trạm hai phía; một họ mô hình (XGB); NERRS là sonde gần đáy 2007–2011, không có amoni / TSS. Điểm "trung thực" (bỏ trạm, loại giá trị vô lý) khác `cv_r2.json`: DO QN −0,54 → 0,34; độ trong QN 0,31 → 0,50; độ mặn HP 0,84 → 0,79.
- **Artifact:** `transfer-impute-20261025b/` (chính), `transfer-impute-20261025c-nerrs/`; `transfer-impute-20261025/` để trống (lần chạy bị dừng khi tắt máy, không dùng).

## RL-68 · 2026-10-25 · H1.7 Học trước trên dữ liệu nước ngoài + tinh chỉnh NB1 cho dự báo

- **Thiết lập:** `experiments/transfer_forecast.py` (thiết kế cố định trong docstring trước khi xem kết quả). Dữ liệu nước ngoài: NERRS SWMP 33 trạm / 8 khu, 2007–2011, 15 phút. Biểu diễn chung: đích Δ so với giá trị cuối, 25 đặc trưng (lag ≤ 12 h, cùng giờ 24 / 48 h, biên dạng 7 ngày, biên độ 24 h, giờ / ngày trong năm). Ba họ (ridge co về trọng số nước ngoài; XGBoost boosting tiếp; MLP ~20k tham số) × ba biến thể (chỉ NB1 / nước ngoài zero-shot / tinh chỉnh); hai tập trạm (tất cả / 8 trạm "giống"); đối chứng XGBoost đích tuyệt đối. A = origin và lockbox RL-62; B = học ≤ 31/08, kiểm tra 15/09–24/10.
- **A (nhiệt độ, pH):** chuyển giao không đạt gate #16 so với mô hình tốt nhất chỉ NB1 ở khung nào. Cái thắng là biểu diễn mới: ridge / MLP chỉ NB1 với đích Δ + đặc trưng ngày–đêm thắng ridge B4 41–58 % ở 3–12 h, ngang Chronos-Bolt base (khớp RL-66). pH: Chronos-Bolt small vẫn tốt nhất.
- **B (lệch mùa):** đối chứng đích tuyệt đối tái hiện lỗi XGBoost runtime (RL-64): MAE 15 phút 0,43 °C, 2,0 °C ở điểm ngoài dải. Đích Δ sửa 34–58 % lỗi đó; dữ liệu nước ngoài giảm thêm ở 3–12 h so với cùng họ chỉ NB1: ridge −9 %, MLP ~−30 %, XGB −13…−38 % (≥ 5/6 khối tuần + DM). Tốt nhất là mô hình nước ngoài zero-shot (MLP 12 h 0,669 °C), ngang Chronos-Bolt base (0,680); tinh chỉnh MLP trên mùa nóng làm kém đi ở 6–12 h.
- **Chọn trạm:** 8 trạm "giống" luôn kém cả 33 trạm → lượng và độ đa dạng dữ liệu quan trọng hơn độ giống khí hậu.
- **Kết luận:** dữ liệu nước ngoài chỉ có ích khi NB1 chưa thấy mùa cần dự báo, và không hơn Chronos zero-shot. Với ridge B4D (RL-66) và Chronos đã có, chuyển giao chỉ là phương án dự phòng không cần torch cho mùa lạnh; chưa đề xuất đưa vào runtime.
- **Hạn chế:** lệch mùa mới là T9–T10 (21–34 °C), chưa phải mùa đông (~18–20 °C); một đầu dò, biên độ ngày–đêm nghi do đầu dò (RL-57); chỉ NERRS (Mỹ), chưa có dữ liệu châu Á, chưa có triều; chưa tinh chỉnh Chronos; TSS và NH4 không đánh giá; mô hình tốt nhất chỉ NB1 được chọn trên cùng fold (lockbox DM là phần sạch).
- **Tiếp theo:** chạy lại phép thử B khi có dữ liệu T11–T12 (mùa lạnh thật).
- **Artifact:** `transfer-forecast-20261025/` (NOTES.md, `evalA-*`, `evalB-Temperature/`, manifest với 164 hash file nước ngoài).

## RL-69 · 2026-10-26 · Sửa cơ sở amoni: TAN cho QCVN / mô hình nội suy / HSI, NH3 không ion cho cảnh báo độc tính

- **Kiểm tra:** file Excel gốc của tỉnh ghi "Amôni (NH4+ tính theo N) (mg/l)" (HP) và "Amoni" theo QCVN 10:2023 (QN) → cột `NH3` trong `clean_data.csv` thực ra là amoni tổng theo N (TAN). Cảm biến NH4 thô × 0,001 = TAN: trung vị 0,107 mg/L trước 31/07 (khớp tỉnh HP 0,094, QN 0,044 → giả định µg/L hợp lý); 0,0039 sau bậc 31/07 14:06 (dưới p1 của HP 0,040 và QN 0,010).
- **Lỗi:** runtime đưa NH3 không ion (Emerson, nhỏ hơn TAN 13–25 lần) vào mô hình nội suy, kiểm tra QCVN 0,1 mg/L, chấm HSI, điểm neo không gian và mô hình ngữ cảnh — tất cả được xây trên TAN. Hệ quả: amoni luôn ngoài miền huấn luyện và QCVN / HSI amoni luôn "đạt".
- **Sửa:** `TAN = raw × NH4_UNIT_SCALE × NH4_TO_N_FACTOR` (mặc định 1,0; đặt 0,7766 nếu nhà cung cấp xác nhận cảm biến báo theo khối lượng ion NH4+); ánh xạ tường minh `AMMONIA_FEATURE_SOURCE = {"NH3": "TAN"}` qua `provincial_basis_row` (không đổi tên đặc trưng trong pickle, không huấn luyện lại; thiếu TAN thì coi là thiếu, không dùng NH3 thay). NH3 không ion chỉ cho cảnh báo độc tính (`alerts`, `forecast_advisory`, `model_alerts`, research-map), nhãn "NH3 không ion (độc tính)". Cờ ngoài miền theo p1–p99 dữ liệu huấn luyện (`core/models/imputer_feature_bounds.json`).
- **Tác động trên lịch sử NB1 (`ammonia-basis-fix-20261026`):** QCVN amoni 0 → 48/64 ngày vượt 0,1 mg/L trước 31/07 (4/64 nếu cơ sở ion 0,7766), 0/85 sau; HSI trung vị trước bậc 0,903 → 0,852, đổi nhãn 58/64 ngày; DO / độ mặn nội suy đổi < 0,1, PO4 0,034 → 0,060; sau bậc không đổi (TAN ngoài miền 100 % dòng, nay có cờ). Không ngày nào chạm mức theo dõi độc tính 0,05 mg/L NH3 không ion.
- **Hạn chế:** cơ sở / đơn vị NH4 chưa được nhà cung cấp xác nhận; bậc 31/07 chưa giải thích; TSS cảm biến ngoài miền HP ở ~93 % dòng nên cờ ngoài miền gần như luôn bật; điểm neo không gian hiện không nhận đầu vào cảm biến (có từ trước).
- **Artifact:** `ammonia-basis-fix-20261026/`; `experiments/ammonia_basis_fix.py`; `tests/test_ammonia_basis.py`.

## RL-70 · 2026-10-26 · Đơn vị / cơ sở kênh NH4 GreenLab: theo N hay ion NH4+?

- **Kiểm tra:** nhãn đơn vị trong dữ liệu xuất của GreenLab, độ phân giải và giá trị trần, so sánh trạm biển với trạm nội đồng, đáp ứng theo pH / nhiệt độ / phần NH3 Emerson / độ mặn CMEMS, so khớp log-normal + bootstrap với amoni tỉnh (NB1/2/25/27, T6–T8, tách triều) và hai bài báo về Cát Bà; ước lượng nhiễu Na+/K+ của điện cực chọn lọc ion (ISE) trong nước biển.
- **Phát hiện:** mọi bản ghi NH4 (313.497, 4 trạm) và màn hình nhà cung cấp đều ghi `mg/L` — quy đổi µg/L ×0,001 là suy luận của repo. Độ phân giải 0,01, trần 500,00 (trạm QN 03 hỏng), trạm biển (~110) cao hơn nội đồng (47–68). Độ dốc theo phần NH3 ≈ 0 (−0,05 / −0,28) → điện cực NH4+, không phải đầu dò khí NH3. Tỉ số hợp lý N/ion khoảng 0,57–1,52 (đã nhân hệ số đổi biến 1,288) tùy tham chiếu: dữ liệu không phân biệt được; riêng trạng thái triều đã làm thang khớp đổi 1,56×, lớn hơn khoảng cách 1,29× giữa hai cơ sở. Theo văn liệu, ISE trong nước biển không có amoni có thể đọc biểu kiến 15–42 mg/L N.
- **Kết luận:** cơ sở NH4-N khả năng trung bình (~60 %, dựa trên thông lệ thiết bị bán cho nuôi trồng). "raw × 0,001 là TAN thật" khả năng thấp–trung bình (~30 %), cạnh tranh với giả thuyết "đúng nhãn mg/L + nhiễu cation nước biển" (giả thuyết này không giải thích được số đọc nội đồng 47–68). Nếu có nhiễu thì TAN thật còn thấp hơn raw × 0,001.
- **Đề xuất (chưa áp dụng):** giữ hệ số 1,0 nhưng hiển thị khoảng ion–N; QCVN amoni chỉ ghi "có thể vượt / không kết luận được / dưới ngưỡng tham khảo", sau 31/07 "không đánh giá". Trước 31/07: 4 ngày có thể vượt, 43 không kết luận, 16 dưới ngưỡng (63 ngày đủ). Không đưa amoni cảm biến vào cảnh báo cho người nuôi. Một cặp mẫu nước tại lồng phân tích TAN phòng thí nghiệm cùng lúc với số đọc cảm biến sẽ giải quyết cả đơn vị, cơ sở và độ lệch nền.
- **Hạn chế:** không có mẫu đối chứng; số liệu tỉnh khác năm, n = 12–36; hệ số chọn lọc ISE là giá trị văn liệu; độ mặn CMEMS không bắt được ngọt hóa ven bờ.
- **Artifact:** `nh4-basis-evidence-20261026/`; `experiments/nh4_basis_evidence.py`; `tests/test_nh4_basis_evidence.py`.

## RL-71 · 2026-10-26 · Bật/tắt cờ "ngoài phạm vi huấn luyện" theo từng chỉ số

- **Vấn đề:** sau RL-69, cờ ngoài phạm vi của mô hình nội suy gần như luôn bật: TSS cảm biến ngoài p1–p99 dữ liệu tỉnh ở ~93 % số dòng, TAN sau bước 31/07 ngoài 100 %. Chủ dự án muốn nút bật/tắt theo loại chỉ số.
- **Làm:** mục `ood_flags` (schema 2) trong alert-config có phiên bản; trang Cấu hình → Ngưỡng cảnh báo có nhóm "Cờ ngoài phạm vi huấn luyện" với một công tắc mỗi chỉ số (dùng lại xem trước, lý do, lưu phiên bản, khôi phục). Mặc định TAN / pH / Nhiệt độ / COD bật, TSS tắt (cơ sở TSS cảm biến khác dữ liệu tỉnh — đang xem xét riêng). Endpoint `GET /api/v1/admin/ood-flags`.
- **Nguyên tắc trung thực:** tắt chỉ đổi phần hiển thị (cờ chung, câu cảnh báo); `ood_features` luôn ghi đủ, kèm `ood_features_muted` và phiên bản cấu hình; cấu hình hỏng thì coi như bật hết. Sổ dự báo shadow nay ghi thêm `inference_diagnostics`. Cổng loại kết quả của mô hình ngữ cảnh DO / độ mặn không phụ thuộc nút này.
- **Không làm:** công tắc theo chỉ số cho các driver khuyến nghị cảm biến (hồ sơ loài nằm trong `core/config.py`, không có chỗ tự nhiên trong alert-config nếu không thiết kế lại).
- **Kiểm tra:** test lõi 901, backend 162, build giao diện, kiểm tra cô lập đều đạt.

## RL-72 · 2026-10-26 · Bước nhảy NH4 / TSS 31/07 tại NB1: do thiết bị, không phải do nước

- **Thiết lập:** `experiments/nh4_step_0731.py` (chỉ đọc). Dữ liệu thô GreenLab 2 bản ghi/phút; `sensor-history-20261024`. Môi trường: ERA5 mưa / gió, mực nước mô hình, CMEMS GLO12 độ mặn / nhiệt, SPM / chlorophyll vệ tinh 4 km, IBTrACS. Nền: amoni tỉnh HP / QN (TAN, RL-69), RIMF 2013 vùng lồng Cát Bà. Đối chứng hai can thiệp khác (12/08, 16/09).
- **Kết quả:** NH4 107,88 → 5,37 trong một mẫu (≤ 30 s) lúc 14:06:00 (÷20); TSS tụt ~1 phút sau (167,7 → 18,9, còn 4–5 lúc 14:15). pH, nhiệt độ, COD không đổi; không mất dữ liệu; chu kỳ 30 phút của thiết bị (:14 / :44) chạy liên tục, bậc nằm ngoài chu kỳ. Không có mưa lớn, gió, bão (gần nhất 801 km), đổi độ mặn (32,5 psu) hay bậc SPM vệ tinh. Hai chế độ lệch nền ngược hướng: NH4 trước bậc 0,104 mg/L (HP 0,093; RIMF 0,089–0,146), sau bậc 0,0048 (< min HP 0,020), giữa T9 còn 0,0003; TSS trước bậc 52,7 (> max HP 32,2), sau bậc 4,3 (QN 5,7; vệ tinh 4–6). NH4 sau bậc vẫn có cấu trúc tương đối (biên độ ngày, tự tương quan) → hệ số mới trên cùng đầu dò. 16/09 15:34: NH4 ×6,7 và COD 0 → 21 cùng một mẫu — cùng kiểu can thiệp; 12/08: gián đoạn 147 phút, COD 558,8 → 0.
- **Kết luận:** thay đổi thiết bị (tin cậy cao, ~90–95 %). NH4 trước bậc gần đúng hơn (~70 %); TSS sau bậc gần đúng hơn (~70 %), TSS ~07/06–31/07 nghi đầu quang bám bẩn. **Với nuôi trồng:** không phải nước sạch hơn hay xấu đi; coi amoni vẫn quanh ~0,1 mg/L N (sát ngưỡng QCVN 0,1, mức cần theo dõi) như trước 31/07 và như số liệu tỉnh / RIMF; độ đục nhiều khả năng vẫn thấp như trước (vệ tinh 4–6 mg/L cả hai giai đoạn).
- **Ảnh hưởng tới kết quả cũ:** phần NH4 của RL-54 / RL-62 / RL-66 là kỹ năng dự báo tín hiệu đầu dò, không phải amoni trong nước; "0/85 ngày sau bậc vượt QCVN" ở RL-69 là hiệu ứng thiết bị; tương quan SPM–TSS 0,13 ở RL-65 cần tính lại chỉ trên dữ liệu sau 31/07 14:15; tăng biên độ nhiệt ngày–đêm (RL-57) nằm sát can thiệp 12/08 (chỉ ghi nhận, chưa kết luận nhân quả).
- **Đề xuất (chờ chủ dự án):** cờ QC `nh4_tss_regime_change_20260731` (NH4 `suspect_scale` từ 31/07 14:06 → coi là thiếu cho QCVN / HSI / nội suy / neo, cảnh báo độc tính từ NH4 sau bậc không mang nghĩa "an toàn"; TSS `suspect_fouling` 07/06–31/07 14:15); cờ can thiệp 12/08 và 16/09; ghi chú cho người dùng; câu hỏi cho nhà cung cấp (hiệu chuẩn, hệ số, loại điện cực, đơn vị, gạt rửa TSS).
- **Hạn chế:** chưa có xác nhận nhà cung cấp; một trạm, không có trạm cùng hãng đối chứng; vệ tinh thiếu 27/07–08/08; nền amoni là mẫu rời của năm khác. Tin công khai duy nhất gần đó: cá chết ở Phù Long cuối T6–đầu T7 (khác thời điểm, > 10 km) — ứng viên ground truth.
- **Artifact:** `nh4-step-0731-20261026/`; `experiments/nh4_step_0731.py`; `tests/test_nh4_step_0731.py`.

## RL-73 · 2026-10-28 · Bài báo 1 / T1: Chronos-2 zero-shot (không biến ngoại sinh) trên origin H1.4

- **Câu hỏi:** Chronos-2 chỉ với chuỗi nhiệt độ có thắng ridge B4D (RL-66) và Chronos-Bolt base (RL-62) không? Tốc độ CPU bản small / base?
- **Thiết lập:** `experiments/paper1_t1_chronos2.py` (nhánh `paper/chronos2-weather`); `preregistration.json` commit trước khi dự báo. `amazon/chronos-2` (base, chính) và `autogluon/chronos-2-small`, revision HF ghim; `.venv-fm` sẵn có `chronos-forecasting` 2.3.2. Ngữ cảnh, bước, kiểm tra không nhìn trước và nội suy y hệt H1.4 → chỉ đổi mô hình. 4.490 origin (stride 15), lockbox 10–24/10; mốc so là dự báo đã lưu (`actual` khớp 100 %). Gate #16; Holm trên 12 kiểm định chính. Lưu thêm phân vị q05–q95 cho T4. Torch 2 luồng.
- **Kết quả (MAE lockbox °C, 15 ph / 1 h / 3 h / 6 h / 12 h):** Chronos-2 base 0,148 / 0,214 / 0,371 / 0,537 / 0,606; small 0,150 / 0,217 / 0,363 / 0,509 / 0,587; B4D 0,163 / 0,232 / 0,421 / 0,583 / 0,582; B5D 0,162 / 0,229 / 0,400 / 0,531 / 0,546; Bolt base 0,159 / 0,273 / 0,396 / 0,556 / 0,630.
  - So với B4D: đạt gate ở 15 / 30 / 60 / 180 phút → "better" theo luật đặt trước; sau Holm chỉ 15 và 30 phút còn ý nghĩa. 6–12 h hòa (12 h tỉ số 1,04).
  - So với Bolt base: thắng 15–60 phút (−7…−22 %, còn ý nghĩa sau Holm), hòa 3–12 h. So với TimesFM (stride 60): hòa 6/6.
  - So với B5D: chỉ thắng 15 / 30 phút; 6 h 1,01, 12 h 1,11 (không ý nghĩa).
  - Small ≈ base (|ΔMAE| ≤ 5 %, không gate) → luật đặt trước chọn **small cho T2**.
  - Tốc độ (2 luồng, batch 64): small 0,23 s / origin, base 0,84 s / origin (đủ 6 chân trời).
- **Kết luận:** Chronos-2 là mô hình nền tốt nhất trên NB1 và vượt ridge ở ≤ 3 h, nhưng không biến ngoại sinh thì không vượt B5D ở 6–12 h. H1 của bài phụ thuộc vào việc T2 thêm thời tiết / triều.
- **Hạn chế:** một trạm, một lockbox ở giai đoạn biên độ lớn (RL-57, RL-72); lockbox đã được mở ở H1.4 / H1.9 và cấu hình kế thừa từ đó; điểm dự báo là trung bình cửa sổ; chưa đánh giá phân vị; chưa có TiRex (giấy phép "other").
- **Artifact:** `paper1-t1-20261028/` (NOTES.md, `preregistration.json`, `fm-*`, `eval-Temperature-stride{15,60}/`, manifest sha256); `tests/test_paper1_t1.py`.

## RL-74 · 2026-10-28 · Bài báo 1 / T2: Chronos-2 + thời tiết as-issued + triều + lịch

- **Câu hỏi:** Thêm thời tiết dự báo as-issued, triều và giờ địa phương làm covariate cho Chronos-2 có vượt ridge B5D ≥ 5 % ở 6–12 h (H1) không? Dự báo dị thường so với chu kỳ 7 ngày hay trực tiếp?
- **Thiết lập:** `experiments/paper1_t2_chronos2_cov.py` (commit 3704b58); `preregistration.json` trước mọi dự báo. Mô hình chính chronos-2-small (luật T1), cấu hình anom-full, stride 15, origin như T1. Thời tiết: 4 biến từ snapshot dựng lại (decision #13), quá khứ không nhìn trước, tương lai = `join_as_issued` (kiểm tra trùng khớp đạt). Triều: fit điều hòa 6 thành phần trên mực nước mô hình Open-Meteo, đóng băng trước 28/08. Lịch: sin/cos giờ địa phương. Ablation (anom, anom-cal, anom-cal-weather, direct-full) và base ở stride 60. Gate #16; Holm trên 12 kiểm định chính.
- **Kết quả (MAE lockbox °C, 15 ph / 1 h / 3 h / 6 h / 12 h):** T2 small anom-full 0,157 / 0,235 / 0,410 / 0,602 / 0,766; T1 small 0,150 / 0,217 / 0,363 / 0,509 / 0,587; B5D 0,162 / 0,229 / 0,400 / 0,531 / 0,546.
  - **H1 không đạt:** tỉ số vs B5D 1,13 (6 h) / 1,40 (12 h; B5D thắng, Holm 0,027). Cùng kết luận vs B5D_nopH.
  - vs T1 small: T1 thắng 15 ph–3 h (Holm ý nghĩa 15–60 ph).
  - Ablation stride 60: chỉ dị thường (không covariate) đã kém T1 10–18 % ở 3–12 h; anom-full kém direct-full 24 % / 40 % ở 6 / 12 h. Lịch, thời tiết, triều mỗi bước |Δ| ≤ 4 % (trừ lịch +12 % ở 12 h), không gate.
  - direct-full (phụ): vs B5D 0,91 / 1,00 ở 6 / 12 h, hòa 6/6; fold trượt không hơn B5D.
  - Base anom-full: tốt hơn small anom-full 1–11 %, vẫn 1,06 / 1,25 vs B5D.
  - Post-hoc: bias lockbox của T2 tăng tới +0,26 °C ở 12 h (T1 ≤ 0,03); PI80 rộng hơn.
  - Tốc độ: small anom-full 1,74 s / origin, base 7,37 s.
- **Kết luận:** H1 bác bỏ. Phép dị thường 7 ngày là nguyên nhân chính làm kém; biến ngoại sinh as-issued gần như không thêm thông tin cho Chronos-2 trên NB1. Dự báo trực tiếp có covariate chỉ ngang B5D. Cần T3 (NERRS nhiều trạm) để biết có phải đặc thù NB1.
- **Hạn chế:** lockbox đã mở (H1.4 / H1.9 / T1); một trạm, giai đoạn biên độ lớn (RL-57, RL-72); triều là fit của chuỗi mô hình, nhật triều trùng pha chu kỳ ngày; chỉ 4 / 7 biến thời tiết; ablation và base chỉ stride 60 (n ≈ 335); direct-full chọn sau khi xem dữ liệu.
- **Artifact:** `paper1-t2-20261028/` (NOTES.md, `preregistration.json`, `fm-*`, `eval-Temperature-stride{15,60}/`, manifest sha256); `tests/test_paper1_t2.py`.

## RL-75 · 2026-10-29 · Bài báo 1 / T3: NERRS nhiều trạm, thời tiết dự báo vs quan trắc

- **Câu hỏi:** Kết quả T2 (Chronos-2 + covariate không vượt ridge B5D) có chung cho nhiều trạm không (T3-H1: Chronos-2 small cal-fc vượt ridge B5D-fc ≥ 5 % ở 6 và 12 h)? Thời tiết dự báo as-issued nắm được bao nhiêu giá trị so với thời tiết quan trắc trạm met (trần trên)?
- **Thiết lập:** `experiments/paper1_t3_nerrs.py` (commit a38c171); `preregistration.json` trước mọi dự báo. CDMO 726235: 8 trạm WQ (Rookery Bay, GTM, Mission-Aransas), train 02/2024–01/2025, test 02–12/2025, 4 origin / ngày, 7.707 origin. NCEI 0052765: 33 trạm, train 2007–2009, test thực tế 2010 (met 2011 không có cờ `<0>`), 11.082 origin. Thời tiết 3 biến (nhiệt độ, gió, mưa; PAR bỏ trước init): dự báo = Open-Meteo Previous Runs theo luật lead as-issued; quan trắc = trạm met NERRS. Chronos-2 small zero-shot, mục tiêu trực tiếp (đăng ký trước, rút từ T2): none / cal / cal-fc / cal-obs / anom-cal-fc. Ridge theo trạm × chân trời: B4D-n, B5D-fc, B5D-obs. Gate-NERRS (≥ 4/5 khối + DM-HLN), Holm 12, CI bootstrap khối ngày. CPU 2 luồng.
- **Kết quả (MAE gộp CDMO °C, 1 h / 3 h / 6 h / 12 h):** Chronos none 0,156 / 0,265 / 0,362 / 0,469; cal-fc 0,162 / 0,275 / 0,375 / 0,477; cal-obs 0,160 / 0,268 / 0,357 / 0,445; ridge B4D-n 0,167 / 0,283 / 0,355 / 0,429; B5D-fc 0,161 / 0,270 / 0,326 / 0,372; B5D-obs 0,162 / 0,269 / 0,318 / 0,348.
  - **T3-H1 không đạt:** cal-fc / B5D-fc 1,15 (6 h) / 1,28 (12 h), ridge thắng gate, Holm p ≈ 0, 0/8 trạm.
  - cal-fc kém Chronos thuần 2–6 % mọi chân trời; lịch một mình cũng kém 2–6 %; dị thường (anom-cal-fc) kém cal-fc 6–9 %.
  - Thang thời tiết: ridge B5D-fc / B4D-n 0,92 / 0,87 (6 / 12 h, gate mọi chân trời, 8/8 trạm), B5D-obs / B4D-n 0,90 / 0,81; dự báo nắm ~79 % / 70 % lợi ích trần (post-hoc). Chronos cal-fc / cal ≈ 1,0 (vô ích), cal-obs / cal 0,96 / 0,93 (gate).
  - Chronos none thắng ridge B4D-n ở 1 h / 3 h (0,94 / 0,93, gate), thua ở 12 h.
  - NCEI: gate đăng ký trước vô hiệu (khối 4–5 nằm trong 2011, trống → mọi cặp "hòa"); DM vẫn nghiêng về ridge ở 6–12 h. Post-hoc (khối trong 2010): ridge B5D-obs thắng cal-obs ở 6 / 12 h (1,05 / 1,15), Chronos none thắng B4D-n ở 1 / 3 h → cùng hướng CDMO.
  - Tốc độ (s / origin): none 0,046, cal-fc 0,405, cal-obs 0,299.
- **Kết luận:** H1 bác bỏ lần hai (NB1 ở T2 → 8 trạm CDMO; H1 dùng thời tiết dự báo nên chỉ kiểm được trên CDMO). 33 trạm NCEI 2010 nhân rộng hướng với thời tiết quan trắc (ridge thắng ở 6–12 h, biên 360 phút chỉ 1,05). NOTES.md kết luận 5 viết "41 trạm" là nói quá; bản này là bản đúng. Mẫu NB1 (Chronos thuần ≈ B5D ở 6 h) không tổng quát: trên NERRS ridge + thời tiết as-issued thắng rõ ở 6–12 h. Thời tiết dự báo có giá trị thật nhưng chỉ khi đưa qua đặc trưng ridge; qua covariate Chronos-2 thì không. Chronos-2 thuần là lựa chọn tốt nhất ở ≤ 3 h.
- **Hạn chế:** gate NCEI đăng ký trước hỏng do cửa sổ khối (sửa post-hoc, code thêm `--block-end` và cảnh báo khối trống); CDMO 3 khu cận nhiệt, 11 tháng; Open-Meteo tại tọa độ trạm met; 3 biến thời tiết; ridge và Chronos nhận thời tiết theo cách khác nhau; chỉ small, không fine-tune; tỉ lệ lợi ích trần không có CI.
- **Artifact:** `paper1-t3-20261029/` (NOTES.md, `preregistration.json`, `weather-fc/`, `data-{cdmo,ncei}/`, `ridge-*`, `fm-*`, `eval-cdmo/`, `eval-ncei/`, `eval-ncei-posthoc-blocks-to-2011-01-01/`, manifest sha256); `tests/test_paper1_t3.py`.
## RL-76 · 2026-10-28 · Bài báo 2 / F1: thư viện chèn sự cố cảm biến hiệu chỉnh trên sự cố thật NB1

- **Câu hỏi:** bộ chèn sự cố (để chấm F2/F3 có đáp án đúng) có tái tạo được biên độ và thời gian của các sự cố thật ở NB1 không?
- **Thiết lập:** `experiments/paper2_faults.py` (nhánh `paper/sensor-faults`). Nguyên hàm `scale_step`, `ramp` (cộng / log-tuyến tính, trần), `fouling` (tăng → bình nguyên → làm sạch có lắng), `stuck`, `gap`; sự cố ghép dạng dữ liệu (`FaultSpec`, `NB1_EVENTS`), nhãn theo kênh, `place_onsets` có hạt giống. "3 sự cố" = ba can thiệp RL-72 (E1 31/07, E2 12/08, E3 16/09), thêm pH 19/09, bám bẩn TSS 30/05→08/06, COD lên trần 06/06. Mỗi sự cố chèn vào đoạn sạch thật cùng biến, đo lại bằng cùng hàm (`detect_level_step` RL-72…); dung sai đặt trước. Ánh xạ NERRS chốt trước F3: đổi thang / kẹt 0 → `DO_mgl`, bám bẩn / trần → `Turb` (trần 1000 NTU giả định), pH → `pH`.
- **Danh mục:** NH4 E1 ÷20,0 trong 1 mẫu; TSS 90 s sau tụt ×40, lắng 7,5 phút (τ 3,9); E2 trống 147 phút, COD kẹt đúng 0,0; E3 NH4 ×8,1 (×6,7 trên 30 s), COD 0 → 21 cùng mẫu, pH +0,22 sớm 2,5 phút; pH 19/09 −1,01 trong 5 h (10–90 %); TSS bẩn ×12,5 trong 5 ngày; COD ×57 lên trần trong 3 ngày.
- **Kết quả:** 16/17 kiểm tra đạt. Trượt: thời gian lắng TSS trên tín hiệu thật 1 phút (trung vị 8 vị trí 11,5 so với 7,5 phút; không nhiễu thì đúng 7,5) — do nhiễu phút của tín hiệu nền, không dùng cho F2/F3. Ba lượt chạy thử sửa lỗi cơ sở đo (tỷ số 30 s / 1 phút, mức lắng, đoạn pH thiếu ngày, trần kiểm duyệt, một vị trí → nhiều vị trí); dung sai không đổi, ghi trong NOTES.
- **Phát hiện phụ:** nhiễu NH4 sau bậc E3 là cộng, không nhân (nhiễu phút tương đối thật 0,010, chèn 0,21) → `scale_step` tạo dấu hiệu nhiễu mà sự cố thật không có, cần lưu ý ở F2. pH 19/09 có bước +0,22 lúc 06:00 trước khi tụt, giống bước pH của E3 → có thể là can thiệp (chưa kiểm).
- **Hạn chế:** mỗi kiểu một quan sát thật, một trạm; chưa mô hình hóa nhiễu sau đổi thang, gai TSS, đảo chu kỳ ngày–đêm pH; kiểm tra COD lên trần dùng chuỗi nền tổng hợp.
- **Artifact:** `paper2-f1-20261028/` (NOTES.md, `nb1_fault_catalog.json`, `reproduction.csv`, `fig_reproduction.png`, manifest); `tests/test_paper2_faults.py` (13 test).
- **Tiếp theo:** F2 — bộ phát hiện đổi chế độ (theo RL-72) + mặt nạ QC, chấm trên sự cố chèn vào NERRS.

## RL-77 · 2026-10-28 · Bài báo 2 / F2: bộ phát hiện đổi chế độ nhân quả + mặt nạ QC, chấm trên sự cố chèn

- **Câu hỏi:** bộ phát hiện chỉ dùng dữ liệu quá khứ bắt các sự cố kiểu NB1 nhanh và chắc đến đâu, với bao nhiêu báo động giả; mặt nạ QC che được bao nhiêu mẫu lỗi?
- **Thiết lập:** `experiments/paper2_detect.py` (đăng ký trong docstring trước lượt chạy). `range` (Turb ≥ 1000 NTU = trần, metadata NERRS), `stuck`, `step` (trung vị 1 h so với 1 h trước, bản nhân quả của RL-72), `drift` (24 h so với nền 7 ngày), `cross` (≥ 2 kênh cùng lúc), `gap`; log cho biến dương. Ngưỡng nhỏ nhất cho ≤ 1 đợt / 30 ngày trên NERRS sạch 2007–08; chấm 1.718 lần chèn (9 loại, tham số F1) trên 2009–11, 33 trạm. Sai lệch sau lượt thử 1: chỉ tính báo động trên kênh bị chèn và ghép mỗi lần chèn với một lần chèn giả → chỉ số chính là phần vượt ngẫu nhiên, CI bootstrap cụm theo trạm. Ánh xạ "kẹt 0" chuyển sang Turb (DO thiếu oxy tự nhiên).
- **Kết quả (vượt ngẫu nhiên [CI 95 %], trễ trung vị):** ÷20 0,78 [0,72; 0,85], 0,25 h; ×8,1 0,83 (trên DO chủ yếu do vượt dải cứng — ở NB1 không có tác dụng này); kẹt 0 0,89, 7,75 h (= k); E1 0,72, 0,25 h; E3 0,53 (chèn giả cao 0,47); pH −1 / 6 h 0,53 [0,42; 0,66], 13 h; bám bẩn 0,56 [0,45; 0,66], 70 h; lên trần 0,72, 37,5 h. Mặt nạ từng mẫu che 57 % mẫu sau đổi thang, thêm điểm đổi chế độ thì ~100 %; sự cố chậm chỉ 38–59 %. Báo động giả năm kiểm tra: 2,5–3,6 đợt / 30 ngày mỗi biến (DO step 1,49 > mục tiêu 1), 5–6,5 % mẫu sạch bị che.
- **NB1 (ngưỡng NERRS):** E1 step 14:15 (9 phút), E3 step 15:45 + cross 16:00, E2 COD-0 sau 8 h, pH 19/09 chỉ drift 23:30 (~13 h, khớp NERRS), COD lên trần chỉ khi chạm trần; bám bẩn TSS đầu 06 không kiểm được (thiếu lịch sử). Ngoài cửa sổ đã biết: 94 đợt / 148,5 ngày (~19 / 30 ngày), chủ yếu TSS và COD.
- **Kết luận:** sự cố đột ngột bắt chắc, nhanh; với đổi thang cần điểm đổi chế độ chứ không chỉ mặt nạ → ủng hộ cơ chế (c) ở F3. Sự cố chậm bắt muộn và không chắc → (d) / (e) phải gánh 0–24 h sau sự cố. Trùng kênh có ích cho E3, yếu cho E1. Ngưỡng NERRS chưa dùng được làm cảnh báo vận hành ở NB1.
- **Hạn chế:** sự cố chèn lý tưởng hóa; NERRS đã qua QC; nhãn bám bẩn tính từ mốc (đánh giá thấp độ che); `cross` không hiệu chỉnh; NB1 một trạm, nhiều sự cố chưa nhãn; 8 cảnh báo numpy "Mean of empty slice" chưa truy ra (không có NaN trong kết quả).
- **Artifact:** `paper2-f2-20261028/` (NOTES.md, `thresholds.json`, `clean_fa_*`, `injections.csv`, `detection_summary.csv`, `nb1_*`); `tests/test_paper2_detect.py` (15 test).
- **Tiếp theo:** F3 — so (a)–(e) trên NERRS với các sự cố chèn này, dùng `flags` / `changepoints` của F2; rồi áp lên NB1.

## RL-78 · 2026-10-30 · Bài báo 2 / F3: cơ chế xử lý khi cảm biến gặp sự cố (a)–(e) trên NERRS chèn lỗi

- **Câu hỏi:** khi cảm biến ven biển có sự cố kiểu NB1, cách nào giữ dự báo và khoảng tin cậy đáng tin nhất: (a) bỏ qua, (b) mặt nạ QC, (c) khởi động lại ngữ cảnh tại điểm đổi chế độ, (d) thích nghi lúc chạy, (e) ACI?
- **Thiết lập:** `experiments/paper2_mechanisms.py` (đăng ký trong docstring trước lượt thử). Chấm theo giá trị sạch; cơ chế chỉ dùng chuỗi quan sát lỗi. Đúng vị trí chèn + chèn giả của F2 (2009–11, 33 trạm, 9 loại). Thêm (c′) căn mức tại điểm đổi (đăng ký trước, dựa RL-72); (d) là proxy (bù sai số trượt mũ), không phải FSNet/TAFAS. Ridge biểu diễn Δ + ngày–đêm của bài 1 (RL-68) trên mọi lần chèn có mô hình (158–196 / loại); Chronos-Bolt small 20 / loại + 4 chèn giả / loại; 2 luồng CPU. Luật: giảm MAE 0–24 h ≥ 30 % (h = 1 h, CI theo lần chèn không chứa 0) ở ≥ 6/8 loại.
- **Kết quả:** **không cơ chế nào đạt** (tốt nhất 4/8: (c′) cả hai mô hình). (c′) sửa được đổi thang: ÷20 −43 % (ridge) / −74 % (Bolt), E1 −56 % / −60 %, hồi phục ≤ 24 h ở 53–100 %, và (c′)+ACI là trường hợp duy nhất đưa PI80 về [0,75; 0,85] (÷20, E1); nhưng trên chèn giả (c′) làm sai số tăng ×2,9–×6,3 (ridge) vì "sửa" các thay đổi tự nhiên và cộng dồn. (b) chỉ giúp khi giá trị lỗi vượt dải (×8,1 trên DO — không chuyển được sang NB1), hại ≤ 11 %. (c) đơn thuần không giúp đổi thang (ridge còn tệ hơn 24–26 %). (d) luôn tệ hơn (−4 … −37 % ở 1 h, tới −80 % ở 6 h) vì học theo đầu dò hỏng. Sự cố chậm không cơ chế nào cứu trong 0–24 h; sau 1–3 ngày mặt nạ giảm 31–90 % sai số 1–7 ngày. ACI phản hồi từ chuỗi lỗi không sửa được độ phủ so với nước thật.
- **NB1 (không có đáp án):** (c′) đưa dự báo NH4 về đúng mức trước bậc ở E1 (0,94×) và E3 (1,03×); các cơ chế khác bám mức sau bậc; pH 19/09 không có điểm đổi bước nhảy nên mọi cơ chế như nhau.
- **Sai lệch ghi rõ:** tìm lại vị trí điểm đổi (test đơn vị, trước chấm); ACI viết lại cho nhanh (cùng logic); NB1 dùng cửa sổ 40 ngày như NERRS; định nghĩa hồi phục đăng ký trước hỏng với sự cố chậm → chỉ báo cáo cho sự cố đột ngột.
- **Kết luận:** chưa có cơ chế tự động an toàn. Mặc định nên dùng (b) (rẻ, ít hại); căn mức chỉ khi có xác nhận can thiệp thiết bị (dấu hiệu trùng kênh, nhật ký bảo dưỡng). Bản (c′) có giới hạn (chỉ điểm đổi gần nhất / có xác nhận) cần đăng ký và chạy riêng.
- **Hạn chế:** sự cố chèn lý tưởng hóa; NERRS đã QC; Bolt mẫu nhỏ; (d) là proxy; không chạy Chronos-2; NB1 không có đáp án.
- **Artifact:** `paper2-f3-20261029/` (NOTES.md, `results_ridge.csv`, `results_bolt.csv`, `summary.csv`, `verdict.csv`, `nb1_*`); `tests/test_paper2_mechanisms.py` (6 test).

## RL-79 · 2026-10-30 · Bài báo 2 / F4: căn mức có giới hạn tại điểm đổi chế độ

- **Câu hỏi:** một bản (c′) có giới hạn có giữ được lợi ích với đổi thang thiết bị (F3: ÷20 −43…−74 %) mà hại trên dữ liệu không sự cố ≤ 10 % không?
- **Thiết lập:** `experiments/paper2_bounded_align.py`, đăng ký trước (docstring + `preregistration.json`, commit `7281100` trước mọi lượt chấm). Gốc (a); điều kiện bật: (i) ≥ 80 % độ dịch trong ≤ 2 mẫu, (iii) tỷ số ≥ ×3 (chỉ biến log), (ii) nhiệt độ < 0,5 °C / độ mặn < 2 psu không đổi; chỉ điểm đổi gần nhất. v1 = (i)+(iii), v2 = + (ii), v3 = v2 giảm dần (bán rã 72 h). Ridge (F3), Chronos-Bolt small, Chronos-2 small; chèn sự cố / chèn giả F2 (NCEI 2009–11) + chèn giả CDMO 2021–25 (ngẫu nhiên và **tại điểm đổi tự nhiên**). Chọn biến thể trên nửa trạm hiệu chỉnh (crc32), chấm cổng trên nửa giữ lại: G1 ≥ 30 % ở 4 loại đổi thang (CI khối trạm > 0), G2 hại chèn giả ≤ 10 % (F2 xấu nhất, cdmo_random, cdmo_event), G3 không tệ hơn (b) quá 10 % ở loại khác.
- **Kết quả:** **không đạt.** Không biến thể nào đủ điều kiện hại (hiệu chỉnh: v1 0,90; v2 0,63; v3 0,29) → chọn v3; trên trạm giữ lại v3 trượt G2 ở cả 3 mô hình (F2 xấu nhất 0,21–0,22; cdmo_event 0,13–0,22) và G3 ở Bolt / Chronos-2. G1 đạt rộng: ÷20 v1 0,77 / 0,92 / 0,94 (ridge / Bolt / Chronos-2), E1 0,81 / 0,88 / 0,89; v3 0,60–0,70. Đổi thang thật bị bắt trong 24 h ở 92 % (v1) / 83 % (v2). So với (c′) F3: lợi ích ridge ÷20 0,43 → 0,77, hại giảm 4–10 lần nhưng chưa đủ: 13–17 % cửa sổ chèn giả có lần bật giả, mỗi lần làm lệch mức ≥ ×3. Lần bật giả chủ yếu do Turb tự nhiên nhảy ×3 trong ≤ 2 mẫu và DO gần 0; nhiệt độ / độ mặn chỉ loại ~1/4 lần bật giả và chặn ~1/10 đổi thang thật. CDMO: v2 bật 0,08 (DO) / 0,48 (Turb) lần / 30 ngày (bỏ Jobos 0,06–0,07). v3 cắt hại nhưng mất lợi ích 1–7 ngày (÷20 / E1 còn 0,20–0,22). PI80 (ACI, từ 24 h): chỉ ridge v2 vào [0,75; 0,85] ở ÷20 / E1.
- **NB1 (mô tả):** ba điều kiện nhận đúng E1 NH4 (dự báo 0,96–0,97 × mức trước bậc) và E3 NH4 (1,12–1,16×) với cả Bolt và Chronos-2; E2 COD không bật (trống chặn); nhưng **bật nhầm** ở E3 COD 0 → 21 (thoát khỏi kẹt 0) và kéo dự báo về 0.
- **Kết luận:** chưa có căn mức tự động an toàn, kể cả có giới hạn. Dùng ba điều kiện làm **gợi ý** cho người vận hành xác nhận (nhật ký bảo dưỡng / nhà cung cấp), chỉ căn mức sau khi xác nhận; loại riêng trường hợp thoát khỏi kẹt.
- **Hạn chế:** sự cố chèn lý tưởng hóa; FM ~14–15 vị trí giữ lại / loại; ngưỡng đặt trước, không quét (tổ hợp khác phải đăng ký lại); hại FM dựa trên tính chất "không bật = (a)" (đã kiểm bằng ridge); NB1 không có đáp án, chỉ có nhiệt độ làm tham chiếu.
- **Sai lệch:** điều kiện (i) sửa sau chạy thử 1 trạm **trước** commit đăng ký (xét bước nhảy trong ±W mẫu quanh điểm đổi định vị lại); chuỗi chạy bị giới hạn 2 h cắt giữa bước Bolt, đã chạy lại tách riêng, mã không đổi.
- **Artifact:** `paper2-f4-20261030/` (NOTES.md, `preregistration.json`, `results_{ridge,bolt,chronos2}.csv`, `results_cdmo_*.csv`, `triggers_nerrs.csv`, `cdmo_*`, `summary.csv`, `selection.json`, `verdict.csv`, `nb1_*`, manifest); `tests/test_paper2_bounded_align.py` (11 test).

## RL-80 · 2026-11-02 · Bài báo 2: rà soát đăng ký trước F1–F4 và các câu cần sửa trước khi viết

- **Câu hỏi:** bước nào trong F1–F4 kiểm chứng được là đăng ký trước, và những câu nào trong RL-76..79 không được đưa nguyên vào bài?
- **Mốc thời gian (giờ +07, tự kiểm từ `manifest.json` và `git log`; ngày tác giả = ngày commit):**
  - F1: manifest 28/10 02:27:33; commit `5ed743f` 02:29:09; manifest ghi `git_head` `3881ca4` (commit tài liệu). `paper2_faults.py` lần đầu vào git ở `5ed743f`.
  - F2: manifest 28/10 08:54:10 (`thresholds.json` 08:43, `clean_fa_*` 08:44); commit `fbe7966` 09:00:53; `git_head` `5ed743f`. `paper2_detect.py` lần đầu vào git ở `fbe7966`.
  - F3: manifest 30/10 02:03:27 (`results_ridge.csv` đã có từ 00:25); commit `72c61a4` 02:10:34; `git_head` `fbe7966`. `paper2_mechanisms.py` lần đầu vào git ở `72c61a4`; NOTES F3 tự ghi lúc chạy chưa commit.
  - F4: commit `7281100` 30/10 08:37:44 (mã + test); `preregistration.json` 08:37:49, `git_head` `7281100`; kết quả đầu (`results_ridge.csv`) 09:17; cả 5 manifest con ghi `7281100`; `git diff 7281100 d0d5c82` trên script và test rỗng (`d0d5c82` chỉ sửa AGENTS, research-log, RESULTS).
- **Kết luận về đăng ký:** F1–F3 là **khám phá**, trong bài **không được gọi "pre-registered"**. Docstring của ba bước có ghi "PRE-REGISTRATION" và NOTES / RL-78 ghi "đăng ký trước", nhưng mã chỉ vào git sau khi có kết quả, nên không kiểm chứng được; không suy ra gì về ý định. **F4 là kiểm định xác nhận duy nhất.**
- **Chi tiết bổ sung so với nhận định ban đầu:**
  - `HANDOFF-paper2.md` mục "Thiết kế (đăng ký trước)" vào git ở `c426029` (28/10 01:27:59), **trước** F1: có câu hỏi, loại sự cố, chỉ số, luật ≥ 30 % ở ≥ 2/3 loại. Phần khung này kiểm chứng được; ánh xạ biến, ngưỡng, ngưỡng 6/8 và định nghĩa cụ thể thì không. Vẫn xếp F1–F3 là khám phá.
  - Giới hạn của F4: (1) mọi timestamp chỉ là git cục bộ, commit chưa lên remote (`git branch -a --contains 7281100` không có nhánh remote), nên không có mốc của bên thứ ba; (2) giả thuyết sinh từ F3 trên chính các vị trí chèn NCEI, cả nửa trạm "giữ lại" cũng đã góp vào số tổng hợp F3 — phần dữ liệu mới là chèn giả CDMO 2021–25 (CDMO 2024–25 đã dùng ở T3, RL-75, cho mục đích khác); (3) điều kiện (i) đã sửa sau chạy thử 1 trạm `job09` trước commit (RL-79 đã ghi). Khi viết nên nói "đăng ký trước, kiểm chứng trong git cục bộ", không ngụ ý dữ liệu hoàn toàn độc lập.
- **(b) "ít hại" phải xem lại:** F3 đặt cờ hại > 5 % trên chèn giả; (b) vượt ở cả hai mô hình: ridge 10,6 % (`verdict.csv`; xấu nhất ở chèn giả `scale_down`, n = 166, CI 5,7–15,9 %; 4/9 loại > 5 %, tuy `scale_up` chỉ 5,01 %), Bolt 14,8 % (chèn giả `rail`, **n = 4**, CI chứa 0, chỉ tham khảo). Câu "hại ≤ 11 %" trong RL-78 không tính Bolt; "(rẻ, ít hại)" và "gần như vô hại" trong NOTES mâu thuẫn với chính cờ này. Trong bài: nêu số và cờ, không viết "ít hại". F4 không dựa vào điều này: docstring F4 đã dùng (a) làm gốc vì (b) tốn +10,6 / +15 %.
- **(d) chỉ là proxy:** docstring F3 ghi rõ "(a) + trung bình mũ của sai số, bán rã 6 h, không phải FSNet / TAFAS". Số trong RL-78 đúng cho proxy (1 h: ridge −4,3…−29 %, Bolt −5,4…−37 %, bỏ loại `gap`; 6 h tới −80 %, ridge `ph_ramp`), và đó là chấm theo nước thật trong cửa sổ có sự cố, kiểu kết quả đã dự đoán trước trong docstring. "Thích nghi luôn tệ hơn" **không tổng quát** cho FSNet / TAFAS (chưa chạy). Ngay với proxy, "luôn" cũng quá rộng: ridge `gap` +0,0 % (CI chứa 0), trên chèn giả ridge (d) hại xấu nhất chỉ 0,26 % (không gắn cờ) và ở vài loại giảm sai số tới 4,8 %; Bolt (d) có cờ 20,8 % (n = 4). Câu viết được: "proxy bù sai số này tệ hơn (a) ở mọi loại sự cố có đổi giá trị".
- **Luật 6/8 không phải 8 phép thử độc lập:** E1 ≈ ÷20 và E3 ≈ ×8,1 vì sự cố ghép chấm trên cùng `DO_mgl` với cùng bậc (`NH4` E1 ÷20,013, E3 ×8,1 → DO). Giảm MAE gần nhau ở `summary.csv` (ridge (c′): ÷20 0,43 / E1 0,56; ×8,1 0,89 / E3 0,89; ridge (b) ×8,1 / E3: 0,97 / 0,97), và trong `verdict.csv` mỗi cặp luôn đạt hoặc trượt cùng nhau. Thực chất 6 loại, trong đó 2 loại tính đôi. Với cơ chế sửa đổi thang, chỉ cần thêm 2 loại khác là đạt "6/8".
- **×8,1 vượt dải cứng trên DO:** DO sau ×8,1 khoảng 50 mg/L (NOTES F3), vượt `RANGE` (0; 25) của F2. `det_range` 0,96 (×8,1), 0,98 (E3), so với 0,00 (÷20), 0,04 (E1); MAE 0–24 h trung vị của (a) 36–47 so với nền khoảng 0,22. Vì vậy (b) giảm 97–99 % ở hai loại này chủ yếu nhờ dải cứng, và không chuyển được sang NB1 (NH4 0,36 → 2,9 không vượt dải nào; RL-77, RL-78 đã nêu). (b) đạt "2/8" chính là cặp này. Bỏ cặp này thì (b) không đạt loại nào.
- **Mỗi loại sự cố gắn một biến** (`injections.csv`): `scale_down`, `scale_up`, `E1`, `E3`, `gap` → DO; `stuck0`, `fouling`, `rail` → Turb; `ph_ramp` → pH. Cơ chế × loại sự cố lẫn với biến: không phân biệt được "cơ chế kém với bám bẩn" và "cơ chế kém với Turb". E1 / E3 có kênh phụ nhưng chấm trên DO. Không biến nào là NH4; NERRS không có NH4 liên tục, nên F4 trượt do Turb tự nhiên và DO gần 0 chưa nói được hại trên NH4.
- **Không đổi:** RL-76..79 và artifact giữ nguyên; kết luận "không cơ chế nào đạt" và "F4 trượt cổng" không đổi hướng. Đây là sửa cách diễn đạt và phạm vi.
- **Tiếp theo:** nguồn NH4 liên tục cho F5: `docs/paper/2026-11-02-nh4-continuous-candidates.md`.

## RL-81 · 2026-11-02 · Bài báo 1 / T4: conformal hóa phân vị Chronos-2 theo chế độ biên độ (H3)

- **Câu hỏi:** PI80 của Chronos-2 sau conformal (aci_amp, RL-19) có trong [0,75; 0,85] ở từng chế độ biên độ, với Winkler không kém ridge + aci_amp quá 5 % không?
- **Thiết lập:** `experiments/paper1_t4_conformal.py`, `experiments/paper1_t4_preregistration.json` (commit 4729634, trước mọi phép tính độ phủ). Phân vị đã lưu T1 (NB1, small; phụ base) và T3 (CDMO `none`), không dự báo lại. Điểm CQR từ q10/q90; raw, tĩnh, ACI có trễ, aci_amp qua `core.forecast_intervals`; mốc ridge B5D / B5D-fc cùng origin. **Định nghĩa H3 chốt:** độ phủ + `frac_infinite` ≤ 0,01 + Winkler ≤ 1,05 ở mọi ô (của plan, chứa của handoff, vì độ phủ đơn thuần mua được bằng khoảng rộng); đọc theo handoff báo riêng. γ = 0,075 / trễ phản hồi theo origin (trùng RL-19 ở bước 1 phút); γ nguyên văn là độ nhạy. NB1: hiệu chuẩn fold 3–5, lockbox 10–24/10. CDMO: hiệu chuẩn tới 01/05/2025; chế độ = A(t) so với trung vị năm train của trạm; đơn vị quyết định là khu (3), không phải trạm (8).
- **Kiểm tra chế độ:** origin T1 từ 04/09, A(t) 1,35–7,2 °C → chế độ nhỏ NB1 có 0 hàng; **H3 không kiểm đầy đủ được trên NB1**. Chế độ CDMO là phân chia nhẹ, không tương đương ×5 của NB1.
- **Kết quả:** **H3 bị bác.** NB1 chế độ lớn 6/6 ô: độ phủ 0,800 / 0,800 / 0,799 / 0,792 / 0,772 / 0,787 (15 ph–12 h; raw 0,64–0,78), tỉ số Winkler 0,81–0,98, ngày tệ nhất 0,48–0,78; CI độ phủ 6–12 h rộng (0,70–0,87). CDMO 23/36 ô, 0/3 khu đủ: độ phủ 33/36 (3 ô trượt sát biên), Winkler 25/36; ≤ 3 h 21/24, 6–12 h 2/12 (tỉ số tới 1,40). Theo handoff (chỉ độ phủ) CDMO vẫn trượt 3 ô.
- **Post-hoc:** aci_amp làm lệch độ phủ giữa hai chế độ CDMO rõ hơn ACI thường ở 3–12 h (Chronos 0,76 / 0,84 so với 0,78 / 0,82; ridge 0,73 / 0,87 so với 0,81 / 0,79), không lặp lại ưu thế RL-19. Ridge + ACI có Winkler thấp hơn ridge + aci_amp, nên mốc đăng ký dễ hơn mốc tốt nhất (NB1 12 h Chronos kém B5D + ACI 13 %).
- **Kết luận:** conformal sửa được độ phủ phân vị gốc của Chronos-2. Ở ≤ 3 h khoảng này cạnh tranh được với ridge; ở 6–12 h ridge + thời tiết vẫn tốt hơn về Winkler trên CDMO, cùng hướng T3. Chưa có bằng chứng cho chế độ nhỏ ở NB1.
- **Hạn chế:** lockbox NB1 đã mở, 14 ngày, nghi đầu dò (RL-57, RL-72); CDMO 3 khu, mar 1 trạm, hiệu chuẩn lệch mùa; luật γ mới; Chronos không thời tiết so với ridge có thời tiết; NCEI không chạy.
- **Sai lệch:** mô tả trung vị train trong bản đăng ký 1,10–2,50, code tính 1,10–2,55 °C; luật không đổi.
- **Sai lệch (thêm khi merge):** lockbox NB1 có `actual_at` rỗng toàn bộ, nên `known_at` (trễ phản hồi ACI) thực chất bằng `valid_at`; chưa chạy lại để đo ảnh hưởng. NOTES / RESULTS của lần chạy dùng số tạm "RL-T4" = RL-81.
- **Artifact:** `paper1-t4-20261102/` (NOTES.md, `preregistration.json`, `verdict.json`, `h3_cells_*`, `metrics_*`, `sensitivity.csv`, `daily_*`, `weekly_cdmo.csv`, `worst_period.csv`, `intervals-*.parquet`, manifest); `tests/test_paper1_t4.py` (22 test).

## RL-82 · 2026-11-02 · Đính chính câu "Chronos thuần tốt nhất ≤ 3 h" của RL-75

- **Đính chính:** câu này của RL-75 chỉ kiểm với B4D-n, không đúng khi so với ridge B5D-fc. Mục RL-75 giữ nguyên, mục này thay thế câu đó.
- **Kiểm tra (phân tích lại dự báo T3 đã lưu, tỉ số đã biết trước, không phải giả thuyết mới):** gate-NERRS `none` vs `ridge-B5D-fc`, 8 trạm, Holm 6. Tỉ số MAE 15 ph / 30 ph / 1 h / 3 h / 6 h / 12 h: 1,147 (ridge thắng) / 1,023 (hòa) / 0,967 (none thắng) / 0,982 (hòa) / 1,110 (ridge thắng) / 1,259 (ridge thắng). Thắng ở 1 h gần như chỉ do GTM: 0,905, so với Mission-Aransas 1,004 và Rookery 1,014; 4/8 trạm. Chronos kém persistence ở 15 ph (1,106; không đạt gate theo chiều nào).
- **Trên trạm mới (RL-83):** none / B5D-fc 1,25 / 1,10 / 1,04 / 1,04, ridge thắng gate ở 15 ph–1 h, 3 h hòa theo luật mức khu.
- **Câu đúng:** Chronos thuần thắng ridge không thời tiết ở 1–3 h trên 8 trạm T3, nhưng không tốt hơn ridge có thời tiết as-issued ở ≤ 3 h, và ở 15 ph kém cả persistence.
- **Artifact:** `paper1-t4b-20261102/t3-correction/gate_none.csv`.

## RL-83 · 2026-11-02 · Bài báo 1 / T4b: lai Chronos-2 + ridge cùng đặc trưng thời tiết, xác nhận trên trạm chưa dùng

- **Câu hỏi:** Kết luận T3 có bị lẫn cách mã hóa thời tiết không? Lai Chronos none với ridge B5D-fc có vượt cả hai trên trạm chưa dùng không?
- **Thiết lập:** `experiments/paper1_t4b_hybrid.py` (commit 3ad298b), đăng ký trước commit 501ddfe. Xác nhận: CDMO 184841, 12 trạm / 3 khu (Apalachicola, Sapelo, Jobos), train 02/2024–01/2025, test 02–12/2025, 13.639 origin; bước 0 chỉ xem độ phủ. Phát triển: 8 trạm T3, chỉ khám phá. Nhánh: resid-none, stack-B5D, avg, switch-180. Chronos năm train nhân quả, 672 bước, origin mỗi 3 h; nhánh có học so với ridge cùng tập origin. Gate-NERRS, Holm 42, CI bootstrap, luật mức khu khai báo trước (tỉ số < 1 ở 3/3 khu, CI < 1 ở ≥ 2/3), Wilcoxon / dấu theo trạm làm phụ. Dev tái lập T3 với sai lệch ridge 0,0.
- **Kết quả (MAE gộp conf °C, 15 ph / 30 ph / 1 h / 3 h / 6 h / 12 h):** persistence 0,062 / 0,110 / 0,193 / 0,452 / 0,696 / 0,868; none 0,074 / 0,099 / 0,144 / 0,263 / 0,369 / 0,477; B5D-fc 0,060 / 0,090 / 0,138 / 0,253 / 0,327 / 0,373; stack-B5D 0,059 / 0,088 / 0,134 / 0,242 / 0,319 / 0,369; avg 0,062 / 0,089 / 0,134 / 0,242 / 0,322 / 0,390; resid-none 0,074 / 0,098 / 0,143 / 0,257 / 0,359 / 0,441.
  - **stack-B5D: supported**, thắng cả hai ở 30 ph–12 h, 15 ph hòa. Tỉ số với ridge cùng tập origin 0,992 / 0,976 / 0,964 / 0,952 / 0,974 / 0,989. So với ridge công thức T3 (phụ), 12 h hòa.
  - **avg: partial**, thắng cả hai chỉ ở 1 h và 3 h (0,970 / 0,955); 6 h hòa, 12 h 1,046. Mẫu "tốt hơn cả hai" thấy ở dev không lặp lại ở 6 h.
  - **switch-180: không có giá trị riêng**, thua ridge ở 15 ph–1 h, hòa 3 h; thắng ở 6 / 12 h chỉ là ridge thắng none.
  - **resid-none: not_supported**, thua ridge 1,10 / 1,18 ở 6 / 12 h, 0/12 trạm. Theo luật: lợi thế ridge còn nguyên khi cùng đặc trưng thời tiết.
- **Kết luận:** Dùng dự báo Chronos làm đặc trưng cho ridge có lợi thật và nhất quán, nhưng chỉ 1–5 %, ở 12 h khoảng 1 %. Mức cải thiện ở trạm mới chỉ bằng khoảng nửa ở dev. Khoảng cách 6–12 h của T3 không chỉ do cách mã hóa thời tiết. Chưa đề xuất đưa vào runtime.
- **Hạn chế:** 3 khu nên luật mức khu chỉ là mô tả; trạm trong khu không độc lập; cùng năm 2025 với dev, CDMO 2025 tạm thời; Jobos thưa (job19, job10 trống ở một số khối); resid-none không có lag nên không tách được cách mã hóa với học theo trạm; dữ liệu huấn luyện của Chronos-2 ngoài tầm kiểm soát; chưa đánh giá phân vị.
- **Số RL:** NOTES của lần chạy dùng số tạm "RL-T4b" = RL-83 (đính chính = RL-82); đánh số khi merge.
- **Artifact:** `paper1-t4b-20261102/` (NOTES.md, `preregistration.json`, `step0_coverage.json`, `eval-{dev,conf}/`, `t3-correction/`, manifest sha256); `tests/test_paper1_t4b.py`.
