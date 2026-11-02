# Nguồn NH4 / ammonium liên tục công khai — rà soát cho F5 (bài báo 2)

Ngày: 02/11/2026. Mục đích: F4 (RL-79) trượt vì Turb / DO gần 0, trong khi sự cố thật ở NB1 là NH4, nên hại trên NH4 chưa
được đo. Cần chuỗi NH4 liên tục (ISE hoặc analyzer, ≤ 1 h, tốt nhất ≥ 1 năm, ưu tiên ven biển / cửa sông, có cờ QC).

Ràng buộc: chỉ nguồn công khai trên web, không đăng ký tài khoản, không gửi thư xin dữ liệu, không vượt chặn script; nguồn
phải xin hoặc cần khóa ghi "không lấy được". Không trùng `data/foreign/CANDIDATES-H4.md`: các mạng ở đó (Texas TWDB, Maryland,
NERRS, IRLON, USGS SF Bay, KOEM từng trạm) không có NH4 liên tục; NERRS chỉ có NH4 mẫu rời hằng tháng.

**Kết luận ngắn:** chỉ một họ nguồn có triển vọng: bộ file "공동활용체계 수질자동측정망" của Bộ Hải dương Hàn Quốc (MOF), mới so
với CANDIDATES-H4. Nó **chưa đạt đủ tiêu chí đã kiểm được** (không có cờ QC; độ dài và độ phủ NH4 chưa biết). Mọi nguồn còn lại
trượt hoặc không lấy được.

## Sai lệch khi kiểm (phải đọc)

Yêu cầu là chỉ kiểm metadata hoặc mẫu nhỏ. Tôi gửi yêu cầu `Range: 0-20000` tới data.go.kr cho 5 file, máy chủ **bỏ qua Range**
và curl nhận tổng cộng khoảng **160 MB** (khoảng 22 / 60 / 67 / 6,5 / 4,9 MB, file đầu bị cắt do timeout) trước khi tôi phát hiện.
Tôi cắt mỗi file còn 60 KB đầu để đọc tiêu đề cột và một đoạn đầu, xóa phần còn lại, rồi xóa luôn phần 60 KB sau khi đọc. Không
có gì được ghi vào `data/` hay giữ lại trong dự án. Vì vậy mọi "đã xác minh" về nội dung dưới đây chỉ dựa trên **60 KB đầu file**.
Lần tải thật về sau phải là quyết định riêng của chủ dự án.

## Ứng viên có triển vọng

### A. Hàn Quốc — MOF 공동활용체계 수질자동측정망 (mạng tự động KOEM, bản lưu)

- **URL (trang dữ liệu):** `https://www.data.go.kr/data/<id>/fileData.do`, metadata `https://www.data.go.kr/catalog/<id>/fileData.json`.

| id | Trạm | File kết thúc (theo tên) | Số dòng | Cột NH4 | NH4 trong 60 KB đầu |
| --- | --- | --- | --- | --- | --- |
| 15159658 | Incheon Songdo (인천송도) | 2022-12-31 | 571.228 | có, tiêu đề cột | 312 / 326 dòng có giá trị |
| 15159657 | Busan Suyeong (부산수영) | 2022-09-30 | 840.758 | có, tiêu đề cột | 0 / 369 (trống) |
| 15159642 | Ulsan Onsan (울산온산) | 2020-09-01 | 440.176 | có, tiêu đề cột | 0 / 366 (trống) |
| 15159129 | Oido (오이도) | 2017-04-30 | 421.483 | có, tiêu đề cột | 0 / 465 (trống) |
| 15159125 | Nakdong (낙동강) | 2013-04-13 | 688.590 | chỉ theo mô tả, chưa xem file | chưa xem |
| 15159128 | Yeongdo (영도) | 2012-10-23 | 609.387 | chỉ theo mô tả, chưa xem file | chưa xem |

