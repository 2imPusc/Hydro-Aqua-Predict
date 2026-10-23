# Tiêu chuẩn và hướng dẫn về lồng nuôi biển (TCVN 13997:2024 và liên quan)

**Ngày lập:** 23/10/2026. **Dùng cho:** bậc cảnh báo sóng/gió trong `config/alert_tiers.default.json` và phân lớp phơi lộ vị trí (`sheltered` / `semi` / `exposed`).

Dữ liệu máy đọc: 11 dòng mới (từ `std-tcvn13997-2024-luatvietnam` trở đi) trong `experiments/storm_damage_engineering.csv`, có thêm hai cột cuối `parameters_extracted`, `evidence_type` (các dòng cũ để trống). Bản chữ thô của từng trang đã mở nằm ở `data/references/standards/` (ghi một lần, không đưa vào git); `local_copy_sha256` là SHA-256 của bản đó, `quote` đã kiểm tra khớp nguyên văn với bản lưu. Với PDF, bản lưu của cột `local_copy_file` là bản chữ trích bằng `pdftotext`, bản PDF gốc nằm cạnh.

## 1. TCVN 13997:2024: kết quả tra cứu

| Mục | Nội dung | Mức chắc chắn |
| --- | --- | --- |
| Tên | "Lồng tròn HDPE nuôi cá biển quy mô công nghiệp - Yêu cầu kỹ thuật" | đã xác minh (3 nguồn: LuatViet, Dekko, BNEWS 26/06/2026) |
| Cơ quan | Viện Nghiên cứu Hải sản biên soạn; Bộ NN&PTNT đề nghị; Tổng cục TCĐLCL thẩm định; Bộ KH&CN công bố | đã xác minh (catalogue Dekko; LuatViet) |
| Ngày | Trang LuatViet ghi "Ngày ban hành 29/05/2024" ở phần đầu và "ban hành ngày 15/03/2024" trong phần tóm tắt: **hai ngày mâu thuẫn**, số quyết định công bố **chưa tìm được** | chưa xác định |
| Phạm vi | "vùng biển có độ sâu từ 20 m trở lên và lưu tốc dòng chảy lớn hơn 0,3 m/s" | đã xác minh (bản tóm tắt LuatViet, đã lưu) |
| Nội dung tóm tắt | lồng đường kính 10-40 m; khung ống HDPE từ PN10 trở lên; lưới PE/HDPE; dây giềng PP lực đứt 1.519,9-6.189,8 kgf; vật nặng, neo, dây neo PP; phao giữ cân bằng dây neo PVC, lực nổi tối thiểu 2.856 kgf | đã xác minh ở mức tóm tắt (LuatViet) |
| Giá trị sóng/gió/dòng thiết kế | **Không có trong phần miễn phí.** Tóm tắt chỉ nêu điều kiện áp dụng (độ sâu ≥ 20 m, dòng > 0,3 m/s); không thấy chiều cao sóng thiết kế, tốc độ gió, hệ số an toàn | không có dữ liệu |
| Truy cập toàn văn | Cần tài khoản trả phí (LuatViet: "Tiêu chuẩn" hoặc "Nâng cao"); thuvienphapluat.vn trả 403 cho công cụ tự động; cửa hàng tiêu chuẩn `tieuchuan.vsqi.gov.vn` đang hiện "Website Disabled" khi truy cập ngày 23/10/2026. Một kết quả tìm kiếm tóm tắt nêu giá 100.000 đ trên tieuchuan.vsqi.gov.vn nhưng **không kiểm chứng được** vì trang không mở | chưa mua; không vượt tường phí |

Hệ quả cho dự án: TCVN 13997 là tiêu chuẩn **cấu kiện** (kích thước ống, dây, neo, phao) cho vùng biển hở có dòng đủ mạnh; nó **không** là nguồn cho ngưỡng cảnh báo sóng/gió, ít nhất ở phần đọc được. Muốn biết sóng thiết kế phải mua bản gốc (hoặc xin Viện Nghiên cứu Hải sản). Theo BNEWS (26/06/2026) Cục Thủy sản và Kiểm ngư đang lấy ý kiến một TCVN thứ hai cho "cơ sở nuôi cá biển công nghiệp" (vị trí nuôi, hệ thống lồng, lắp đặt, vận hành; dự kiến ban hành cuối 2026 hoặc đầu 2027), và một chuyên gia đề nghị đưa vào yêu cầu "khả năng chống chịu điều kiện sóng gió trên biển". Nên theo dõi.

