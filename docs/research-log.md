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