- **Biến và đơn vị:** 암모니아성질소 (ammonia-N). µg/L theo ghi chú trang Onsan và theo độ lớn ở Songdo; bộ Nakdong / Yeongdo ghi "Z~AG là mg/L", nên đơn vị phải kiểm từng file. Kèm nhiệt độ, độ mặn, DO, pH, độ đục, Chl, TN, TP, NO3, PO4 (khác nhau theo trạm), và kinh độ / vĩ độ ở Songdo, Busan, Onsan.
- **Tần suất:** dòng 5 phút. Ở đoạn Songdo 2017 (khoảng 2 ngày, sau khi sắp theo thời gian), **giá trị NH4 đổi theo mốc tròn giờ** (khoảng cách đổi chủ yếu 60 phút, đôi khi 120–180) và được giữ nguyên giữa hai lần đo → thực chất là chuỗi 1 h.
- **Năm:** chỉ biết ngày kết thúc theo tên file. Ngày bắt đầu chưa biết: file không theo thứ tự thời gian (Busan có 2013 và 2019 cạnh nhau; Songdo có một dòng cách hơn 32 ngày). Số dòng ở mức 5 phút tương đương khoảng 4–8 năm **nếu** liên tục, đây chỉ là suy luận.
- **Số trạm:** 6 file NH4 / 6 trạm; đều xếp loại "하구" (cửa sông) trong 4 file đã xem (Songdo, Busan, Onsan, Oido); hai trạm cuối chưa xem. Khí hậu ôn đới, gió mùa Đông Á; Songdo ở vùng triều lớn.
- **Cờ QC:** **không có** cột QC ở cả 4 file đã xem. Tiêu chí này không đạt.
- **Giấy phép:** 이용허락범위 제한 없음 (không giới hạn phạm vi sử dụng), theo trang và JSON catalog.
- **Cách tải:** trang ghi tải không cần đăng nhập; `https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=<FILE_ID>&fileDetailSn=1` trả HTTP 200 (Songdo `FILE_000000003648080`, 99,7 MB). `atchFileId` lấy qua `/tcs/dss/selectFileDataDownload.do`. **Không hỗ trợ Range**: phải tải cả file. Trang có đoạn mã xác thực giới hạn tải (`limitAtchFileId`); 5 lần tải thử của tôi không bị chặn, chưa rõ ngưỡng. Nếu bị chặn thì dừng, không vượt.
- **Đã xác minh:** cột NH4 ở 4 file; nhịp 1 h trên một đoạn ngắn Songdo; tải không đăng nhập; giấy phép; không có cờ QC; số dòng; tọa độ. 14 giá trị đầu của Songdo dao động mạnh: 157–747 µg/L, có ×2,1 trong 3 h (280 → 585, qua một giờ trống) — quan trọng với điều kiện "tỷ số ≥ ×3" của F4.
- **Chưa xác minh:** độ dài thật và số năm có NH4 của từng trạm; tỷ lệ có giá trị ngoài đoạn đầu (3/4 file đã xem trống hoàn toàn ở đoạn đầu; ở đó có thể đo bắt đầu muộn hơn hoặc không đo); loại thiết bị (nhịp 1 h gợi ý analyzer hóa ướt chứ **không chắc** là ISE, chưa có tài liệu); LOQ, hiệu chuẩn, lịch bảo trì (cần để phân biệt đổi thang tự nhiên / thật); giá trị bất thường đã thấy (nhiệt độ, độ mặn, độ dẫn cùng bằng 0 ở Busan 2019) cho thấy dữ liệu chưa làm sạch; file Nakdong, Yeongdo chưa mở.

**Lưu ý đã kiểm và loại khỏi bảng:** 15159659 Gwangyang: mô tả có 암모니아성질소 nhưng **file thật không có cột này** (tiêu đề cột đã đọc; 30.000 dòng). 15159130 Ulsan: mô tả không có NH4. Như vậy **mô tả trang không đáng tin**, 15159125 và 15159128 chưa thể tính là có NH4 cho tới khi xem file.

## Không lấy được

- **KOEM OpenAPI "하구 및 만" (data.go.kr 15059978):** có trường `nh4n`, cập nhật thời gian thực, giấy phép mở, nhưng bắt buộc `ServiceKey` → phải đăng ký → **không lấy được** theo ràng buộc. File KOEM từng trạm công khai (15044185…): theo mẫu Yeongsan-Mokpo trong máy và mô tả trang, không có NH4. Nếu chủ dự án đổi quyết định về đăng ký khóa miễn phí thì đây là nguồn đáng thử nhất; quyết định đó không thuộc phiên này.
- **OMES Zeeschelde (Bỉ, marineinfo.org dataset 1069):** "bán liên tục", 16 trạm, có từ khóa ammonium; truy cập theo phê duyệt của bên cung cấp → **không lấy được**. Tần suất NH4 chưa kiểm.

## Đã kiểm, không đạt

