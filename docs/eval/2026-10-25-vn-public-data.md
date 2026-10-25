# Dữ liệu công khai của Việt Nam cho vùng nuôi cá giò Cát Bà – Hạ Long – Bái Tử Long (2026-10-25)

Chủ dự án yêu cầu ngày 25/10/2026: **tìm và, nếu được phép, thu thập dữ liệu công khai của Việt Nam (ngoài dữ liệu nội bộ) để huấn luyện/kiểm tra mô hình dự báo và nội suy** cho trạm NB1 (20,719 N; 107,043 E).

Phạm vi: nghiên cứu tài liệu, mở thử trang web, một vài lệnh gọi nhỏ. Không đăng nhập, không tạo tài khoản, không vượt captcha/paywall.
"**Đã kiểm**" = đã mở trang hoặc tệp gốc ngày 25/10/2026. "**Chỉ nhắc tới**" = chỉ thấy qua kết quả tìm kiếm hoặc báo chí, chưa mở được nguồn gốc.
Tài liệu này bổ sung cho `docs/eval/2026-10-24-data-sources.md` (độ tin cậy nguồn mở), `2026-10-23-events-and-sources.md` và `2026-10-24-disease-evidence.md` (danh mục sự kiện). Không lặp lại các nguồn đã đánh giá ở đó.
Không dùng lại dữ liệu đã có: GreenLab 06M26042804, bảng quan trắc tỉnh Quảng Ninh (99 điểm, theo quý 2021–2024) và Hải Phòng (14 điểm, 2020–2024), Open-Meteo, OISST, CMEMS vật lý/sóng, GEBCO, IBTrACS, ECMWF, OSM.

## Tóm tắt

1. **Nguồn giá trị nhất là Viện Nghiên cứu Hải sản (RIMF, Hải Phòng).** Viện quan trắc môi trường **vùng nuôi cá lồng biển** ở Cát Bà nhiều năm: 2005–2013, 2016–2021 (2 đợt/năm, tầng mặt + đáy, nước lớn + nước ròng) và năm 2024 (tháng 5–11, ra 27 bản tin, 7 báo cáo tháng và một "bộ số liệu"). Điểm Hang Vẹm – Vụng O cách NB1 **khoảng 2,8 km**. Đây là nguồn DO, NH4, PO4, Vibrio đo **tại vùng lồng** duy nhất tìm được. Số liệu gốc **không công khai**, cần gửi công văn xin (mẫu ở mục 6). Điều này **sửa** mục 9 của `2026-10-24-data-sources.md` ("không tìm thấy bản tin cho Hải Phòng / Quảng Ninh").
2. **Ảnh vệ tinh màu nước (CMEMS ocean colour) dùng được ở mức 4 km, đã tải về.** Ô 4 km cách NB1 2,3 km có số liệu 31,7 % số ngày (≈ 440 ngày từ 01/2023 đến 17/10/2026), rất ít vào tháng 2–4 vì mây. Ô 300 m (OLCI) sát NB1 gần như luôn trống (0,7 %); ô 300 m gần nhất đủ dùng cách 1,56 km, chỉ 120 ngày. Không có sản phẩm SPM/độ đục 300 m.
3. **SPM vệ tinh không theo được TSS của sensor** (54 ngày trùng, Spearman 0,13). Tháng 6–7/2026 sensor đọc TSS 35–100 mg/L trong khi vệ tinh 1,5–17 g/m³; từ tháng 8 sensor đọc 2–5. Chưa kết luận được bên nào sai, nhưng vệ tinh là một phép kiểm độc lập cho đợt TSS cao của sensor.
4. **Trạm quan trắc tự động nước biển của tỉnh có tồn tại nhưng không công khai số liệu.** Quảng Ninh có 6 trạm nước biển ven bờ (2018); hệ thống quốc gia có 120 trạm nước biển (28 trung ương, 92 địa phương) truyền về Bộ. Không tìm thấy cổng tải hoặc dashboard công khai. Hải Phòng: chỉ thấy trạm nước thải/khí thải. Cần xin.
5. **Không có bộ dữ liệu nghiên cứu mở** (PANGAEA, Zenodo, Figshare…) cho Hạ Long/Cát Bà. Các bài báo chỉ có biểu đồ, không có bảng số liệu thô.
6. **Thủy văn:** bản tin thủy triều 10 ngày của NCHMF (Hòn Dấu, Cô Tô) chỉ có giờ và độ cao nước lớn/nước ròng (đã có trong eval 24/10). Chuỗi giờ Hòn Dấu ở UHSLC chỉ có 1959–1960, không dùng được.

