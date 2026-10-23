# 2026-10-23: thiệt hại lồng bè do bão và mức gió tại lồng

Phạm vi: bằng chứng công khai về bão nhiệt đới làm hỏng lồng/bè nuôi biển, ghép với gió tại lồng ước tính từ IBTrACS (`storm_passages`), để xem bậc hành động `SITE_ACTIONS_VI` (cấp 6/8/10/12) có hợp lý không. **Không sửa code bậc hành động**; đề xuất ở mục 5.

- Nguồn: `docs/references/storm-damage-sources.md`; dữ liệu `experiments/storm_damage_evidence.csv` (34 dòng), `experiments/storm_damage_engineering.csv` (10 dòng). Bản chữ của mỗi trang: `data/references/storm_damage/` (ghi một lần, SHA-256 trong CSV).
- Code: `experiments/storm_damage.py` (`register`, `analyze`), test `tests/test_storm_damage.py`.
- Lần chạy: `artifacts/experiments/storm-damage-20261023b/` (thêm bootstrap và đường cong "có thiệt hại"). `storm-damage-20261023` giống hệt phần exposure/bảng, chỉ thiếu bootstrap, bị thay thế.

## 1. Bằng chứng thu được

| Vùng | Số dòng | Trong đó `primary` | Ghi chú |
| --- | --- | --- | --- |
| Bắc Bộ (Quảng Ninh, Hải Phòng) | 20 | 14 | Yagi 2024 ở 5 khu vực; Sơn Tinh 2012; Kalmaegi 2014; 7 ca không ghi nhận thiệt hại |
| Bắc Trung Bộ (Quảng Trị) | 1 | 1 | Kajiki 2025, lồng gỗ tre |
| Nam Trung Bộ (Khánh Hòa, Phú Yên/Đắk Lắk, Lý Sơn) | 7 | 4 | Damrey 2017, Kalmaegi 2025, Noru 2022 (lồng HDPE) |
| Vùng tương tự (Hồng Kông, Quảng Đông, Hải Nam, Philippines, Penang) | 6 | 3 | Mangkhut 2018, Hato 2017, Chaba 2022 |

Phân tích dùng 22 dòng `primary` (một dòng cho mỗi cặp bão – khu vực, 16 cơn bão): 14 có thiệt hại, 8 không ghi nhận. Theo loại lồng: gỗ/hỗn hợp 18, HDPE 1, không rõ 3. Không tìm được nguồn cho Thái Bình, Nam Định, Thanh Hóa, Nghệ An, Hà Tĩnh, Nhật Bản, Đài Loan.

**Lớp thiệt hại** (gán tay theo câu trích):

| Lớp | Định nghĩa |
| --- | --- |
| catastrophic | nguồn nói mất gần hết / toàn bộ lồng của khu vực (≥ ~50 % hoặc "mất trắng" phần lớn hộ) |
| major | hàng chục lồng trở lên bị phá, hoặc nguồn chính thức nói "nghiêm trọng" nhưng không phải gần hết |
| minor | vài lồng (≤ ~5) hoặc diện tích nhỏ so với vùng nuôi |
| none | nguồn sau bão không nêu thiệt hại lồng bè (`absence_of_report`) hoặc nói rõ không thiệt hại (`direct`) |

## 2. Giới hạn kỹ thuật tìm được

| Mục | Nội dung | Nguồn | Độ tin cậy |
| --- | --- | --- | --- |
| Tiêu chí chọn vị trí lồng nổi | gió < 10 kn, sóng < 1,0 m (lồng cố định: 5 kn, 0,5 m); bão tạo sóng 3–15 m | FAO/NACA 1989 (`eng-naca-1989-site`) | tiêu chí chọn vị trí, **không** phải giới hạn chịu tải |
| Lồng nổi đơn giản | chịu sóng không quá 2 m; "dưới bão cuồng phong hầu như không vị trí nào bảo vệ được lồng nổi loại nào" | FAO Jamaica (`eng-fao-jamaica`) | tài liệu FAO |
| TCVN 13997:2024 (lồng tròn HDPE) | có tồn tại; **không mở được nội dung** (lỗi SSL trang VSQI) | `eng-tcvn-draft-2026` | chưa có số liệu |
| Lồng HDPE "chịu cấp 12" | lời thợ đóng bè / người nuôi, không phải thử nghiệm | `eng-plvn-hdpe-claim`, `noru-2022-lyson` | tuyên bố, chưa kiểm chứng |
| Mục tiêu chính sách | Chủ tịch UBND Quảng Ninh: vật liệu nuôi biển cần chịu "trên cấp 12" | `eng-qn-policy-level12` | định hướng |
| Hàm dễ tổn thương | xác suất hỏng lồng theo **chiều cao sóng có nghĩa**; ANN dự báo hỏng lồng HDPE theo sóng bão Maria | Fang et al. 2025; Shi et al. (`eng-fang-2025`, `eng-shi-ann-maria`) | phương pháp; dùng sóng, không dùng cấp gió |