| Nguồn | URL | Biến / đơn vị | Tần suất | Năm | Số trạm | QC | Giấy phép | Cách tải | Đã xác minh | Chưa xác minh / Kết luận |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Skidaway River Estuary (SECOORA / IOOS) | `erddap.secoora.org/erddap/info/skidaway-river-estuary` | `ammonium_microg_l_1`, µg/L | **Khoảng hằng tuần, không phải cảm biến** | 2023→09/2026 | 1 | QARTOD có cột, nhưng `qc_agg` chỉ có giá trị 2 (chưa đánh giá) | Dùng tự do, trích dẫn | ERDDAP CSV | Dòng có NH4: 22 / 34 / 54 / 6 theo năm 2023–26; thời điểm các dòng 01–03/2024 cách nhau khoảng 1 tuần | Có vẻ là chương trình lấy mẫu hằng tuần tại cầu tàu SkIO (trang SkIO), chưa xác nhận trực tiếp. **Trượt tần suất** |
| ModMon Neuse / Pamlico (SECOORA) | `erddap.secoora.org` (`neuse-river-*`, `pamlico-sound-*`) | NH4 | Khảo sát tàu | Marker 64: 1994–2006 | khoảng 20 | Chưa kiểm | Như trên | ERDDAP | Dải thời gian Marker 64 từ thông báo ERDDAP | Các trạm khác chưa kiểm dải thời gian. **Trượt** |
| USGS NWIS | `api.waterdata.usgs.gov` / `waterservices.usgs.gov` | 00608 NH3+NH4 hòa tan, mg/L | **Không có chuỗi tức thời**; chỉ Daily Mean | 1990–2025 | 72 chuỗi | Có duyệt | Công khai | API mở | Dịch vụ site `iv`: 0 ở mọi bang đã thử (đối chứng GA 00010 = 127); OGC: 72 / 72 Daily Mean, kinh độ / vĩ độ thuộc vùng nội địa Trung Tây | Mã 00610, 00613, 62955 trả 0 chuỗi; có thể còn mã khác. **Trượt tần suất + không ven biển** |
| LOBO Elkhorn Slough (MBARI) | `www3.mbari.org/lobo/getLOBOdata.htm` | **Biểu mẫu không liệt kê ammonium** (có nitrate, DO, Turb…) | Giờ | 2003→ | khoảng 5 | Có mức chất lượng | Chưa kiểm | CGI công khai | Danh sách biến của biểu mẫu: không có NH4 | Bài AGU 2012 có nhắc phép đo NH4 tại chỗ; dữ liệu đó chưa thấy công khai. **Không tìm thấy NH4** |
| LOBO NERACOOS (Maine) | `data.ioos.us/dataset/lobo-70-casco-bay-1` | Nitrate, DO, Turb… | Giờ | Chưa kiểm | Nhiều | Chưa kiểm | Chưa kiểm | ERDDAP | Chỉ qua kết quả tìm kiếm | **Không thấy NH4** (máy chủ ERDDAP NERACOOS không đáp ứng thử) |
| IOOS / SECOORA / CeNCOOS ERDDAP | `erddap.sensors.ioos.us`, `erddap.cencoos.org`… | Tìm "ammonium", "ammonia", "NH4" | — | — | — | — | — | Search API | Trang đầu kết quả: chỉ Skidaway, ModMon, tàu khảo sát, glider, CTD | Chỉ đọc 30 mục đầu mỗi lượt, cộng 141 mục trang 2 IOOS (cỡ trang 200); mục 31–200 chưa xem. GCOOS: "ammonia", "NH4" lỗi; "ammonium" chỉ ra CTD. **Không tìm thấy; chưa vét hết** |
| EMODnet Chemistry | `erddap.emodnet.eu` | Ammonium, µmol/L | Khí hậu tháng | 1960–2023 | Lưới | — | Trích dẫn | ERDDAP | 6 bộ đều lưới DIVA | Kho CDI gốc chưa kiểm. **Trượt** |
| Thames catchment 2013–17 (UKCEH EIDC) | `doi.org/10.5285/793874b5-48b0-4971-8172-1cf97c35230f` | Ammonium (sonde Manta 2) | **2–4 tuần** cho chất lượng nước (theo trang CKAN) | 2013–17 | Chưa rõ | Chưa rõ | Trang CKAN ghi không có; bản BGS ghi OGL | ZIP | Mô tả trang CKAN | Đô thị, không ven biển. **Trượt** |
| Anh — quan trắc §82 Environment Act | `thameswater.co.uk/.../continuous-water-quality-monitoring` | Ammonia, DO, pH, Turb, T | Giờ (Thames Water) | Đang triển khai | — | — | — | Chưa có | Thames Water: công khai gần thời gian thực "by April 2030" | Công ty khác chưa kiểm. **Chưa có dữ liệu mở đã thấy**; đáng xem lại sau |
| Hamburg WGMN (Elbe triều) | `hamburg.de/.../blankenese-183170` | T, DO, pH, EC, Turb | Chưa rõ | 1979→ | 9 | Chưa rõ | Chưa rõ | Trang báo cáo | Blankenese: danh sách thiết bị không có NH4 | Seemannshöft, Bunthaus chưa kiểm chi tiết. **Không thấy NH4** |
| Cuxhaven FerryBox (Hereon / COSYNA) | `jerico-ri.eu/infrastructure/stationary-ferrybox-system` | "nutrients" | Chưa rõ | Chưa rõ | 1 | Chưa rõ | Mở theo mô tả | Cổng CODM | Tài liệu có nhắc dinh dưỡng; NH4 chỉ thấy ở phân tích theo mẻ trên tuyến phà 2002–05 | Cổng dữ liệu chưa mở. **Chưa xác nhận NH4** |
| Rijkswaterstaat (Lobith, Eijsden, Aqualarm) | `waterinfo.rws.nl`, `waterwebservices.rijkswaterstaat.nl` | Chưa rõ | Chưa rõ | — | — | — | — | API | Catalog POST trả rỗng; trang Aqualarm trên data.overheid 404 | **Chưa xác minh được, không kết luận**; và là sông, không phải ven biển. Báo cáo RIVM 2025-0075 so sánh cảm biến NH4 nhưng PDF không đọc được |
| Hồng Kông EPD | `epd.gov.hk`, `gov.hk/.../marinewater.htm` | NH3-N | Hằng tháng; phao thời gian thực có "vài chỉ số" | — | 76 / 12 | — | — | — | Chỉ qua kết quả tìm kiếm | Khớp ghi chú H4. **Trượt** |
| Úc | Tìm kiếm chung | — | — | — | — | — | — | — | Chỉ thấy tóm tắt hội nghị Griffith 2026, không dữ liệu | Chỉ một lượt tìm, chưa kiểm cổng từng bang. **Không tìm thấy** |
| PANGAEA, Zenodo, Dryad, HydroShare | Tìm kiếm chung | — | — | — | — | — | — | — | Chỉ thấy đợt ngắn (Columbia 2010 không rõ kho, chu kỳ triều Bahía Blanca) | Tìm qua web chung, chưa dùng tìm kiếm riêng từng kho. **Không tìm thấy** |

