# Độ tin cậy của các nguồn dữ liệu mở và nguồn chính thống thay thế (2026-10-24)

Câu hỏi của chủ dự án: **các nguồn dữ liệu mở đang dùng có đủ tin cậy không, và có nguồn chính thống hơn không?**

Trạng thái: đánh giá tài liệu + đối chiếu kết quả đã có trong repo. Không chạy thí nghiệm mới, không sửa code.
Các trang web được mở thử ngày 24/10/2026 từ máy dev. "Mở được" nghĩa là tải được không cần đăng nhập vào lúc đó.
Số [n] là tài liệu ở cuối. "RL-nn" là mục trong `docs/research-log.md`.

## Tóm tắt

1. Không nguồn mở nào đo **tại lồng**. Tất cả là mô hình 8–27 km, ảnh vệ tinh hoặc trạm cách xa. Đổi nguồn không xóa được giới hạn này.
2. **Gió dự báo** (Open-Meteo, ECMWF IFS 0,25°): dùng được. Có kỹ năng cấp 6 tới ~4 ngày (RL-31). Giữ.
3. **Open-Meteo marine** là bản phân phối lại của mô hình Météo-France (MFWAM, SMOC, SST 0,08°) [5]. Đây cũng là các sản phẩm CMEMS. Đổi sang CMEMS **không làm dữ liệu mịn hơn**, nhưng cho tên phiên bản, tài liệu kiểm định và tải cả vùng bằng một lần gọi.
4. **Hạn mức Open-Meteo là rủi ro thật.** Nếu mỗi điểm tính là một lượt gọi, bản đồ ở commit hiện tại (358 điểm, 30 phút) dùng ~34.000 lượt/ngày, gấp 3,4 lần mức miễn phí 10.000 [1]. Bản đang sửa (154 + 108 nút) vẫn ~12.600/ngày. Worker nuốt lỗi, nên vượt hạn mức chỉ thấy là bản đồ "cũ".
5. **Bão:** nguồn chính thống là bản tin Trung tâm Dự báo KTTV quốc gia (NCHMF). Theo QĐ 18/2021, cơ quan KTTV là nơi ban hành tin bão và cấp độ rủi ro [25]. Bản tin chỉ là HTML/ảnh, không có API. JMA có luồng XML mở [34]. ECMWF ensemble giữ vai trò "theo dõi sớm".
6. **Thủy triều:** NCHMF phát hành bản tin thủy triều 10 ngày dạng PDF, có trạm **Hòn Dáu** (~26 km từ NB1) [23]. Đây là nguồn chính thống tốt nhất tìm được. Không tìm thấy trạm triều thời gian thực mở cho Hòn Dáu.
7. **Nhiệt độ nước:** GLORYS12 gần sensor nhất (MAE 0,65 °C, RL-44); OISST 0,25° không bắt được ngày nóng (POD 0). Có thể thử MUR 1 km [13] hoặc Himawari 2 km [14].
8. **Độ sâu:** GEBCO 2024 là lựa chọn đúng (RL-45); GEBCO 2025 đã phát hành [15]. Chỉ ~2,7 % ô có đo. Hải đồ chính thức không tìm thấy bản mở.
9. **Chất lượng nước nuôi:** có bản tin quan trắc của Viện NC NTTS I và các tỉnh, nhưng chỉ dạng PDF, lấy mẫu thưa. Không tìm thấy bản tin cho Hải Phòng / Quảng Ninh.
10. **Vẫn không tin được dù đổi nguồn:** DO, độ mặn, NH4 tại lồng; dòng chảy trong luồng hẹp; sóng trong vịnh kín; mầm bệnh.

## 1. Bảng tổng hợp

Mức phù hợp: **Tốt** = dùng như hiện tại; **Có điều kiện** = dùng được nếu ghi rõ giới hạn; **Không phù hợp** = không nên dùng cho mục đích đó.