## 2. Các tiêu chuẩn và hướng dẫn khác (đã mở)

### 2.1. Số liệu đã xác minh (nguyên văn trong bản lưu)

**FAO Fisheries and Aquaculture Technical Paper 593** (Cardia và Lovatelli 2015, "Aquaculture operations in floating HDPE cages", `std-fao-tp593-hdpe-handbook`), tái hiện phân lớp của NS 9415-2003:

| Lớp sóng | Hs (m) | Tp (s) | Mức phơi lộ |
| --- | --- | --- | --- |
| A | 0,0-0,5 | 0,0-2,0 | thấp |
| B | 0,5-1,0 | 1,6-3,2 | trung bình |
| C | 1,0-2,0 | 2,5-5,1 | đáng kể |
| D | 2,0-3,0 | 4,0-6,7 | cao |
| E | > 3,0 | 5,3-18,0 | cực đoan |

| Lớp dòng | Vc (m/s) | Mức phơi lộ |
| --- | --- | --- |
| a | 0,0-0,3 | thấp |
| b | 0,3-0,5 | trung bình |
| c | 0,5-1,0 | đáng kể |
| d | 1,0-1,5 | cao |
| e | > 1,5 | cực đoan |

Cùng tài liệu: phân loại FAO 2009: ven bờ Hs thường < 1 m; ngoài bờ Hs ≤ 3-4 m; xa bờ Hs ≥ 5 m; "Hs x 1,9 = chiều cao sóng lớn nhất"; dòng chiếm 70-75 % tổng lực lên lồng cỡ trung; NS 9415 yêu cầu **dòng 50 cm/s** làm đầu vào tối thiểu để tính hệ neo; dòng tối ưu cho cá hồi 25-50 cm/s, tối đa khuyến nghị 75 cm/s; Bảng 7 liên hệ gió, đà gió và Hs (ví dụ gió 20 m/s, đà 10 km: Hs 1,5 m; gió 30 m/s, đà 10 km: Hs 2,5 m).

**NS 9415:2021** (`std-ns9415-2021`): trang catalogue chỉ nêu phạm vi (ngăn cá thoát; khảo sát vị trí, tải, kiểm tra sức bền, lồng/phao/neo). Toàn văn bán; không có số trên trang. Bản dự án Faroe (Simonsen 2020, `std-ns9415-site-classes-faroe`) xác nhận NS 9415 phân lớp vị trí theo dòng cực đại và chiều cao sóng, nhưng lớp trên cùng chỉ tới "> 3 m".

**ISO 16488:2015** (`std-iso16488-2015`): quy trình phân tích, thiết kế, đánh giá lồng lưới nuôi cá biển; "design basis" từ điều kiện môi trường và rủi ro chấp nhận được. Toàn văn bán; trang không có số.

**FAO/NACA 1989** (đã có trong danh mục cũ, `eng-naca-1989-site`): gió không quá 10 kn và sóng < 1 m cho lồng nổi; tiêu chí chọn vị trí, không phải giới hạn chịu tải.

### 2.2. Văn bản pháp luật và hướng dẫn Việt Nam

- **Nghị định 26/2019/NĐ-CP, Điều 34 và 36** (`reg-nd26-2019-art34`): điều kiện cơ sở nuôi lồng bè gồm vật liệu không gây ô nhiễm, **không để thủy sản thoát ra**, thiết bị cảnh báo giao thông thủy, nơi chứa rác; đăng ký lồng bè với sơ đồ vị trí. **Không có số liệu sóng, gió, dòng.**
- **QCVN 02-22:2015/BNNPTNT** (`reg-qcvn-02-22-2015`): chỉ cho lồng bè **nước ngọt** (dòng 0,2-0,5 m/s; mật độ lồng ≤ 0,2 % mặt nước nơi có dòng). Không áp dụng cho nuôi biển; ghi lại để tránh nhầm. Chưa tìm thấy QCVN riêng cho lồng bè trên biển (không khẳng định là không có).
- **Quyết định 982/QĐ-TCTS-KTTS ngày 28/10/2016** của Tổng cục Thủy sản (hướng dẫn tàu thuyền tránh trú và bảo vệ ao, đầm, lồng, bè khi có bão): chưa mở được văn bản gốc; chỉ thấy được qua bản trích dẫn trong **Công văn 3489/SNN&PTNT-CCTS Quảng Nam 07/11/2024** (`guid-qn-cv3489-2024`) và bài báo về công văn 1744/TS-NTTS của Cục Thủy sản (`guid-cuc-ts-1744-2024`). Nội dung dành cho lồng bè: thu hoạch khi đạt cỡ thương phẩm; kiểm tra, gia cố dây neo và phao; di chuyển vào khu kín gió, dòng nhẹ; nếu không di chuyển được thì **hạ lồng xuống thấp** để giảm sóng gió; che lưới mặt lồng; sơ tán người. **Không có ngưỡng số** (không nêu cấp gió hay độ cao sóng nào kích hoạt từng hành động).