## Xếp hạng

1. **Songdo (15159658).** Là trạm duy nhất đã thấy NH4 thật, nhịp 1 h, cửa sông, có T / độ mặn đi kèm (điều kiện tham chiếu của F4), đuôi tới 2022. Thiếu QC, độ dài chưa biết.
2. **Busan Suyeong, Ulsan Onsan, Oido.** Có cột NH4 nhưng đoạn đầu trống; chưa biết có dữ liệu không.
3. **Nakdong, Yeongdo.** Chỉ có mô tả, mà mô tả từng sai (Gwangyang); file cũ (kết thúc 2013, 2012).
4. **KOEM OpenAPI.** Không lấy được khi không có khóa.

Không có nguồn nào khác đạt cả ≤ 1 h và công khai.

## Khuyến nghị: F5 có chạy được không

**Hiện chưa đủ để kết luận; có thể chạy một F5 hẹp, có điều kiện, sau một bước kiểm mà chủ dự án phải duyệt.**

Bước 0 (cần chủ dự án đồng ý vì phải tải trọn file, 70–140 MB mỗi file): tải Songdo, Busan, Onsan, Oido vào `data/foreign/` (ghi một lần) và tính: số năm có NH4, tỷ lệ có giá trị, đơn vị, LOQ, thời gian kẹt. Ngưỡng nên đặt **trước** khi tải; đề xuất: một trạm chỉ dùng khi có ≥ 1 năm với ≥ 70 % giờ có NH4.

Nếu qua bước 0, F5 trả lời được: "trên NH4 thật, ở các trạm này, ba điều kiện của F4 có bật giả nhiều không". Đó là thứ F4 chưa đo. Các giới hạn phải ghi trong đăng ký:

