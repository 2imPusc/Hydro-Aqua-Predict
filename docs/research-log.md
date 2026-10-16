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