### 2.3. Tuyên bố của nhà sản xuất (không phải giá trị tiêu chuẩn)

Catalogue Dekko (`std-tcvn13997-2024-dekko`, 04/2025) ghi: lồng tròn ống kép "chịu được bão lên tới cấp 12 và sóng biển cao 14m", lồng vuông "cấp 10 và sóng biển 9m", lồng ống đơn "cấp 8"; đặt được ở độ sâu 6-100 m; "có khả năng đánh chìm khi gặp bão". Công ty nói sản xuất "theo TCVN 13997:2024". Đây là **lời quảng cáo**: sóng 14 m vượt xa mọi lớp sóng thiết kế ở mục 2.1 (lớp E bắt đầu từ Hs > 3 m, Hmax khoảng 1,9 Hs), không nêu thử nghiệm hay chu kỳ lặp lại, nên **không dùng làm ngưỡng**. Chỉ dùng như bằng chứng rằng nhà sản xuất cũng khuyến cáo "đánh chìm" lồng khi có bão, khớp với hướng dẫn mục 2.2.

## 3. So sánh với bậc mặc định của dự án

Bậc sóng mặc định `wave_height`: 0,5 / 1,0 / 2,0 / 3,0 m (Hs). Bậc gió bão `storm_wind`: cấp Beaufort 6 / 8 / 10 / 12.

| Chỉ tiêu | Bậc của ta | Tiêu chuẩn / hướng dẫn | Nhận xét |
| --- | --- | --- | --- |
| Hs | 0,5 / 1,0 / 2,0 / 3,0 m | Ranh giới lớp A-E của NS 9415 (qua FAO TP 593): 0,5 / 1,0 / 2,0 / 3,0 m | **Trùng khớp từng mốc.** Nhưng lớp NS 9415 là lớp **phơi lộ vị trí theo thống kê dài hạn** để chọn công nghệ lồng, không phải ngưỡng cảnh báo giờ; không nên diễn giải "Hs vượt 2 m = hỏng lồng". |
| Hs 1 m | bậc 2 "vượt giới hạn 1 m cho lồng nổi" | FAO/NACA 1989: tiêu chí chọn vị trí < 1 m | Nhất quán, nhưng là tiêu chí chọn vị trí chứ không phải giới hạn chịu tải. |
| Hs > 3 m | bậc 4 từ 3 m, không có bậc cao hơn | NS 9415 lớp E "> 3 m" (mở); FAO 2009: vùng xa bờ Hs ≥ 5 m | Bậc 4 là "mọi thứ trên 3 m"; vùng nuôi xa bờ có thể gặp Hs ≥ 5 m thường xuyên, nên bậc 4 không phân biệt được 3 m với 6 m (Damrey 2017: sóng khoảng 6 m, theo danh mục sự kiện). |
| Hmax | chưa dùng | Hmax ≈ 1,9 Hs (FAO TP 593) | Nên ghi chú: Hs 2 m tương ứng sóng lớn nhất khoảng 3,8 m. |
| Dòng chảy | không có bậc | Lớp dòng a-e: 0,3 / 0,5 / 1,0 / 1,5 m/s; NS 9415 lấy 0,5 m/s làm đầu vào tối thiểu cho hệ neo; TCVN 13997 áp dụng cho dòng > 0,3 m/s | Dự án chưa có chỉ báo dòng. Dòng không phải hiểm họa bão chính ở Cát Bà nhưng là điều kiện thiết kế neo; chỉ nên ghi như thuộc tính vị trí. |
| Gió | cấp 6 / 8 / 10 / 12 | Không tiêu chuẩn nào đọc được nêu ngưỡng gió cho lồng; hướng dẫn Việt Nam không nêu cấp gió kích hoạt; tuyên bố nhà sản xuất cấp 8 / 10 / 12 | Bậc gió của ta vẫn chỉ dựa vào đối chiếu sự kiện (`docs/eval/2026-10-23-storm-damage.md`) và QĐ 18/2021. Bảng 7 của FAO cho thấy Hs phụ thuộc cả đà gió: gió 20 m/s (cấp 8) tạo Hs 0,8 / 1,5 / 2,5 m ở đà 3 / 10 / 30 km, nên cấp gió một mình không quyết định sóng ở lồng. Điều này củng cố đề xuất bổ sung chỉ báo **sóng** làm ngữ cảnh. |
| Hành động | bậc 3 "thu hoạch sớm, gia cố hoặc kéo lồng vào nơi kín gió" | CV 3489 (theo QĐ 982/2016): thu hoạch, gia cố neo phao, di chuyển vào nơi kín gió, hạ lồng nếu không di chuyển được | Nhất quán. **Chưa có** hành động "hạ lồng xuống thấp / đánh chìm" trong `actions_vi`; có thể bổ sung ở bậc 3 cho lồng có cơ cấu chìm, ghi nguồn là hướng dẫn chứ không phải ngưỡng. |