Không tìm được hàm thiệt hại theo cấp gió cho lồng nuôi ở Việt Nam. Nhiều nguồn sự kiện nêu **sóng** là nguyên nhân trực tiếp (Damrey: sóng ~6 m; Cát Bà 2024: "sóng lớn đánh sập"; Quảng Trị 2025: "bị sóng đánh tan hoang").

## 3. Thiệt hại theo gió tại lồng (IBTrACS, hệ số 0,93)

`site_beaufort` tính tại tọa độ của dòng; 17/22 dòng dùng bán kính gió (`wind_radii`), tức **cận dưới**: trong R64 mọi điểm đều ra cùng 30,6 m/s (cấp 11), trong R50 ra 23,9 m/s (cấp 9). Hệ số 0,88 cho cùng cấp ở mọi dòng.

| Lớp \ cấp tại lồng | ≤ 5 | 6–7 | 8–9 | 10–11 | ≥ 12 |
| --- | --- | --- | --- | --- | --- |
| none | 0 | 5 | 3 | 0 | 0 |
| minor | 0 | 0 | 1 | 2 | 0 |
| major | 0 | 0 | 3 | 2 | 1 |
| catastrophic | 0 | 0 | 2 | 3 | 0 |

- **Cấp 6–7:** 5/5 không ghi nhận thiệt hại (Prapiroon 2024 Vân Đồn: nguồn trực tiếp, gió đo trên đất liền cấp 6–7; 4 ca còn lại là không có tin, bằng chứng yếu).
- **Cấp 8–9:** 6 có thiệt hại (Kajiki 2025 Quảng Trị 8, Sơn Tinh 2012 Vân Đồn 9, Kalmaegi 2014 Quảng Ninh 9, Chaba 2022 9, Damrey 2017 Vạn Ninh và Sông Cầu 9) và 3 không (Talim 2023 Móng Cái 8, Prapiroon 2024 Cô Tô 9, Noru 2022 Lý Sơn 9 với lồng HDPE). 5/6 ca thiệt hại ở dải này là cận dưới; Damrey đổ bộ cách Vạn Ninh 11 km với giật cấp 15 nên gió thật tại lồng cao hơn nhiều.
- **Cấp 10–11:** 7/7 có thiệt hại (Yagi 2024 ở Vân Đồn, Cẩm Phả, Quảng Yên: catastrophic; Cát Bà: major; Cô Tô: minor; Hồng Kông: Mangkhut major, Hato minor). Vùng nuôi kín gió (Hồng Kông) hoặc ít lồng (Cô Tô) chỉ hỏng nhẹ ở cùng cấp gió.
- **≥ 12:** 1 (Kalmaegi 2025 Sông Cầu, Rankine, major).

**Ngưỡng bắt đầu (lồng gỗ / hỗn hợp, 18 ca):** thiệt hại thấp nhất ở cấp 8 (1 ca, Rankine), major thấp nhất ở cấp 8; không có ca không thiệt hại nào trên cấp 9. Chỉ tính ca nguồn trực tiếp (13 ca): không thiệt hại cao nhất ở cấp 7, thiệt hại từ cấp 8.

**Đường cong dễ tổn thương** (logistic không phạt; dữ liệu chồng lấn ở cấp 8, 9, 11 nên không tách hoàn toàn; bootstrap 1000 lần, KTC 90 %):

| Tập | n (dương / âm) | Mục tiêu | Cấp ở P = 0,5 | KTC 90 % |
| --- | --- | --- | --- | --- |
| Lồng gỗ / hỗn hợp | 18 (12 / 6) | có thiệt hại | 8,4 | 7,9–9,0 |
| Lồng gỗ / hỗn hợp | 18 (10 / 8) | major trở lên | 9,0 | 7,8–10,4 |
| Mọi `primary` | 22 (11 / 11) | major trở lên | 9,2 | 8,3–10,5 |
| Chỉ nguồn trực tiếp | 16 (11 / 5) | major trở lên | 7,7 | không ổn định (−0,1–10,0) |

Kết quả chỉ là **thăm dò**: n nhỏ, 5 ca thuộc cùng một cơn bão (Yagi), ca âm chủ yếu là "không có tin", và gió tại lồng thiên thấp (cận dưới) nên ngưỡng ước tính cũng thiên thấp.

