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
