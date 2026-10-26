# Cảnh báo rủi ro nuôi cá giò

`core/alerts.py` tách chỉ số rủi ro nuôi trồng khỏi suitability/WQI. Engine hiện
dùng các rule provisional cho DO, nhiệt độ và NH3; đánh giá mức tức thời, tốc độ
giảm DO trong 15 phút và tổ hợp DO + nhiệt độ.

`core/sensor_health.py` chạy trước policy cảnh báo. Nó phát hiện reading thiếu,
ngoài dải vật lý, sensor kẹt (flatline), spike Hampel causal và level shift
CUSUM. Dữ liệu `suspect` hoặc `invalid` không được dùng để nâng cấp severity.

## Giới hạn an toàn

- `EMERGENCY` chỉ có thể phát từ số đo DO trực tiếp, QC hợp lệ.
- DO nội suy hoặc forecast không được dùng làm bằng chứng duy nhất để phát
  cảnh báo khẩn cấp.
- Profile `cobia-v1-provisional` phải được hiệu chỉnh cùng người vận hành trước
  khi kết nối SMS/Zalo/email.

## Payload

`run_pipeline()` trả thêm `aquaculture_alert` gồm `risk_score`, `severity`,
`confidence`, `drivers`, `sensor_health` và `recommended_actions`.

Dashboard giữ lifecycle `OPEN → RESOLVING → RESOLVED` trong session hiện tại;
chưa lưu event qua lần khởi động lại app. Notification và mô hình xác suất sự
kiện chỉ được bổ sung sau khi có DO sensor trực tiếp và tập lịch sử đủ để hiệu
chỉnh/đánh giá theo thời gian.

## Cờ ngoài phạm vi huấn luyện — bật/tắt theo chỉ số (2026-10-26)

Bộ nội suy (`core/impute.py`) gắn cờ khi input cảm biến nằm ngoài p1–p99 của dữ liệu
tỉnh (`core/models/imputer_feature_bounds.json`). Admin bật/tắt cờ theo chỉ số ở
**Cấu hình → Ngưỡng cảnh báo → "Cờ ngoài phạm vi huấn luyện"**; lưu như mọi thay đổi
khác thành phiên bản mới trong `runtime/alert-config/` (lý do bắt buộc, xem trước, khôi phục).

- Schema 2 của `config/alert_tiers.default.json` thêm mục `ood_flags.metrics.<chỉ số>`
  `{label_vi, feature, enabled, muted_reason_vi?}`; chỉ `enabled` sửa được. Phiên bản lưu
  trước schema 2 vẫn hợp lệ, `load_effective` bổ sung mục này từ mặc định.
- Mặc định: TAN (feature `NH3` = amoni theo N), pH, Nhiệt độ, COD **bật**; TSS **tắt**
  ("cơ sở TSS cảm biến khác dữ liệu tỉnh — đang xem xét riêng").
- Tắt chỉ đổi phần hiển thị: `diagnostics.ood`, `ood_targets`, `input_flagged` và câu cảnh
  báo của `classify_station` chỉ tính chỉ số đang bật. `ood_features` luôn ghi đủ;
  `ood_features_muted`, `ood_any`, `ood_targets_all`, `ood_flags{config_version, muted_metrics}`
  cho biết đã tắt gì. Pipeline trả `ood_flags` ở cấp gốc.
- Mô hình ngữ cảnh DO/độ mặn (`core/contextual_models.py`) vẫn **loại** dự đoán khi input
  ngoài min–max huấn luyện, kể cả chỉ số đã tắt; bản ghi bị loại chỉ thêm `ood_features_muted`.
  Sổ dự báo shadow (`runtime/forecast-shadow/forecasts.jsonl`) nay ghi thêm `inference_diagnostics`
  mỗi mốc (đủ `ood_features` + `ood_features_muted`).
- API: `GET /api/v1/admin/ood-flags` (trạng thái hiệu lực); preview trả `ood_flags.muted_metrics`.
- Cấu hình hỏng → coi như bật hết (`source: fallback_all_enabled`), không bao giờ ẩn cờ.