## 1. Bảng xếp hạng (giá trị × khả năng lấy)

Giá trị: dùng cho (a) huấn luyện/kiểm định dự báo, (b) nội suy DO/độ mặn/PO4/NH3, (c) sự thật cho cảnh báo, (d) đặc trưng ngữ cảnh.

| # | Nguồn | Gần NB1 | Thông số | Tần suất, thời kỳ | Truy cập | Đã kiểm? | Dùng cho | Giá trị | Khả năng lấy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **RIMF – quan trắc môi trường vùng nuôi cá biển** (Bộ NN&PTNT giao) | Hang Vẹm – Vụng O 2,8–2,9 km; các điểm Cát Bà 2016–2021 2,9–7,7 km; Hòn Thoi Quýt 17 km | Nhiệt độ, độ muối, pH, DO, độ đục, TSS, N-NH4, N-NO2, N-NO3, P-PO4, COD, Coliform, Vibrio, thực vật phù du/tảo độc, trầm tích | 2/năm (2005–2021); hàng tháng hoặc 2 lần/tháng, tháng 5–11 (2024) | Bản tin gửi cơ quan quản lý và người nuôi; **số liệu không công khai** | Đã kiểm (trang dự án 2024 qua Internet Archive; 3 bài báo) | a, b, c | **Rất cao** | Trung bình (công văn) |
| 2 | **CMEMS ocean colour L3** (OCEANCOLOUR_GLO_BGC_L3_MY_009_103) | ô 4 km cách 2,3 km | CHL, SPM, KD490, ZSD | ngày, 1997→nay (trễ vài ngày; NRT riêng) | Miễn phí, cần tài khoản CMEMS (đã có) | Đã kiểm, **đã tải** | d (độ đục/chl ngữ cảnh), kiểm TSS sensor | Trung bình | Cao |
| 3 | Sở NN&MT Quảng Ninh – trạm tự động nước biển + quan trắc định kỳ | Hạ Long, Cẩm Phả, Vân Đồn (vị trí trạm chưa rõ) | pH, nhiệt độ, DO, TSS, Cr6+, CN, F (trạm tự động); định kỳ = bảng tỉnh đang có | phút/giờ (tự động) | Không công khai | Chỉ nhắc tới (bài CEM 2018, tham luận CEM) | a, b | Cao (nếu có DO liên tục) | Thấp–trung bình |
| 4 | Trung tâm Quan trắc MT & Bệnh thủy sản miền Bắc (RIA1) | Đông Quảng Ninh (Móng Cái, Đầm Hà, Hải Hà, Tiên Yên), xa NB1 > 60 km | nhiệt độ, độ mặn, pH, DO, NH4, COD, H2S… ; Perkinsus ở hàu/ngao | tháng/2 lần tháng, 4–11 (2023) | Bản tin gửi tỉnh; không công khai | Chỉ nhắc tới (báo NN&MT 21/11/2023) | b (vùng khác), c (bệnh nhuyễn thể) | Trung bình | Trung bình |
| 5 | Bài báo RIMF/VIMARU (VJS 2014, VIMARU 2023, Tạp chí Xây dựng 2026) | như #1 | khoảng giá trị, tỷ lệ mẫu vượt ngưỡng | — | Mở, **đã tải** làm bằng chứng | Đã kiểm | kiểm tra miền giá trị cho nội suy; tọa độ điểm | Thấp–trung bình | Cao |
| 6 | Hệ thống quan trắc tự động quốc gia (Envisoft, 120 trạm nước biển) | chưa rõ | như #3 | liên tục | Không công khai (chỉ Bộ, tỉnh) | Chỉ nhắc tới (kế hoạch TEDP, cem.gov.vn) | a, b | Cao | Thấp |
| 7 | NCHMF bản tin thủy triều 10 ngày | Hòn Dấu ~26 km | giờ, độ cao nước lớn/ròng | ngày | PDF công khai, có lớp chữ | Đã kiểm, tải 1 mẫu | d | Thấp | Cao |
| 8 | VAST/Trung tâm Vũ trụ VN – Sentinel-2 chất lượng nước vịnh Hạ Long (2019–2023) | vịnh Hạ Long, cửa Lục | TSS, Chl-a, COD, SST từ ảnh | 78 ảnh | Không có tải | Chỉ nhắc tới | d | Thấp | Thấp |
| 9 | UHSLC/PSMSL Hòn Dấu | 26 km | mực nước giờ (1959–1960), tháng (đến 2013) | — | Mở | Đã kiểm | — | Rất thấp | Cao |

