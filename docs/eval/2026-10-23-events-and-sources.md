# 2026-10-23: danh mục sự kiện và đối chiếu nguồn bão / nắng nóng

Phạm vi: `experiments/hazard_events.csv`, QĐ 18/2021/QĐ-TTg Điều 42, hệ số Harper 1 phút → 10 phút. Chạy lại `storm-hindcast-20261023c` (thay cho `-20261022d` về phần `events_check`).

## 1. QĐ 18/2021/QĐ-TTg, Điều 42 (bản .doc gốc, trích bằng Word)

Nguồn: https://vupc.mae.gov.vn/Data/files/18_2021_QD-TTg.doc

| Cấp độ rủi ro | Điều kiện (dự báo) |
| --- | --- |
| 3 | ATNĐ, bão cấp 8–9 trên Biển Đông, vùng biển ven bờ, đất liền (Tây Bắc, Việt Bắc, Đông Bắc Bộ, đồng bằng Bắc Bộ, ...); bão mạnh cấp 10–11 trên Biển Đông, ven bờ, đất liền (trừ Nam Bộ); bão rất mạnh cấp 12–13 **chỉ trên Biển Đông** |
| 4 | Bão rất mạnh cấp 12–13 trên **vùng biển ven bờ**, đất liền Đông Bắc Bộ, đồng bằng Bắc Bộ, ...; bão rất mạnh cấp 14–15 trên vùng biển ven bờ, đất liền Đông Bắc Bộ, đồng bằng Bắc Bộ, Bắc/Trung Trung Bộ; bão từ cấp 14 trở lên trên Biển Đông |
| 5 | Siêu bão từ cấp 16 trở lên trên vùng biển ven bờ, đất liền Đông Bắc Bộ, đồng bằng Bắc Bộ, ... (Biển Đông không có cấp 5) |

Kết luận: `qd18_risk_level` (8–11 → 3, 12–15 → 4, ≥ 16 → 5) **đúng cho vùng biển ven bờ / Đông Bắc Bộ**. Không sửa logic. Điểm mơ hồ: văn bản ghi "áp thấp nhiệt đới, bão cấp 8, cấp 9" nên cấp 6–7 → 3 là một cách đọc, không chắc chắn; chỉ đổi nếu muốn đọc chặt (khi đó cấp 6–7 → không có cấp độ). Biển Đông (12–13 → 3, ≥ 14 → 4) chưa mô hình hóa vì lồng ở vùng ven bờ. Đã ghi chú vào docstring, thêm test biên 8, 13, 14, 17.

Điều 50 (gió mạnh trên biển), chưa nối vào code:
- Cấp 2: gió mạnh cấp 6 trên vùng biển ven bờ; cấp 7–8 trên vùng biển ngoài khơi.
- Cấp 3: gió mạnh từ cấp 7 trở lên trên vùng biển ven bờ; từ cấp 9 trở lên ngoài khơi.

Điều 47 (nắng nóng), để tham khảo cho phần nhiệt: cấp 1 khi nhiệt độ cao nhất trong ngày 35–37 °C kéo dài từ 3 ngày (Bắc Bộ, Trung Bộ); đây là nhiệt độ không khí, không phải nhiệt độ nước.

## 2. Hệ số 1 phút → 10 phút