### Gợi ý cho lớp phơi lộ vị trí

Ánh xạ tham khảo (không phải quy định), dựa trên các lớp NS 9415 và phân loại FAO 2009: `sheltered` ≈ lớp sóng A-B (Hs thiết kế ≤ 1 m; vịnh kín, ven bờ); `semi` ≈ lớp C (1-2 m); `exposed` ≈ lớp D-E (> 2 m; vùng biển hở, xa bờ). Cần đặt Hs thiết kế **dài hạn** (ví dụ chu kỳ lặp lại 50 năm, như NS 9415 khuyến cáo cho dòng) khi gán lớp, không dùng Hs nhất thời. Dự án hiện chưa có dữ liệu đó cho Cát Bà; xem `docs/eval/2026-10-23-site-exposure.md`.

## 4. Hạn chế

- Không đọc được toàn văn TCVN 13997:2024, NS 9415:2021, ISO 16488:2015 (đều bán). Mọi con số về chúng đến từ tóm tắt hoặc tài liệu thứ cấp (FAO TP 593 trích NS 9415 bản **2003**, không phải bản 2021 hiện hành; bản 2021 có thể đổi ranh giới lớp).
- Số quyết định công bố TCVN 13997:2024 chưa tìm được; ngày ban hành mâu thuẫn (29/05/2024 và 15/03/2024) trong cùng một trang.
- Giá 100.000 đ chưa kiểm chứng; trang bán tiêu chuẩn ngừng hoạt động khi truy cập.
- Trang tóm tắt LuatViet nằm trên nguồn thương mại và có thể do máy tạo; các con số trong đó (PN10, lực đứt, lực nổi) nên đối chiếu với bản gốc trước khi dùng.
- Chưa tìm được văn bản gốc của QĐ 982/QĐ-TCTS-KTTS 2016 (Tổng cục Thủy sản).
- Tuyên bố nhà sản xuất chỉ lấy từ một catalogue (Dekko).
- Ghi chú về các tệp trong `data/references/standards/` (không xóa được do quy tắc ghi một lần): `guidance__laichau-sonn-2024-09-06.pdf` chỉ chứa thông báo lỗi 33 byte ("The server name is not supported."), không phải tài liệu; `tcvn13997__caselaw.*` và `tcvn13997__vsqi-*` / `tcvn13997__vsqi-list.*` chỉ là trang giao diện chung hoặc trang "Website Disabled", không có nội dung tiêu chuẩn; `fao__hdpe-handbook-agris.*` là trang danh mục của FAO TP 593 (bản đầy đủ là `fao__i4508e-hdpe-cages-handbook.*`); `fao__tp576-hexagonal-wooden-cages.*` và `qcvn__tt16-2015-hoatieu.*` đã lưu nhưng chưa dùng trong bảng.