## 4. So với bậc hành động hiện tại

| Bậc (`SITE_ACTIONS_VI`) | Bằng chứng | Đánh giá |
| --- | --- | --- |
| cấp 6 "theo dõi" | 0/5 thiệt hại ở cấp 6–7 | phù hợp |
| cấp 8 "chuẩn bị" | thiệt hại bắt đầu ở cấp 8–9 (6/9 ca), major có ở cấp 8–9 (5 ca); P(có thiệt hại) = 0,5 ở cấp ~8,4 | ngưỡng đúng chỗ nhưng **hành động hơi muộn**: gia cố và thu hoạch cần làm xong trước khi gió tại lồng đạt cấp 8 |
| cấp 10 "nguy hiểm" | ở cấp 10–11 mọi ca đều có thiệt hại, 5/7 major trở lên; P(major) = 0,5 ở cấp ~9 | ngưỡng hơi cao so với bằng chứng |
| cấp 12 "rất nguy hiểm" | không đủ ca ≥ 12 để phân biệt với 10–11 (gió cận dưới) | giữ để khớp QĐ 18; không có bằng chứng riêng |

## 5. Đề xuất (chưa sửa code; cần chuyên gia / người nuôi xem lại)

1. **Giữ** mốc cấp 6 và cấp 8. Ở bậc cấp 8, chuyển "chuẩn bị phương án thu hoạch" thành "**thu hoạch sớm cá thương phẩm nếu kịp**" và nêu rõ phải làm khi **dự báo** gió tại lồng đạt cấp 8 trong 48–72 giờ tới (độ tin cậy: thấp – trung bình; 6/9 ca ở cấp 8–9 có thiệt hại).
2. **Hạ** bậc "nguy hiểm" từ cấp 10 xuống **cấp 9** cho lồng gỗ / bè hỗn hợp; nội dung: kéo lồng vào nơi kín gió, **người rời lồng bè** (độ tin cậy: thấp; P(major) = 0,5 ở cấp 9,0, KTC 7,8–10,4). Lý do an toàn: Sơn Tinh 2012 và Yagi 2024 đều có người ở lại trên bè khi bão vào.
3. Giữ cấp 12 để khớp QĐ 18/2021, nhưng ghi rõ thiệt hại "mất trắng" đã xảy ra ở cấp 10–11 tại lồng.
4. **Không** đặt bậc riêng cho lồng HDPE: chỉ 1 ca (Noru 2022, không hỏng, gió ước tính cấp 9, giật đo 7–8) và 1 ca hỏng nặng ở Hải Nam (Yagi 2024, vị trí không rõ). Tuyên bố "chịu cấp 12" chưa có thử nghiệm; TCVN 13997:2024 chưa đọc được.
5. Thêm chỉ báo **sóng** (Open-Meteo marine `wave_height`) làm ngữ cảnh: nguồn sự kiện thường nêu sóng là nguyên nhân, và nghiên cứu dễ tổn thương (Fang 2025, Shi) dùng chiều cao sóng.

## 6. Hạn chế

- **Bằng chứng báo chí, không phải điều tra hiện trường.** Lớp thiệt hại gán tay; con số giữa các nguồn có thể lệch (Damrey Phú Yên: 238 lồng theo UN, 24.000 theo VNS – định nghĩa "lồng" khác nhau).
- **Ca âm yếu:** 6/8 ca "none" là không thấy tin thiệt hại sau khi tìm (bài sớm sau bão, có thể chưa thống kê). Một ca âm trực tiếp (Prapiroon Vân Đồn, "chưa xảy ra thiệt hại" sáng hôm sau).
- **Gió tại lồng là ước tính best track** (oracle hồi cứu, không phải dự báo), 17/22 là cận dưới theo bán kính gió; Rankine bỏ qua che chắn của đảo/vịnh. Vị trí cấp tỉnh dùng tọa độ vùng nuôi chính, sai số có thể vài chục km.
- **Không độc lập:** 5 ca primary cùng là Yagi 2024; Damrey 2 ca. Bootstrap theo ca nên KTC thực còn rộng hơn.
- **Thiên lệch chọn mẫu:** báo chí đưa tin bão gây thiệt hại nhiều hơn bão không gây thiệt hại; các bão mạnh (≥ 10) đều có thiệt hại một phần vì thế.
- Mức độ kín gió, loại lồng, neo và việc người nuôi đã gia cố hay chưa ảnh hưởng mạnh (Hồng Kông chỉ hỏng nhẹ ở cấp 11 với Hato) nhưng không được mô hình hóa.