Nguồn: Harper, Kepert & Ginger 2010, WMO/TD-No. 1555, Bảng 1.2 (https://www.systemsengineeringaustralia.com.au/download/WMO_TC_Wind_Averaging_27_Aug_2010.pdf): `Vmax600 = K · Vmax60`, K = 0.93 (at-sea), 0.90 (off-sea), 0.87 (off-land), 0.84 (in-land). Báo cáo viết rõ: "at-sea conversion ... of 0.93, rather than the traditional value of 0.88, which has been shown here to be associated more with an off-land exposure".

Kết luận: 0.93 đúng cho at-sea; 0.88 gần giá trị off-land (0.87) nên là ca độ nhạy hợp lý cho gió ven bờ. Không sửa hằng số; đã thêm trích dẫn bảng vào comment.

## 3. Danh mục sự kiện (12 dòng)

Cột `verified`: `yes` = bài đã mở nêu sự kiện và tác động; `partial` = bài xác nhận bão và chuẩn bị/sơ tán nhưng không nêu thiệt hại lồng bè ở Hải Phòng - Quảng Ninh.

| Loại | Số dòng | Ghi chú |
| --- | --- | --- |
| storm | 8 | yagi-2024 (yes, SAR), wipha-2025 (yes, ngập 14 ha, cuốn 3 tấn cá), wipha-2019, talim-2023, kajiki-2025, matmo-2025, maysak-2026, narra-2026 (partial) |
| disease | 1 | lanha-2018-10: 20 tấn cá song, cá giò, bệnh nấm mang |
| fishkill | 2 | haiha-clam-2018-11: 2.000 tấn ngao (chưa rõ nguyên nhân); vandon-lowsal-2025-10: độ mặn 20 sau mưa bão |
| heat | 1 | phulong-2026-06: cá song thiếu oxy, nắng nóng, mực nước thấp (cơ quan chức năng); Tiền Phong nghi nước thải nhưng chưa kết luận |

Số liệu thiệt hại lồng bè khác cho Yagi 2024 (chưa thêm dòng riêng để không đếm trùng bão): Quảng Ninh hơn 1.100 lồng bè chìm hoặc cuốn trôi (https://vnexpress.net/trang-tay-sau-bao-yagi-4790511.html); toàn quốc 19.956 ha và 4.246 lồng (https://vneconomy.vn/toan-nganh-thuy-san-dieu-dung-vi-bao-yagi.htm); Quảng Ninh gần 3.000 cơ sở, hơn 43.000 tấn hải sản nuôi (https://vneconomy.vn/quang-ninh-khoi-phuc-nuoi-trong-thuy-hai-san-sau-sieu-bao.htm).

Hạn chế: ngày bắt đầu/kết thúc là ngày bão ảnh hưởng ước tính từ bài viết (vandon và phulong chỉ theo tháng, ±vài ngày). Không tìm thấy trang nêu sự kiện cá chết do nắng nóng ở Cát Bà trước 2026, nên chỉ một dòng heat. Các sự kiện cá chết chưa đủ để kiểm định chỉ báo nhiệt.

## 4. events_check (`storm-hindcast-20261023c`)

| Sự kiện | verified | Bão (IBTrACS) | Gió tại lồng (cấp) | QĐ 18 |
| --- | --- | --- | --- | --- |
| yagi-2024 | yes | YAGI | 11 | 4 |
| wipha-2019 | partial | WIPHA | 7 | 3 |
| talim-2023 | partial | TALIM | 6 | 3 |
| wipha-2025 | yes | WIPHA | 7 | 3 |
| kajiki-2025 | partial | KAJIKI | 6 | không |
| matmo-2025 | partial | MATMO | 7 | 3 |
| maysak-2026 | partial | MAYSAK | 7 | 3 |
| narra-2026 | partial | NARRA | 7 | 3 |

Tỷ lệ bắt gặp: cả 8 bão được khớp (8/8), gió tại lồng ≥ cấp 6: 8/8; ≥ cấp 8: 1/8 (chỉ YAGI). Với 2 sự kiện `verified = yes`: ≥ cấp 6 là 2/2, ≥ cấp 8 là 1/2.

Diễn giải thận trọng: gió tại lồng là cận dưới/ước tính best track, chưa so với gió đo; các bão `partial` không có thiệt hại lồng bè nên không dùng để đánh giá độ nhạy thiệt hại. Chỉ YAGI cho thiệt hại lớn và là bão duy nhất ≥ cấp 8, phù hợp với ngưỡng cấp 8 là điểm bắt đầu có thiệt hại lồng nhưng n = 1 nên không kết luận được ngưỡng.