| Nguồn | Dùng cho | Độ phân giải | Bằng chứng (tài liệu + repo) | Giấy phép / truy cập | Mức phù hợp | Thay thế chính thống hơn |
| --- | --- | --- | --- | --- | --- | --- |
| Open-Meteo forecast, `ecmwf_ifs025` (hazard runner) | Gió, giật, mưa tại trạm | 0,25° (~27 km), giờ, 6 giờ/lần chạy [4] | Cấp 6: CSI 0,58 lead 1, ≥ 0,44 tới lead 4 (RL-31). Kiểm so với ERA5, không có gió đo tại lồng | CC BY 4.0, phi thương mại, < 10.000 lượt/ngày [2] | **Tốt** | Bản tin NCHMF làm tham chiếu chính thức; ECMWF Open Data 0,1° (từ 20/10/2026) [10] |
| Open-Meteo forecast, `best_match` (research-map) | Lớp gió, mưa trên bản đồ | Việt Nam: chỉ mô hình toàn cầu [4] | Không đánh giá riêng; RL-31: best_match CSI 0,22 so với ifs025 0,58 | như trên | **Có điều kiện** | Ghi `models=` (decisions #18) |
| Open-Meteo marine: sóng | Lớp sóng | MFWAM 0,08°, 12 giờ/lần [5] | Yagi: 2,58–2,86 m, gần CMEMS MFWAM 2,35–3,14 m (RL-44). Ô 8 km không thấy đảo che | CC BY 4.0 | **Có điều kiện** (biên ngoài khơi) | CMEMS WAV_001_027 (cùng MFWAM) [41] |
| Open-Meteo marine: dòng chảy (SMOC) | Lớp dòng chảy, phơi nhiễm | 0,08°, 24 giờ/lần [5] | p95 SMOC gấp ~2,4 lần GLO12 (RL-44). Delft3D công bố Cửa Lục > 1 m/s, SMOC p95 ≤ 0,47 (RL-39). Tài liệu: "Accuracy at coastal areas is limited" [5] | CC BY 4.0 | **Có điều kiện** | CMEMS GLO12 [8]; không có mô hình ven bờ mở |
| Open-Meteo marine: `sea_level_height_msl` | Mực nước, đặc trưng triều B6 | 0,08° [5] | B6 giúp pH ở RL-08, bị bác ở RL-18 trên dữ liệu sạch. Tài liệu: "không thay lịch thủy triều hàng hải" [5] | CC BY 4.0 | **Có điều kiện** | **Bản tin thủy triều Hòn Dáu (NCHMF)** [23] |
| Open-Meteo marine: SST (best_match) | Nắng nóng, gieo ngày | MeteoFrance SST 0,08° [5] | So với sensor: bias +0,80, MAE 0,91, r 0,68 (RL-44) | CC BY 4.0 | **Có điều kiện** (trừ bias) | GLORYS12/GLO12 (RL-44), MUR [13] |
| Open-Meteo archive `models=era5` | "Giá trị thật" gió, mưa, nhiệt độ không khí | 0,25°, giờ, trễ 5 ngày [6] | ERA5 đọc thấp lõi bão [19]. Yagi tại NB1: ERA5 18,86 m/s, IFS 9 km 29,56 m/s (RL-31) | CC BY 4.0 (qua Open-Meteo) | **Có điều kiện** (cận dưới khi có bão) | Không có trạm gió đo mở gần lồng |
| Open-Meteo Previous Runs (`ecmwf_ifs025`) | Đánh giá thời gian báo trước | Có từ 01/2024 [7] | Dùng ở RL-31; lead 0 phải khác giá trị thật (decisions #18) | CC BY 4.0 | **Tốt** (cho nghiên cứu) | Single Runs API của Open-Meteo nếu cần cả lần chạy [7] |
| ECMWF Open Data, quỹ đạo bão BUFR | Theo dõi bão thời gian thực | ENS 51 thành viên + HRES | 414/414 cặp khớp TIGGE (RL-41) | CC BY 4.0, dùng thương mại được [10] | **Tốt** | Bản tin NCHMF / JMA làm tham chiếu |
| TIGGE (NCAR d330003) | Quỹ đạo dự báo lịch sử | 00/12 UTC | 7/7 cơn ≤ 200 km được báo, trung vị 93 h (RL-37) | CC BY 4.0, phi thương mại (storm-basin eval) [42] | **Tốt** (nghiên cứu) | — |
| IBTrACS v04r01 | Khí hậu bão, oracle | 3 giờ; cập nhật 3 lần/tuần, có phần "provisional" [11] | Tái hiện Yagi ≥ cấp 11 (RL-29). Gió giữa các cơ quan khác thời gian lấy trung bình [11] | Mở, WMO Res. 40 [11] | **Tốt** | Best track RSMC Tokyo gốc [33] (IBTrACS đã gộp) |
| NOAA OISST v2.1 | Khí hậu nhiệt độ nước 1982– | 0,25°, ngày [12] | So với sensor: r 0,37, POD ≥ 31 °C = 0 (RL-44, RL-32) | NOAA, mở | **Có điều kiện** (chỉ khí hậu) | MUR 0,01° [13]; GLORYS12 1/12° |
| CMEMS GLORYS12 / GLO12 | Nhiệt độ, độ mặn, dòng | 1/12°, ngày/giờ [8] | GLORYS12: bias +0,39, MAE 0,65, r 0,72; độ mặn không xuống dưới 28,2 psu (RL-44) | Miễn phí, cần đăng ký [8] | **Có điều kiện** | Không có sản phẩm khu vực cho vịnh Bắc Bộ (RL-44) |
| CMEMS MFWAM | Sóng | 1/12°, 3 giờ, 10 ngày [41] | Yagi 2,35–3,14 m, ô đồng đều (RL-44) | Miễn phí, cần đăng ký | **Có điều kiện** (biên ngoài khơi) | Không có mô hình sóng ven bờ mở |
| GEBCO 2024 (+TID) | Độ sâu mặc định | 15″ (~460 m) | Sửa hố sai của ETOPO; 2,7 % ô có đo (RL-45) | Public domain, ghi công; **không dùng cho hàng hải** [15] | **Có điều kiện** | GEBCO 2025 [15]; hải đồ (không mở); đo sâu tại lồng |
| NOAA ETOPO 2022 | So sánh | 15″ [45] | Hố sai Cửa Lục 45 m, Vân Đồn 72 m (RL-45) | NOAA, mở | **Không phù hợp** làm mặc định | GEBCO |
| Copernicus SDB 100 m | Bãi triều | 100 m | 0 ô hợp lệ ở Cát Bà / Hạ Long (RL-36) | — | **Không phù hợp** cho vùng lồng | ICESat-2 ATL24 (xem mục 3.4) |
| Copernicus GLO-30 DEM | Che chắn gió | 30 m, DSM [16] | Sai số đứng < 4 m (LE90) [16]. Đường cong chắn gió 2-D là giả định (RL-39) | Miễn phí toàn cầu, ghi công [16] | **Tốt** | — |
| OpenStreetMap | Mặt nạ nước, đà gió | vector | NB16 lệch 884 m vào mặt nước (RL-39) | ODbL [43] | **Tốt** (có kiểm tay) | Bản đồ địa hình nhà nước (không mở) |
| GreenLab 06M26042804 | Sự thật tại lồng | 1–3 phút, 1 trạm | COD hỏng, pH trôi từ 19/09, đơn vị NH4 chưa xác nhận, 16 ngày thiếu (AGENTS.md, RESULTS.md) | Riêng | **Có điều kiện** (nguồn thật duy nhất) | Không có; cần hiệu chuẩn định kỳ |

## 2. Nhận xét từng nhóm nguồn

### 2.1. Open-Meteo forecast (gió, mưa)

- Ở Việt Nam, `best_match` **chỉ dùng mô hình toàn cầu** (ICON, GFS, IFS). Mô hình khu vực mịn chỉ có ở châu Âu, Bắc Mỹ, Nhật… [4].
- `core/hazard_runner.py` đã cố định `ecmwf_ifs025`. Đây là lựa chọn có bằng chứng: CSI cấp 6 lead 1 là 0,58, so với gfs 0,45 và best_match 0,22 (RL-31).
- Research-map (`providers.py`) **không truyền `models=`**, nên lớp gió/mưa trên bản đồ là best_match. Điều này trái với decisions #18 (phải ghi tên mô hình).
- Giới hạn: kiểm định chỉ so với ERA5, không có gió đo tại lồng. ERA5 đọc thấp gió lõi bão [19].
- ECMWF mở dữ liệu 0,1° (nội suy từ mô hình ~9 km) từ 20/10/2026 [10]. Có thể tải một file GRIB cho cả vùng thay cho hàng trăm điểm Open-Meteo.

### 2.2. Open-Meteo marine (sóng, dòng chảy, mực nước, SST)

- Bảng mô hình của Open-Meteo [5]: MFWAM 0,08° (12 giờ/lần), SMOC dòng chảy + thủy triều 0,08° (24 giờ/lần), MeteoFrance SST 0,08° (24 giờ/lần). Cả ba là sản phẩm toàn cầu của Mercator / Météo-France trong CMEMS [8][41].
- Vì vậy so sánh "Open-Meteo marine với CMEMS" **không phải hai nguồn độc lập** (RL-44 đã cảnh báo cho sóng).
- Open-Meteo tự ghi: "Accuracy at coastal areas is limited" và "not suitable for coastal navigation and does not replace your nautical almanac" [5].
- Kết quả repo: dòng SMOC p95 0,11–0,47 m/s, GLO12 0,09–0,15 m/s (RL-44). Cả hai không thấy dòng siết > 1 m/s ở Cửa Lục (RL-39).
- Mực nước SMOC được dùng làm đặc trưng triều B6. B6 giúp pH ở RL-08 nhưng bị bác ở RL-18 trên dữ liệu pH sạch.
- Hỏi mỗi 30 phút là thừa: MFWAM chỉ đổi 12 giờ/lần, SMOC và SST 24 giờ/lần [5].

### 2.3. Hạn mức Open-Meteo và research-map

Hạn mức miễn phí: 600/phút, 5.000/giờ, **10.000/ngày**, 300.000/tháng [1]. Chỉ cho mục đích phi thương mại [2].

Cách đếm có hai cách đọc:

- Trang giá [1]: yêu cầu "hơn 10 biến hoặc hơn 2 tuần **cho một địa điểm**" mới bị tính nhiều lượt. Đọc theo câu này: mỗi địa điểm ít nhất 1 lượt.
- Bài blog 11/2023 [3]: `weight = nLocations × (nDays/14) × (nVariables/10)`. Nếu áp dụng nguyên công thức (không có mức sàn 1), yêu cầu ngắn tính rất nhẹ.

Chưa xác định được cách nào đang áp dụng. Bảng dưới tính cả hai. Research-map hỏi 2 ngày dự báo, 4 biến thời tiết, 6 biến marine, 48 lần/ngày.

| Cấu hình | Địa điểm mỗi lần | Lượt/ngày nếu sàn 1/điểm | Lượt/ngày theo công thức [3] |
| --- | --- | --- | --- |
| Commit hiện tại (HEAD): 358 điểm × 2 API | 716 | **~34.400** (vượt 3,4 lần) | ~2.450 |
| Bản đang sửa (chưa commit): lưới 0,125°, 154 nút thời tiết + 108 nút marine (đếm ngày 24/10) | 262 | **~12.600** (vượt 1,26 lần) | ~870 |
| Bản đang sửa, nhưng 60 phút/lần | 262 | ~6.300 | ~435 |
| Hazard runner: 14 trạm × 2 API, mỗi giờ (nếu task chạy) | 28 | ~670 | ~670 (13 ngày < 14) |

- Mọi nguồn gọi từ cùng máy dùng chung hạn mức (tính theo IP [2]).
- Theo cách đọc "sàn 1/điểm", commit hiện tại cũng vượt mức **600/phút** (716 điểm trong vài giây).
- Không thấy chuỗi "429" hay "Daily API request limit" trong `runtime/logs/hazard-jobs.log`. Chưa kiểm log worker Docker / Postgres.
- `worker.run_once` bắt mọi lỗi và trả `False`, giữ snapshot cũ. Nếu bị chặn, bản đồ chỉ chuyển sang "cũ" sau 90 phút mà không ghi lý do.
- Lưới 0,125° của bản đang sửa gần lưới IFS 0,25° / marine 0,08° hơn lưới ~1,2 km cũ (RL-36), nên ít điểm thừa hơn. Nút thời tiết vẫn dày gấp ~4 lần ô IFS 0,25°.

### 2.4. ERA5 và Previous Runs

- ERA5 qua Open-Meteo: 0,25°, trễ 5 ngày; best_match của archive ghép IFS 9 km từ 2017 [6]. Đây là lỗi đã gặp ở RL-31.
- ERA5 đọc thấp cường độ bão, đỉnh muộn hơn IBTrACS với bão mạnh [19]. Ở Yagi: 18,86 m/s so với ≥ cấp 11 theo best track (RL-29, RL-31). ERA5 là **cận dưới** khi có bão.
- Previous Runs có `ecmwf_ifs025` từ 01/2024 [7]. Nên chỉ đánh giá được 3 mùa bão.

### 2.5. ECMWF Open Data, TIGGE, IBTrACS

- ECMWF Open Data: CC BY 4.0, dùng thương mại được, có quỹ đạo bão [10]. Trang ECMWF ghi chỉ giữ ~12 lần chạy gần nhất (~2–3 ngày) [10]; RL-41 ghi ~4 ngày. Cần kiểm lại, vì task 6 giờ/lần bỏ lỡ hơn 2 ngày sẽ mất dữ liệu.
- IBTrACS v04r01 cập nhật 3 lần/tuần; mùa gần nhất là "provisional" [11]. Gió giữa các cơ quan dùng thời gian lấy trung bình khác nhau [11]. Repo đã ưu tiên TOKYO và nhân USA × 0,93 (RL-29, RL-33).

### 2.6. Nhiệt độ nước (OISST, CMEMS, nguồn thay thế)

- OISST: 0,25°, ngày, ghép vệ tinh + tàu + phao [12]. Ô gần nhất cách NB1 ~13 km. So với sensor: r 0,37, POD ≥ 31 °C = 0 (RL-44). Chỉ dùng cho khí hậu và lịch (RL-32).
- GLORYS12 tốt nhất trong các sản phẩm đã thử: bias +0,39, MAE 0,65, r 0,72, POD 0,86 (RL-44). GLO12 ấm hơn ~1 °C.
- Thay thế đáng thử, chưa đánh giá trong repo:
  - **MUR SST v4.1**: 0,01° (~1 km), ngày, 2002–nay; có trên NOAA CoastWatch ERDDAP, không cần đăng nhập [13].
  - **Himawari SST (JAXA P-Tree)**: 2 km, 10 phút / giờ / ngày; bản gần thời gian thực xóa sau 72 giờ [14].
  - Cả hai là nhiệt độ bề mặt từ vệ tinh, bị mây che; ô ven bờ vẫn có thể lẫn đất.

### 2.7. Độ sâu, địa hình, mặt nước

- GEBCO: 15″, có lớp TID; public domain, ghi công; "**should NOT be used for navigation**" [15]. GEBCO 2025 phát hành 8/2025 [15]; repo đang dùng bản 2024 (decisions #21).
- ETOPO 2022: 15″/30″/60″ [45]. Có hố sâu sai ở cửa sông (RL-45). Giữ làm lớp so sánh.
- SDB 100 m: 0 ô ở vùng lồng (RL-36). Phương pháp quang học cần nước trong.
- GLO-30: DSM 30 m (gồm nhà, cây), sai số đứng < 4 m LE90, nguồn TanDEM-X 2011–2015 [16]. Đủ cho che chắn gió của núi đá vôi.
- OSM: ODbL [43]. Đường bờ ven đảo có thể lệch vài trăm mét (RL-39).

### 2.8. Sensor GreenLab

- Là nguồn đo tại lồng duy nhất. Không có thay thế.
- Vấn đề đã biết (AGENTS.md, RL-18, RESULTS.md): COD hỏng phần lớn mùa; pH trôi từ 19/09; đơn vị NH4 chưa được nhà cung cấp xác nhận; 16 ngày thiếu do phía nhà cung cấp; không có DO, độ mặn.
- Không có hiệu chuẩn độc lập (mẫu nước gửi phòng thí nghiệm). Đây là điểm yếu lớn nhất của "sự thật" trong repo.

## 3. Nguồn chính thống Việt Nam và khu vực

Kiểm ngày 24/10/2026, không đăng nhập, không vượt tường phí.

| Nguồn | Có gì | Truy cập thực tế | Kết luận |
| --- | --- | --- | --- |
| **NCHMF – tin bão** [20][21] | Bảng 24/48/72 h: vị trí, hướng/tốc độ, cường độ (cấp gió, giật), vùng nguy hiểm, **cấp độ rủi ro thiên tai**; ảnh GIF quỹ đạo. Bản xem thử ra 14:00, hẹn bản sau 17:00 | HTML + ảnh, mở được. Không thấy API, XML, KML. Link RSS trả **404**. Không thấy kho lưu trữ máy đọc được (storm-basin eval) | Tham chiếu chính thức. Đọc làm đối chiếu, không làm dữ liệu đầu vào |
| **NCHMF – thủy triều** [22][23] | Bản tin 10 ngày, PDF: giờ và độ cao nước lớn / nước ròng (cm) mỗi ngày. Trạm phía Bắc: Cô Tô, Bạch Long Vỹ, **Hòn Dáu**, Sầm Sơn | PDF mở được, đường dẫn theo mẫu `kttv.gov.vn/upload/haivan/YYYY/M/D/dbqg-tthv-YYYYMMDD_0930.pdf`. Ví dụ 25/03–03/04/2026: Hòn Dáu cao 216–347 cm, thấp 26–154 cm | Nguồn triều chính thống tốt nhất. Chỉ 4 giá trị/ngày; mốc độ cao chưa ghi trên trang đã xem; Hòn Dáu cách NB1 ~26 km |
| NCHMF – sóng [24] | Bản tin sóng 10 ngày dạng ảnh bản đồ | Ảnh, không có số | Chỉ để đối chiếu bằng mắt. Mô hình nghiệp vụ không ghi trên trang; bài báo cho thấy NCHMF dùng SWAN và hệ tổ hợp sóng [38][39] |
| Cục Quản lý đê điều và PCTT (VNDMA) [26] | Báo cáo nhanh, thiệt hại; liên kết tới VNDMS | Trang mở được | Nguồn tốt cho **thiệt hại** sau bão (đối chiếu RL-38) |
| VNDMS (vndms.gov.vn) [26] | Mưa, mực nước, gió, cảnh báo triều cường, xâm nhập mặn | Bản đồ xem được; phần dữ liệu cần **đăng nhập**. Không thấy API | Không dùng làm nguồn tự động |
| Trạm triều Hòn Dáu: PSMSL / UHSLC / IOC [27][28] | PSMSL 841: trung bình tháng 1957–2013; số liệu giờ ngừng 2001 | Mở, nhưng là chuỗi lịch sử. Không thấy trạm Việt Nam trong danh sách IOC (danh sách dài, có thể bị cắt khi đọc; chưa chắc) | Không có mực nước đo thời gian thực mở |
| Hải đồ (VMS-North, Hải quân) [29] | Hải đồ giấy / ENC | vms-north.vn **không kết nối được** từ máy này. ENC của UKHO cho Việt Nam chỉ phủ Vũng Tàu và là hàng bán [29] | Chưa xác minh. Cần mua hoặc xin |
| IMER (Viện TN&MT biển, Hải Phòng) [30] | Nghiên cứu môi trường vịnh Hạ Long, Hải Phòng | imer.ac.vn **không kết nối được**. Không thấy cổng dữ liệu | Dữ liệu qua hợp tác / bài báo, không mở |
| Quan trắc môi trường nuôi thủy sản (Viện NC NTTS I; Chi cục Thủy sản tỉnh) [31][32] | Trung tâm quan trắc cảnh báo miền Bắc (từ Huế trở ra) [31]; tỉnh ra thông báo theo đợt (ví dụ Cà Mau "đợt 21/2025") [32] | PDF ký số. **Không tìm thấy** bản tin cho Hải Phòng / Quảng Ninh | Nguồn DO/độ mặn chính thống duy nhất, nhưng thưa và xa lồng |
| **JMA / RSMC Tokyo** [33][34][35] | Best track 1951–2026 (mở) [33]; luồng Atom XML công khai có "台風解析・予報情報（５日予報）" [34]. Sai số vị trí chính thức 2024: 71/106/152 km ở 24/48/72 h [35] | Mở, máy đọc được | Nguồn quốc tế chính thức tốt nhất cho bão Tây Bắc Thái Bình Dương |
| HKO [36][37] | XML quỹ đạo bão trên data.gov.hk [36]; sai số 2019: 84/144/205 km ở 24/48/72 h [37] | Mở | Đối chiếu thứ hai |
| JTWC | Cảnh báo, best track | HTTP 403 từ máy này (storm-basin eval). Gió 1 phút, phải nhân hệ số (RL-33) | Không dùng |
| SEAFDEC OFDS [40] | Hệ dự báo trình diễn 12,5 km, 3 ngày (theo tin trên trang SEAFDEC) | Chưa mở được cổng | Thô hơn CMEMS; không chính thống cho Việt Nam |
| **ICESat-2 ATL24** [17][18] | Độ sâu ven bờ dọc vệt quỹ đạo, 2018–nay | Miễn phí, cần tài khoản Earthdata [17] | Thấy đáy tới ~1 độ trong Secchi, nước trong (Kd490 0,05–0,12 m⁻¹) [18]. **Suy luận:** nước đục vịnh Hải Phòng / Cát Bà khó dùng được; chưa kiểm |
| SDB từ Sentinel-2 / Landsat | Độ sâu từ ảnh quang học | Tự làm được | Cùng giới hạn độ trong như SDB 100 m (RL-36) |

Về pháp lý: QĐ 18/2021/QĐ-TTg giao cơ quan KTTV ban hành tin dự báo, cảnh báo bão và cấp độ rủi ro thiên tai [25]. Mọi đầu ra của repo phải giữ nhãn shadow, không trình bày như cảnh báo chính thức (hard rule 4).

## 4. Khuyến nghị theo thứ tự ưu tiên

| # | Việc | Loại | Công sức | Lý do |
| --- | --- | --- | --- | --- |
| 1 | Giảm lượt gọi Open-Meteo của research-map: marine 3–6 giờ/lần (mô hình chỉ đổi 12–24 giờ/lần), thời tiết 60 phút; bỏ trùng điểm cùng ô mô hình; **ghi log lỗi HTTP** thay vì nuốt lỗi | Sửa | Nhỏ | Tránh vượt 10.000/ngày (mục 2.3); thấy được khi bị chặn |
| 2 | Truyền `models=ecmwf_ifs025` (hoặc tên mô hình cụ thể) cho lớp gió/mưa của research-map | Sửa | Nhỏ | decisions #18; best_match có CSI thấp nhất (RL-31) |
| 3 | Lớp dòng chảy, mực nước, sóng của bản đồ lấy từ **CMEMS** (GLO12, MFWAM) bằng một lần tải cả vùng | Thay | Nhỏ–vừa: `app/copernicus.py` và biến `COPERNICUS_*` đã có, cần tài khoản + cấu hình | Không mịn hơn, nhưng có phiên bản, QUID [9], ít lượt gọi; thêm độ mặn, MLD |
| 4 | Thêm bản tin **NCHMF** (bão) và luồng **JMA XML** làm "tham chiếu chính thức" bên cạnh ECMWF ensemble; ghi lệch giữa hai bên | Thêm | Vừa (đọc HTML/XML, chỉ lưu, không ra quyết định) | Nguồn có thẩm quyền theo QĐ 18 [25]; JMA máy đọc được [34] |
| 5 | Lưu bản tin thủy triều **Hòn Dáu** (PDF 10 ngày) mỗi ngày; so với `sea_level_height_msl` của SMOC tại NB1 | Thêm | Vừa (chưa kiểm PDF có lớp chữ hay chỉ là ảnh) | Nguồn triều chính thống; kiểm được độ lệch pha/biên độ của mô hình |
| 6 | Thử **MUR SST** (và Himawari nếu đăng ký) so với sensor như RL-44 | Thêm (thí nghiệm) | Nhỏ | Có thể tốt hơn OISST ở ven bờ; chưa có bằng chứng |
| 7 | GEBCO 2024 → **GEBCO 2025**; so ô TID quanh lồng | Nâng cấp | Nhỏ | Bản mới hơn; xem có thêm ô đo không |
| 8 | Hiệu chuẩn sensor: lấy mẫu nước định kỳ gửi phòng thí nghiệm (pH, NH4, DO, độ mặn); xin xác nhận đơn vị NH4 | Thêm | Vừa–lớn (ngoài phần mềm) | "Sự thật" hiện chưa được kiểm độc lập |
| 9 | Liên hệ Viện NC NTTS I / Chi cục Thủy sản Hải Phòng xin số liệu quan trắc vùng nuôi Cát Bà | Thêm | Không biết trước (thủ tục) | Nguồn DO/độ mặn chính thống duy nhất |
| — | **Giữ:** `ecmwf_ifs025` cho gió tại trạm; ECMWF Open Data + TIGGE cho bão; IBTrACS cho khí hậu; GEBCO; GLO-30; OSM; ERA5 (ghi là cận dưới khi có bão) | Giữ | — | Có bằng chứng trong RL-29…RL-45 |
| — | **Không dùng làm mặc định:** ETOPO, SDB 100 m, OISST cho cảnh báo ngày, JTWC | Bỏ / chỉ so sánh | — | Mục 1 |

## 5. Những gì vẫn không tin được dù đổi nguồn

- **DO, độ mặn, NH4 tại lồng.** Không sản phẩm mở nào đo DO hay NH4. Trên 94 trạm HK EPD, DO/TSS/NH3 không có bán kính đại diện nào; nhiệt độ và độ mặn chỉ ~5 km (RL-14). GLORYS12 không xuống dưới 28,2 psu trong khi Vân Đồn báo 20 psu (RL-44).
- **Dòng chảy trong luồng hẹp** (Cửa Lục > 1 m/s theo Delft3D công bố): mô hình 8 km không phân giải (RL-39, RL-44).
- **Sóng trong vịnh kín:** ô 8 km không thấy đảo che; chỉ có ước lượng SPM theo đà gió (RL-39), chưa có sóng đo.
- **Gió tại lồng khi có bão:** mô hình 9–27 km đọc thấp lõi bão; không có trạm đo gần lồng.
- **Mầm bệnh, tảo độc:** không có nguồn mở; chỉ số dịch bệnh chưa có kỹ năng so với khí hậu (RL-34, RL-42).
- **Độ sâu tại lồng:** ~97 % ô GEBCO là nội suy (RL-45). Cần đo sâu tại chỗ hoặc hải đồ.

## 6. Chưa xác minh được

- Open-Meteo có tính sàn 1 lượt cho mỗi địa điểm hay không (mục 2.3).
- Mốc độ cao (số 0 trạm / số 0 hải đồ) của bản tin triều NCHMF; PDF có lớp chữ hay không.
- Ai phát hành bảng thủy triều năm cho Hòn Dáu (trang thuvienphapluat trả 403); vms-north.vn và imer.ac.vn không kết nối được từ máy này. Không có nghĩa là các trang này không tồn tại.
- Thời gian ECMWF giữ file Open Data: trang ghi ~2–3 ngày [10], RL-41 ghi ~4 ngày.
- Mô hình sóng nghiệp vụ của NCHMF (chỉ có bài báo [38][39]); trạng thái hiện tại của SEAFDEC OFDS [40].
- JAXA P-Tree có cần đăng ký tài khoản không (trang hướng dẫn không nói rõ) [14].
- File giờ UHSLC trạm 650: các file thử chỉ có năm 1959–1960 và 1995; chưa rõ có phải Hòn Dáu.
- ICESat-2 ở vùng Cát Bà: kết luận "khó dùng" là suy luận từ độ đục, chưa tải thử.
- Luồng XML của JMA có mang bản tin cho bão trên Biển Đông đi về Việt Nam không: các mục đã thấy là bão ảnh hưởng Nhật Bản. Khuyến nghị #4 phụ thuộc điểm này.
- Danh sách trạm IOC có trạm Việt Nam hay không (danh sách dài, có thể đọc thiếu).
- Bản đồ đang được sửa song song (lưới 0,125°, chưa commit): số 154 / 108 nút đếm từ cây làm việc ngày 24/10 và sẽ đổi khi phần đó được commit.

## Tài liệu

1. Open-Meteo, API limits and pricing. https://open-meteo.com/en/pricing
2. Open-Meteo, Terms. https://open-meteo.com/en/terms
3. Open-Meteo blog, "Weather Data for Multiple Locations At Once" (03/11/2023). https://openmeteo.substack.com/p/weather-data-for-multiple-locations
4. Open-Meteo, Weather Forecast API docs (bảng mô hình, best_match, nhiều tọa độ). https://open-meteo.com/en/docs
5. Open-Meteo, Marine Weather API docs. https://open-meteo.com/en/docs/marine-weather-api
6. Open-Meteo, Historical Weather API docs. https://open-meteo.com/en/docs/historical-weather-api
7. Open-Meteo, Previous Runs API docs. https://open-meteo.com/en/docs/previous-runs-api
8. Copernicus Marine, GLOBAL_ANALYSISFORECAST_PHY_001_024. https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024/description
9. Copernicus Marine, QUID GLO 001-024. https://documentation.marine.copernicus.eu/QUID/CMEMS-GLO-QUID-001-024.pdf
10. ECMWF, Open data. https://www.ecmwf.int/en/forecasts/datasets/open-data
11. NOAA NCEI, IBTrACS. https://www.ncei.noaa.gov/products/international-best-track-archive
12. NOAA NCEI, OISST. https://www.ncei.noaa.gov/products/optimum-interpolation-sst
13. MUR SST v4.1 trên NOAA CoastWatch ERDDAP. https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41 ; trang gốc PO.DAAC (không mở được từ máy này ngày 24/10): https://podaac.jpl.nasa.gov/dataset/MUR-JPL-L4-GLOB-v4.1
14. JAXA P-Tree user guide (Himawari SST). https://www.eorc.jaxa.jp/ptree/userguide.html
15. GEBCO, The GEBCO_2025 Grid. https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2025-grid
16. Copernicus Data Space, COP-DEM. https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM
17. NSIDC, ATL24 v1. https://nsidc.org/data/atl24/versions/1
18. Parrish et al. 2019, Validation of ICESat-2 ATLAS Bathymetry, Remote Sensing 11(14):1634. https://www.mdpi.com/2072-4292/11/14/1634
19. Dulac et al., Assessing the representation of tropical cyclones in ERA5 with the CNRM tracker (Climate Dynamics). https://researchportal.ip-paris.fr/en/publications/assessing-the-representation-of-tropical-cyclones-in-era5-with-th/
20. NCHMF, trang chủ. https://nchmf.gov.vn/Kttv/vi-VN/1/index.html
21. NCHMF, ví dụ tin bão (Cơn bão số 15). https://www.nchmf.gov.vn/kttv/vi-VN/1/tin-bao-tren-bien-dong-con-bao-so-15-post52084.html ; danh mục: https://www.nchmf.gov.vn/kttv/vi-VN/1/bao-ap-thap-nhiet-doi-2049-15.html
22. NCHMF, mục Thủy triều. https://www.nchmf.gov.vn/kttv/vi-VN/1/thuy-trieu-23-15.html
23. NCHMF, Bản tin dự báo thủy triều 10 ngày 25/03–03/04/2026 (PDF). https://kttv.gov.vn//upload/haivan/2026/3/25/dbqg-tthv-20260325_0930.pdf
24. NCHMF, mục Sóng. https://www.nchmf.gov.vn/kttv/vi-VN/1/song-25-15.html
25. Luật Minh Khuê, phân tích truyền tin thiên tai theo QĐ 18/2021/QĐ-TTg (nguồn thứ cấp). https://luatminhkhue.vn/phan-tich-noi-dung-truyen-tin-ve-thien-tai-theo-quyet-dinh-18-2021-qd-ttg-cua-thu-tuong-chinh-phu.aspx
26. Cục Quản lý đê điều và PCTT. https://phongchongthientai.mard.gov.vn/ ; VNDMS: https://vndms.gov.vn/
27. PSMSL, trạm HONDAU (841). https://psmsl.org/data/obtaining/stations/841.php
28. IOC Sea Level Station Monitoring Facility, danh sách trạm. https://www.ioc-sealevelmonitoring.org/list.php?operator=&showall=a&output=general&order=country
29. MarineLink, "Admiralty Provides New ENC Coverage of Vietnam" (2012). https://www.marinelink.com/news/admiralty-provides343471
30. OceanExpert, IMER. https://oceanexpert.org/institute/14723
31. QĐ 14/2006/QĐ-BTS (thành lập trung tâm quan trắc cảnh báo môi trường và phòng ngừa dịch bệnh thủy sản miền Bắc). https://vbpl.vn/TW/Lists/vbpq/Attachments/15151/14.2006.QD.BTS.doc
32. Chi cục Thủy sản Cà Mau, thông báo kết quả quan trắc đợt 21/2025 (ví dụ dạng bản tin tỉnh). https://storage-vnportal.vnpt.vn/cmu-khdn/5342/Vanban/signed-signed-tb-ccts-kq-qtmt-nuoc-dia-ban-tinh-ca-mau-dot-21-2025.pdf
33. JMA, RSMC Tokyo best track. https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/besttrack.html
34. JMA, luồng Atom XML phòng chống thiên tai. https://www.data.jma.go.jp/developer/xml/feed/extra.xml
35. RSMC Tokyo – Typhoon Center, Activities in 2024 (WRD/TC.57/7.1). https://www.typhooncommittee.org/57th/docs/item%207/7.1.Review_RSMC_Activities_2024_20250218.pdf
36. data.gov.hk, HKO tropical cyclone track information. https://data.gov.hk/en-data/dataset/hk-hko-rss-tc-track-info
37. HKO, Tropical Cyclones in 2019, Table 4.12. https://www.hko.gov.hk/en/publica/tc/tc2019/table412.html
38. "Kết quả bước đầu dự báo tổ hợp sóng biển tại Việt Nam", Tạp chí KTTV. https://vjol.info.vn/TCKHTV/article/view/59732
39. "Applying the SWAN model to predict wave fields in Hai Phong coastal area", VJMST. https://vjs.ac.vn/jmst/article/view/9728
40. SEAFDEC, Ocean forecasting system in the South China Sea and Gulf of Thailand. https://seafdec.or.th/fisheries-refugia/home/news/232-apply-the-ocean-forecasting-system-in-the-south-china-sea-and-the-gulf-of-thailand.html
41. Copernicus Marine, GLOBAL_ANALYSISFORECAST_WAV_001_027. https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_WAV_001_027/description
42. TIGGE tropical cyclone tracks, NCAR d330003 (bản sao OSDF, tải không cần đăng nhập; giấy phép ghi trong storm-basin eval). https://osdf-director.osg-htc.org/ncar/rda/d330003/ecmf
43. OpenStreetMap, Copyright and License (ODbL; không mở được bằng công cụ ngày 24/10). https://www.openstreetmap.org/copyright
44. Repo: `docs/eval/2026-10-23-storm-basin.md` (TIGGE, JTWC, JMA, NCHMF truy cập), `docs/eval/2026-10-24-cmems-sites.md`, `docs/eval/2026-10-24-gebco-vs-etopo.md`.
45. NOAA NCEI, ETOPO 2022. https://www.ncei.noaa.gov/products/etopo-global-relief-model
