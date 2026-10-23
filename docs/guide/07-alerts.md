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