- **Số trạm ít (1–4).** F4 dùng CI khối trạm trên 33 trạm NERRS với khoảng 14–15 vị trí giữ lại cho FM; ở đây CI khối trạm không có nghĩa. Chỉ báo cáo theo từng trạm, không tổng quát hóa thành "NH4 nói chung".
- **Không có cờ QC.** Không có "dữ liệu sạch" đáng tin để làm đáp án. Sự cố thật trong dữ liệu sẽ trùng với "thay đổi tự nhiên", nên hại đo được bị nhiễu theo cả hai hướng; QC tự làm phải đặt trước, và phải báo cáo độ nhạy.
- **Khác thiết bị.** NB1 có lẽ là ISE đọc 1–3 phút; nguồn này có lẽ analyzer đọc 1 h. Hình dạng sự cố đổi thang của NB1 (bậc 1 mẫu ở 1 phút) không tương đương. Nhiễu sau bậc khác (RL-76).
- **Ngưỡng F2 / F4 không chuyển thẳng được.** Bộ phát hiện `step` (w = 1 h ở bước 15 phút), `stuck` và điều kiện (i) "≤ 2 mẫu" đều phụ thuộc nhịp lấy mẫu. Ở 1 h, "≤ 2 mẫu" là 2 giờ. Dữ liệu 5 phút giữ nguyên giá trị sẽ kích hoạt `stuck` giả nếu không hạ về 1 h. Đổi các thông số này là **thiết kế mới**, không phải lặp lại F4.
- **Đây vẫn không phải kiểm định độc lập cho F4 như đã đăng ký.** F5 phải có đăng ký riêng, commit trước khi chấm, và nêu rõ đã xem đoạn nhỏ Songdo trong rà soát này.

Dấu hiệu sớm, chưa phải kết quả: 14 giờ đầu ở Songdo đã có biến động ×2 trong 3 h. Nếu trạm này cũng thường đạt ×3 thì điều kiện (iii) sẽ bật giả như Turb, nhưng cần dữ liệu để biết.

## Nếu không chạy F5, hoặc bước 0 trượt: thu hẹp kết luận của bài

- Chỉ được nói: "trên sự cố **lý tưởng hóa, gắn lên DO / Turb / pH** của mạng đã QC (NERRS), căn mức tự động có giới hạn gây hại vượt ngưỡng; nguyên nhân chính là Turb tự nhiên và DO gần 0".
- **Không** được nói căn mức tự động có hại trên NH4; hại trên NH4 chưa được đo. Bài phải nêu rõ biến của sự cố thật (NH4) không có trong tập chấm, và không có nguồn NH4 liên tục công khai đạt yêu cầu, đây cũng là một phát hiện của bài.
- NB1 chỉ dùng làm minh họa một trạm không có đáp án: ba điều kiện nhận đúng E1, E3 trên NH4, bật nhầm khi COD thoát kẹt (RL-79).
- Khuyến nghị vận hành giữ dạng thận trọng: dùng ba điều kiện làm **gợi ý** cho người xác nhận, không phải quy tắc đã được chứng minh là không an toàn hoặc an toàn trên NH4.

## Nguồn đã dùng

- data.go.kr: [15159658](https://www.data.go.kr/data/15159658/fileData.do), [15159657](https://www.data.go.kr/data/15159657/fileData.do), [15159642](https://www.data.go.kr/data/15159642/fileData.do), [15159129](https://www.data.go.kr/data/15159129/fileData.do), [15159125](https://www.data.go.kr/data/15159125/fileData.do), [15159128](https://www.data.go.kr/data/15159128/fileData.do), [15159659](https://www.data.go.kr/data/15159659/fileData.do), [15059978 (OpenAPI)](https://www.data.go.kr/data/15059978/openapi.do)
- [SECOORA ERDDAP Skidaway](https://erddap.secoora.org/erddap/info/skidaway-river-estuary/index.html), [Chương trình Skidaway River](https://www.skio.uga.edu/research/biological-oceanography/skidaway-river-monitoring-program/), [IOOS ERDDAP](https://erddap.sensors.ioos.us/erddap/index.html), [EMODnet ERDDAP](https://erddap.emodnet.eu/erddap/index.html)
- [USGS time-series metadata](https://api.waterdata.usgs.gov/ogcapi/v0/collections/time-series-metadata), [MBARI LOBO GetLOBOData](https://www3.mbari.org/lobo/getLOBOdata.htm), [OMES](https://marineinfo.org/id/dataset/1069)
- [Thames catchment 2013–17](https://ckan.publishing.service.gov.uk/dataset/fcfc6d5f-a3a9-4a29-b9b1-e9a73f67ff28), [Thames Water CWQM](https://www.thameswater.co.uk/about-us/performance/river-health/river-quality/continuous-water-quality-monitoring), [Hamburg Blankenese](https://www.hamburg.de/politik-und-verwaltung/behoerden/bukea/hu/umweltuntersuchungen/wasseruntersuchungen/blankenese-183170), [FerryBox Cuxhaven](https://www.jerico-ri.eu/infrastructure/stationary-ferrybox-system/), [HK EPD](https://www.gov.hk/en/residents/environment/water/water/marinewater.htm)