Đã xem nhưng không dùng được: cổng halong.navy01.com (cảnh báo dông lốc, chỉ thời tiết – nếu dùng chỉ là ngữ cảnh, không điều khiển cảnh báo; chỉ nhắc tới).
Chưa kiểm được: data.gov.vn không kết nối được từ máy dev ngày 25/10/2026; cổng dữ liệu mở các tỉnh và "Báo cáo hiện trạng môi trường" quốc gia/tỉnh **chưa tra** (báo cáo hiện trạng thường chỉ có bảng tổng hợp theo năm, giá trị thấp cho mô hình giờ).
Bài báo chưa đọc được: bài MDPI Remote Sensing 14(19):4822 (Chl-a vịnh Hạ Long bằng GEE) và ECSS 2024 S0272771424001665 (mô hình dinh dưỡng vịnh Hạ Long) trả 403 – chỉ nhắc tới, chưa biết có số liệu kèm theo không.

## 2. Chi tiết từng nguồn

### 2.1. Viện Nghiên cứu Hải sản (RIMF) – quan trắc vùng nuôi cá biển

- **Nhiệm vụ 2024** (đã kiểm, trang lưu Internet Archive 14/06/2026; rimf.org.vn trả 404 cho mọi trang ngày 25/10/2026, chỉ tệp tĩnh `/Media/...` còn tải được): "Quan trắc, cảnh báo và giám sát môi trường vùng nuôi trồng thủy sản trên biển tại một số tỉnh trọng điểm (năm 2024)". Cấp quản lý Bộ NN&PTNT; chủ nhiệm TS. Nguyễn Công Thành; vùng nuôi biển Quảng Ninh, Hải Phòng, Kiên Giang; tháng 5–11/2024. Sản phẩm: 27 bản tin, 7 báo cáo tháng, 2 công văn cảnh báo, 1 báo cáo đột xuất, **bộ số liệu**; số liệu được cập nhật vào "cơ sở dữ liệu quan trắc thống nhất từ Trung ương đến địa phương".
- Kết quả tóm tắt (trích trang): Hải Phòng ô nhiễm nhất trong 3 vùng; Hang Vẹm – Vụng O nặng hơn Hòn Thoi Quýt; 6/60 mẫu tầng đáy DO ngoài GHCP; **93/120 mẫu N-NH4 vượt GHCP**; COD 13/120 vượt; Coliform 39/60, Vibrio tổng số 34/60 vượt. Quảng Ninh: N-NH4 94/188 mẫu vượt (1,1–3 lần) ở hòn Ông Cụ, Bọ Cắn, Béo Cò, Cống Đông – Cống Tây; tháng 5–8/2024 DO giảm, nhiệt cao, độ muối giảm, độ đục tăng; **cá bơi lờ đờ, nổi đầu, lở loét, chết rải rác** ở các khu này tháng 5–8/2024 (ứng viên sự kiện mới cho H2.4).
- **Chuỗi cũ ở Cát Bà** (đã kiểm qua bài báo):
  - VJS 2014 (Lê Tuấn Sơn và nnk., DOI 10.15625/1859-3097/14/3/3983): quan trắc thường niên của RIMF tháng 5 và 9/2013 tại Bến Bèo 1–2, Tùng Tràng, Hải Quân, Vụng Giá; DO 3,64–5,91 mg/L, thấp nhất lúc nước lớn và mùa mưa, chủ yếu ở tầng đáy; biểu đồ 2005–2013; **5 đợt thủy triều đỏ diện rộng 2011–2012** ở Cát Bà (trích Nguyễn Văn Nguyên 2013) – ứng viên sự kiện.
  - VIMARU 2023 (Trần Quang Thư và nnk., số 76): nhiệm vụ "Quan trắc môi trường khu vực nuôi cá biển tập trung, 2016–2021"; 5 điểm CB1–CB5; mùa khô (tháng 4–5) và mùa mưa (tháng 9–10); 2021 mùa mưa 100 % mẫu DO < 5 mg/L, thấp nhất 3,76; N-NH4 vượt ở 40 % (khô) và 90 % (mưa) mẫu; Bến Bèo (CB2) thường cao nhất.
  - Tạp chí Xây dựng 05/2026 (Trần Hữu Long, Lưu Ngọc Thiện): 4 bè cố định, hàng tháng tháng 4–8 (năm không ghi), tầng mặt + đáy; pH 7,92–8,29; độ trong 0,6–3,5 m; biên độ triều 1,6 – > 3 m.
