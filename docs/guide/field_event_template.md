# Mẫu nhật ký sự kiện thực địa (Field Event Schema)

Để tương thích với luồng nhập liệu tự động và kiểm toán, dữ liệu sự kiện thực địa cần lưu dưới dạng CSV với các trường sau:

\\\csv
event_id,station_id,cage_id,start_at_utc,end_at_utc,event_type,measured_do,lab_sample_id,fish_symptoms,actions_taken,confirmed_by,label_quality,evidence_source
EV-001,06M26042804,Long_3,2026-10-01T07:00:00Z,2026-10-01T09:30:00Z,mortality,2.1,,Cá nổi đầu,Bật sục khí,NguyenVanA,high,Visual_and_Sensor
\\\

**Định nghĩa các trường:**
- \event_id\: Mã duy nhất của sự kiện
- \station_id\: Mã trạm (VD: 06M26042804)
- \cage_id\: Mã/Tên lồng nuôi
- \start_at_utc\: Thời gian bắt đầu (chuẩn ISO 8601 UTC)
- \end_at_utc\: Thời gian kết thúc (chuẩn ISO 8601 UTC)
- \event_type\: Loại sự kiện (mortality, disease, low_do, feeding_issue, equipment_failure)
- \measured_do\: Giá trị DO đo trực tiếp bằng máy cầm tay (mg/L) tại thời điểm xảy ra sự kiện
- \lab_sample_id\: Mã mẫu lab (nếu có)
- \ish_symptoms\: Mô tả dấu hiệu (VD: Cá nổi đầu, tấp lề)
- \ctions_taken\: Thao tác xử lý (VD: Bật sục khí, ngừng cho ăn)
- \confirmed_by\: Người xác nhận
- \label_quality\: Độ chắc chắn của nhãn (high, medium, low) - không tự sinh từ policy dự báo
- \evidence_source\: Nguồn bằng chứng (Visual, Sensor, Lab, Third_party)