- Tọa độ điểm: `data/vn_public/rimf_farm_zones/farm_zone_sampling_points.csv`. Bài 2023 in tọa độ dạng phút thập phân (20°44.388'), bài 2026 in dạng độ-phút-giây; hai vị trí CB1 trùng nhau trong ~150 m nên cách đọc là đúng. Chưa đối chiếu với mặt nạ nước (CB2–CB5 của bài 2023 nằm ở 20,76–20,78 N, cần kiểm).
- Dùng cho: (b) **nội suy DO, NH4, PO4 tại vùng lồng** – bảng tỉnh hiện có lấy mẫu ở điểm quan trắc chung, không phải giữa bè; (c) Vibrio/tảo độc làm sự thật mặt đất cho cảnh báo bệnh; (a) kiểm định theo mùa (thưa, không đủ cho dự báo giờ).
- Rủi ro: lấy mẫu thưa (2–14 lần/năm), mỗi lần một thời điểm thủy triều; đơn vị N-NH4 (mg N/L) khác NH3 của bảng tỉnh và NH4 µg/L của sensor; phương pháp APHA/SMEWW trong phòng thí nghiệm, khác cảm biến điện cực.

### 2.2. CMEMS ocean colour (đã tải)

- Sản phẩm `OCEANCOLOUR_GLO_BGC_L3_MY_009_103` (Copernicus-GlobColour, L3 ngày, đa cảm biến). Bộ dữ liệu:
  - `cmems_obs-oc_glo_bgc-plankton_my_l3-multi-4km_P1D` (v202603): CHL, 1/24° (~4 km).
  - `cmems_obs-oc_glo_bgc-transp_my_l3-multi-4km_P1D` (v202603): KD490, SPM, ZSD, ~4 km.
  - `cmems_obs-oc_glo_bgc-plankton_my_l3-olci-300m_P1D` (v202211): CHL, 1/180° (~300 m), chỉ OLCI.
  - Bản NRT (`..._nrt_l3-...`) chỉ giữ ~3 tuần gần nhất. Không có bộ "transp" 300 m; muốn độ đục 300 m phải tự tính từ bộ reflectance.
- Truy vấn: vùng 106,8–107,35 E × 20,55–20,95 N (giống các trích CMEMS sẵn có) cho 4 km; NB1 ±0,1° cho 300 m; 01/01/2023 – 17/10/2026. Lệnh: `python scripts/vn_public/fetch_ocean_colour.py` (cần `HAP_DATA_DIR` trỏ tới data của bản checkout chính khi chạy từ worktree).
- Kết quả tại NB1:

| Bộ | Ô gần nhất | % ngày có số liệu | Ô dùng được gần nhất (≥ 5 %) | Số ngày | Trung vị |
| --- | --- | --- | --- | --- | --- |
| CHL 4 km | 2,32 km | 31,7 % | 2,32 km | 439 | 3,4 mg/m³ |
| SPM 4 km | 2,32 km | 31,8 % | 2,32 km | 441 | 5,2 g/m³ (1 giá trị 100 = trần) |
| KD490 / ZSD 4 km | 2,32 km | 31,7 % | 2,32 km | 439 | — |
| CHL 300 m | 0,15 km | 0,7 % | 1,56 km | 120 | 7,6 mg/m³ |

- Theo tháng (4 km): tháng 9–11 nhiều nhất (57–71 ngày qua 4 năm), tháng 3–4 chỉ 7 ngày. Mùa nóng tháng 6–8 có 30–38 ngày.
- So với sensor (ngày sensor có > 200 bản ghi): SPM–TSS 54 ngày trùng, Pearson 0,12, Spearman 0,13; CHL 4 km với nhiệt độ/pH/NH4 |r| ≤ 0,34. Chênh lớn nhất ở tháng 6–7/2026 (sensor 35–100 mg/L, vệ tinh 1,5–17 g/m³). Vệ tinh nhìn lớp mặt của ô 4 km, sensor đo một điểm sát lồng; không kết luận được sensor sai, nhưng nên đưa vào danh sách kiểm tra chất lượng TSS.
- Lưu ý: toolbox báo phiên bản 202603/202211 **ngừng ngày 24/11/2026** và số liệu sau 27/04/2026 "có thể chưa cập nhật". Khi tải lại phải ghi thành tệp mới (write-once).
- Dùng cho: (d) đặc trưng ngữ cảnh mùa (độ đục, chl), cảnh báo tảo nở hoa sớm (thử), kiểm tra chéo TSS sensor. Không dùng trực tiếp cho cảnh báo.

**Viễn thám khác (chỉ nhắc tới, không thử tải):**

| Sản phẩm | Độ phân giải, trễ | Tại NB1 | Truy cập | Nhận xét |
| --- | --- | --- | --- | --- |
| SMAP L3 độ mặn (JPL / RSS) | ~40–70 km, 8 ngày | Không dùng được: một ô rộng hơn cả cụm Lan Hạ – Hạ Long, nhiễm đất liền gần bờ | NASA Earthdata (cần tài khoản) | Độ mặn chỉ còn cách xin số liệu đo hoặc mô hình GLORYS (đã có) |
| SMOS L3 độ mặn (CATDS / BEC) | ~25–50 km | Như trên | đăng ký | Như trên |
| MODIS-Aqua / VIIRS L3 SST (NASA OBPG, NOAA CoastWatch ERDDAP) | 4 km ngày, trễ 1–2 ngày | Mây như màu nước (~30 % ngày có số liệu, ước theo kết quả 4 km ở trên) | mở | SST đã có OISST/GLORYS (eval 24/10); không ưu tiên |
| ESA OC-CCI v6 | 4 km ngày, CHL, KD490 | Như GlobColour 4 km | mở, không cần tài khoản | Dự phòng nếu mất truy cập CMEMS |
| Sentinel-2 MSI / Landsat 8–9 | 10–30 m, 5–16 ngày | Có thể thấy vùng bè, nhưng không có sản phẩm độ đục/chl sẵn | mở (Copernicus Data Space, USGS) | Phải tự xử lý (ACOLITE/C2RCC, GEE) – như dự án VAST ở #8 |
| Sentinel-3 OLCI | 300 m | Đã thể hiện qua bộ CMEMS 300 m (0,7 % ngày tại ô sát NB1) | mở | — |

### 2.3. Trạm quan trắc tự động nước biển (tỉnh, quốc gia)

- Quảng Ninh: bài CEM 28/12/2018 nêu mạng 26 trạm, trong đó 6 trạm nước biển ven bờ do Trung tâm Quan trắc TN&MT tỉnh vận hành (chỉ nhắc tới). Tham luận CEM liệt kê 3 trạm nước biển với các thông số pH, nhiệt độ, DO, TSS, Cr6+, CN, F.
- Quốc gia: kế hoạch TEDP (cem.gov.vn) nêu 1.714 trạm trên phần mềm Envisoft, 120 trạm nước biển/ven biển (28 trung ương, 92 địa phương), 60/63 tỉnh đã truyền số liệu về Bộ.
- Không thấy cổng công khai chuỗi số liệu. Đây là nguồn **DO liên tục** tiềm năng nhất ngoài sensor của mình → đưa vào công văn (mục 6).
- QĐ 52/2026/QĐ-UBND Quảng Ninh (định mức quan trắc nước biển) cho thấy tỉnh vẫn duy trì quan trắc định kỳ – chính là nguồn của bảng `data/quangninh` đang có.

### 2.4. RIA1 – Trung tâm Quan trắc Môi trường và Bệnh thủy sản miền Bắc

- Quảng Ninh 4–11/2023: 35 điểm vùng nuôi tôm + 10 điểm nhuyễn thể ở Móng Cái, Đầm Hà, Hải Hà, Tiên Yên; 4.840 mẫu; báo kết quả sơ bộ trong 3 ngày, báo cáo trong 5 ngày (chỉ nhắc tới, báo NN&MT 21/11/2023). Xa NB1, vùng nuôi khác (đầm tôm, bãi nhuyễn thể).
- 2024: Perkinsus olseni ở hàu/ngao Quảng Ninh 25–100 % số mẫu (chỉ nhắc tới). Giá trị cho mô hình bệnh nhuyễn thể, không phải cá giò.

### 2.5. Thủy văn, khí tượng biển

- NCHMF: bản tin thủy triều 10 ngày (PDF có lớp chữ, `kttv.gov.vn/upload/haivan/...`), trạm Hòn Dấu, Cô Tô, Bạch Long Vỹ. Đã tải 1 bản mẫu. Đã được đề xuất ở eval 24/10 (khuyến nghị #5).
- UHSLC h650a "Hon Dau": 8.784 giờ, chỉ năm 1959–1960. PSMSL trạm 841: trung bình tháng đến 2013. Không dùng.
- Sông Bạch Đằng/Cấm (lưu lượng, xâm nhập mặn), VNDMS: chưa tìm được nguồn tải mở; VNDMS cần đăng nhập – không thử.

## 3. Đã tải về (bản checkout chính, `data/vn_public/`, mỗi tệp có `.manifest.json`: URL, thời điểm, sha256, điều khoản)

| Thư mục / tệp | Cỡ | Nội dung |
| --- | --- | --- |
| `rimf_farm_zones/rimf_2024_quan-trac-vung-nuoi-bien_wayback20260614.html` | 44 KB | Trang nhiệm vụ 2024 (bản lưu Internet Archive) |
| `rimf_farm_zones/vjs_2014_le-tuan-son_catba-cage-pollution.pdf` | 724 KB | Bài VJS 2014 |
| `rimf_farm_zones/vimaru_2023_tran-quang-thu_catba-longson.pdf` | 589 KB | Bài VIMARU 2023 (vjol.info.vn không kết nối được từ máy; dùng bản tải cùng ngày, ghi trong manifest) |
| `rimf_farm_zones/tapchixaydung_2026_tran-huu-long_haiphong-cage.pdf` | 390 KB | Bài Tạp chí Xây dựng 2026 |
| `rimf_farm_zones/farm_zone_sampling_points.csv` | 1,3 KB | 9 điểm lấy mẫu, tọa độ thập phân, khoảng cách tới NB1 |
| `nchmf_tide/dbqg-tthv-20260325_0930.pdf` | 289 KB | Bản tin thủy triều 10 ngày (mẫu) |
| `cmems_oceancolour/oc_chl_4km__...nc` | 0,76 MB | CHL 4 km, 2023-01-01 → 2026-10-17 |
| `cmems_oceancolour/oc_transp_4km__...nc` | 2,2 MB | KD490, SPM, ZSD 4 km |
| `cmems_oceancolour/oc_chl_olci300m__...nc` | 7,2 MB | CHL 300 m, NB1 ±0,1° |
| `cmems_oceancolour/derived/*__usability.csv`, `*__nb1_series.csv` | < 100 KB | % ngày có số liệu từng ô; chuỗi ngày tại ô dùng được gần NB1 (CHL 439, SPM 441, CHL 300 m 120 dòng) |

Mỗi thư mục có `SOURCES.md`. Mã: `scripts/vn_public/` (ghi một lần, không ghi đè), test `tests/test_vn_public.py`. Các bài báo chỉ lưu bản địa phương làm bằng chứng, không đưa vào git, không phát tán lại.

## 4. Cần xin chính thức

| Cơ quan | Xin gì | Vì sao |
| --- | --- | --- |
| **Viện Nghiên cứu Hải sản** (Trung tâm Quan trắc môi trường biển; TS. Nguyễn Công Thành) | Bộ số liệu quan trắc vùng nuôi cá biển Cát Bà (Bến Bèo, Hang Vẹm – Vụng O, Tùng Tràng, Vụng Giá…) và Hòn Thoi Quýt, 2005→nay; bản tin 2024–2026 | Nguồn duy nhất đo tại vùng lồng gần NB1 |
| Sở Nông nghiệp và Môi trường Quảng Ninh (Trung tâm Quan trắc) | Chuỗi trạm tự động nước biển (DO, pH, nhiệt độ, TSS) + quan trắc định kỳ vùng nuôi Hạ Long, Bái Tử Long, Vân Đồn | DO liên tục; mở rộng bảng tỉnh sẵn có sau 2024 |
| Chi cục Thủy sản Hải Phòng (Sở NN&MT Hải Phòng) | Kết quả quan trắc vùng nuôi Cát Bà, Cát Hải; danh sách sự cố cá chết/bệnh có ngày, địa điểm | Sự thật mặt đất cho cảnh báo |
| Viện Tài nguyên và Môi trường biển (IMER) | Số liệu khảo sát vịnh Lan Hạ, Hạ Long (độ muối, DO, dinh dưỡng), nếu có hợp tác | Nghiên cứu nền; imer.ac.vn không kết nối được |

## 5. Rủi ro khi dùng

- **Đơn vị và dạng chất khác nhau:** bảng tỉnh ghi NH3 (mg/L); bài báo/QCVN 10:2023 ghi N-NH4 (mg N/L); sensor NH4 thô (µg/L, chưa xác nhận) → NH3. Không gộp trực tiếp để huấn luyện nội suy khi chưa quy đổi.
- **Phương pháp khác nhau:** mẫu chai phân tích phòng thí nghiệm (APHA/SMEWW) so với điện cực liên tục; một thời điểm thủy triều/lần.
- **Lấy mẫu thưa, thiên lệch mùa:** 2 đợt/năm (2016–2021) hoặc tháng 5–11 (2024); vệ tinh thiếu tháng 2–4.
- **Bản quyền:** bài báo mở nhưng không ghi giấy phép → chỉ lưu nội bộ. CMEMS: miễn phí, ghi công. Số liệu xin được sẽ có điều kiện riêng (thường cấm phát tán lại).
- **Kết quả tìm kiếm tóm tắt bằng máy có thể sai năm/số** – chỉ các mục "đã kiểm" được dùng làm căn cứ.
- **Shadow mode:** mọi nguồn ở đây chỉ dùng để huấn luyện/kiểm định hoặc ngữ cảnh, không đẩy cảnh báo.

## 6. Mẫu công văn xin số liệu (điều chỉnh tên cơ quan, người ký)

> **[TÊN ĐƠN VỊ]** &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
> Số: …/…  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; Độc lập – Tự do – Hạnh phúc
> V/v đề nghị cung cấp số liệu quan trắc môi trường vùng nuôi biển khu vực Cát Bà – Hạ Long
>
> Kính gửi: **[Viện Nghiên cứu Hải sản / Sở Nông nghiệp và Môi trường tỉnh Quảng Ninh / Chi cục Thủy sản thành phố Hải Phòng / Viện Tài nguyên và Môi trường biển]**
>
> [Tên đơn vị] đang thực hiện nghiên cứu "[tên đề tài]" về giám sát, dự báo ngắn hạn chất lượng nước phục vụ nuôi cá giò lồng biển tại vịnh Lan Hạ – Cát Bà (trạm cảm biến tự động tại 20,719° N; 107,043° E, hoạt động từ 29/5/2026). Kết quả chỉ dùng cho nghiên cứu, chạy thử nghiệm nội bộ, không công bố số liệu gốc và không dùng cho mục đích thương mại.
>
> Để hiệu chỉnh và kiểm định mô hình, chúng tôi kính đề nghị Quý cơ quan xem xét cung cấp:
> 1. **Phạm vi:** các điểm quan trắc vùng nuôi cá lồng biển Cát Bà (Bến Bèo, Hang Vẹm – Vụng O, Tùng Tràng, Hải Quân, Vụng Giá, vịnh Lan Hạ), Hòn Thoi Quýt – Gia Luận, và vùng nuôi biển Hạ Long – Bái Tử Long – Vân Đồn (hòn Ông Cụ, Bọ Cắn, Béo Cò, Cống Đông – Cống Tây); kèm tọa độ từng điểm.
> 2. **Thời kỳ:** từ năm 2016 (hoặc sớm nhất hiện có) đến nay; với trạm tự động: toàn bộ chuỗi theo giờ.
> 3. **Thông số:** nhiệt độ, độ muối, pH, DO (tầng mặt và tầng đáy), độ đục, độ trong, TSS, N-NH4⁺ (hoặc NH3), N-NO2⁻, N-NO3⁻, P-PO4³⁻, COD, Chl-a, Coliform, Vibrio tổng số, mật độ thực vật phù du/tảo độc; ghi chú thời điểm thủy triều (nước lớn/nước ròng).
> 4. **Thông tin kèm theo:** ngày giờ lấy mẫu, độ sâu, phương pháp phân tích, đơn vị, giới hạn phát hiện; các bản tin/thông báo kết quả quan trắc và các sự cố cá chết, dịch bệnh đã ghi nhận (ngày, địa điểm, đối tượng nuôi, nguyên nhân).
> 5. **Định dạng:** tệp Excel/CSV (ưu tiên) hoặc bản tin PDF.
>
> Chúng tôi cam kết sử dụng đúng mục đích, ghi rõ nguồn trong mọi sản phẩm, không chuyển cho bên thứ ba, và sẵn sàng chia sẻ lại kết quả phân tích (chuỗi đo liên tục của trạm cảm biến tại Cát Bà) để Quý cơ quan tham khảo.
>
> Đầu mối liên hệ: [họ tên, chức vụ, điện thoại, email].
> Trân trọng cảm ơn./.
>
> *Nơi nhận:* như trên; lưu VT. &nbsp;&nbsp;&nbsp;&nbsp;&nbsp; **[THỦ TRƯỞNG ĐƠN VỊ]** (ký, đóng dấu)

## 7. Việc tiếp theo đề xuất

1. Gửi công văn tới RIMF trước (giá trị cao nhất, có đầu mối rõ).
2. Kiểm tọa độ CB1–CB5 (bài 2023) với mặt nạ nước; thêm 2 ứng viên sự kiện (thủy triều đỏ 2011–2012 Cát Bà; triệu chứng cá ở vùng nuôi Quảng Ninh tháng 5–8/2024) vào danh mục sự kiện sau khi đối chiếu nguồn.
3. Nếu cần chuỗi màu nước thường xuyên: chạy lại `fetch_ocean_colour.py` với phiên bản mới sau 24/11/2026 (tệp mới), cân nhắc thêm bộ NRT cho ngày gần nhất.
4. Thêm cờ kiểm tra chất lượng TSS sensor dựa trên SPM vệ tinh (chỉ ghi chú, không loại dữ liệu tự động).

## Tài liệu (đã mở ngày 25/10/2026 trừ khi ghi khác)

1. RIMF, nhiệm vụ quan trắc vùng nuôi biển 2024 (bản lưu 14/06/2026): http://web.archive.org/web/20260614105511/https://www.rimf.org.vn/ketquanc/chitiet/quan-trac-canh-bao-va-giam-sat-moi-truong-vung-nuoi-trong-thuy-san-tren-bien-tai-mot-so-tinh-trong-%C4%91iem-nam-2024
2. Lê Tuấn Sơn và nnk. (2014), Tạp chí KH&CN Biển 14(3): 265–271: https://vjs.ac.vn/index.php/jmst/article/download/3983/5283/20919
3. Trần Quang Thư và nnk. (2023), Tạp chí KHCN Hàng hải số 76: https://vjol.info.vn/vimaru/article/view/89606
4. Trần Hữu Long, Lưu Ngọc Thiện (2026), Tạp chí Xây dựng 05/2026: https://cmsnews.tapchixaydung.vn/upload/pdf/2026/06/05/35.-tran-huu-long_05062026153553.pdf
5. Báo NN&MT, bản tin thủy sản 24/4/2024 – nguyên nhân cá chết ở Cát Bà: https://nongnghiepmoitruong.vn/radio/ban-tin-thuy-san-ngay-24-4-2024-xac-dinh-nguyen-nhan-ca-chet-o-cat-ba-d383775.html
6. Báo NN&MT, quan trắc môi trường vùng nuôi Quảng Ninh (21/11/2023): https://nongnghiepmoitruong.vn/quan-trac-moi-truong-vung-nuoi-trong-thuy-san-d368946.html
7. CEM, Quảng Ninh giám sát môi trường bằng quan trắc tự động (2018): https://cem.gov.vn/thong-tin-hoat-dong/quang-ninh-giam-sat-moi-truong-bang-quan-trac-tu-dong
8. CEM, kế hoạch triển khai TEDP (chỉ qua kết quả tìm kiếm): https://cem.gov.vn/storage/upload/files/Bai%201_%20Ke%20hoach%20trien%20khai%20TEDP.pdf
9. CEM, tham luận quản lý trạm quan trắc tự động (chỉ qua kết quả tìm kiếm): https://cem.gov.vn/storage/news_file_attach/thamluan.pdf
10. VAST, giám sát chất lượng nước vịnh Hạ Long bằng viễn thám và AI: https://vast.gov.vn/en/web/chuyen-doi-so/tin-chi-tiet/-/chi-tiet/giam-sat-thong-minh-chat-luong-nuoc-vinh-ha-long-bang-cong-nghe-vien-tham-va-tri-tue-nhan-tao-141811-3807.html
11. NCHMF, bản tin thủy triều 10 ngày: https://kttv.gov.vn//upload/haivan/2026/3/25/dbqg-tthv-20260325_0930.pdf
12. UHSLC Hòn Dấu h650a: https://uhslc.soest.hawaii.edu/opendap/rqds/pacific/hourly/h650a.nc ; PSMSL 841: https://psmsl.org/data/obtaining/stations/841.php
13. CMEMS OCEANCOLOUR_GLO_BGC_L3_MY_009_103: https://data.marine.copernicus.eu/product/OCEANCOLOUR_GLO_BGC_L3_MY_009_103
14. Chỉ nhắc tới (403): MDPI Remote Sensing 14(19):4822 https://www.mdpi.com/2072-4292/14/19/4822 ; ECSS 2024 https://www.sciencedirect.com/science/article/pii/S0272771424001665
