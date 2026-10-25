# Bộ dữ liệu nước ngoài để huấn luyện trước (pretrain) rồi tinh chỉnh trên dữ liệu VN — khảo sát 2026-10-25

**Trạng thái:** khảo sát tài liệu + thăm dò nhẹ (mỗi nguồn ≤ 1 truy vấn nhỏ). Không tải hàng loạt, không tạo tài khoản, không ghi gì vào `data/`, `artifacts/`, `runtime/`. Mẫu thăm dò chỉ nằm trong thư mục tạm của phiên, không commit.
`data/foreign/CANDIDATES-H4.md` **giữ nguyên**; ứng viên mới chỉ ghi ở đây.
Hai agent khác đang chạy thí nghiệm chuyển giao trên các bộ đã có trong repo (NERRS, Chesapeake, Texas, USGS, IRLON, HK EPD). Tài liệu này là khảo sát rộng hơn, không chạy mô hình.
Nguồn Việt Nam chỉ liệt kê ngắn (mục 3.6): một agent khác đang khảo sát sâu phần VN.

Mức kiểm chứng dùng trong mọi bảng:

- **K1** = gọi API / ERDDAP / tải vài KB thành công hôm nay, đã thấy dữ liệu thật.
- **K2** = mở được trang hoặc metadata chính thức (CKAN, trang dataset), chưa thấy dữ liệu.
- **K3** = chỉ thấy trong kết quả tìm kiếm, báo chí hoặc bài báo. **Chưa kiểm chứng.**
- **X** = đã thử nhưng bị chặn (403, lỗi SSL, cần tài khoản/khóa).

Số liệu khí hậu ghi "(ước lượng)" là hiểu biết chung, chưa đo trên dữ liệu.

## 1. Câu hỏi

Cát Bà chỉ có 5 tháng sensor (29/05 → 24/10/2026), chưa có mùa đông, chưa có một chu kỳ năm. Dữ liệu tỉnh (QN, HP) là mẫu tháng/quý và độ mặn, nhiệt độ của HP là số mô hình GLORYS, không phải số đo (RL-25). Ý tưởng của chủ dự án: tìm dữ liệu có đặc điểm giống Cát Bà, huấn luyện trước trên đó, tinh chỉnh và kiểm tra trên VN.

Hai mục đích khác nhau nên tách đánh giá:

- **(a) Dự báo tần suất cao:** Temp, pH, NH4, độ đục/TSS; ≤ 1 giờ; nhiều năm, có mùa lạnh.
- **(b) Bộ nội suy chéo biến (imputer):** đích DO, độ mặn, PO4, NH3/NH4, độ trong; đầu vào giống `core/impute.py` (`FEATURES_4` = NH3, pH, Temperature, TSS; thêm COD, tháng). Tần suất tháng cũng được, miễn là các biến **đo cùng một mẫu**.

## 2. Phương pháp

### 2.1 Cách tìm

- Đọc `data/foreign/CANDIDATES-H4.md`, các `data/foreign/*/SOURCES.md`, `probe_korea_irlon/NOTES.md`, RL-11/12/14/20–28 và RL-62 (H1.4).
- Tìm web theo vùng (HK, Đài Loan, Trung Quốc/Vịnh Bắc Bộ, Nhật, Hàn, Thái, Malaysia, Singapore, Philippines, Ấn Độ, Úc, Hawaii, Mỹ) và theo kho (Zenodo API, Mendeley, Kaggle, data.gov.au CKAN).
- Thăm dò nhẹ: metadata ERDDAP + 1 giờ dữ liệu (PacIOOS), danh sách trạm 28 KB + 4 KB đầu tệp số liệu (Đài Loan OCA), liệt kê thư mục NCEI (NERRS nutrient), CKAN data.gov.au và THREDDS AODN (AIMS), Zenodo REST.
- Tính lại phân bố mặt nước HK EPD 2015–2025 từ tệp **đã có** trong repo (chỉ đọc).

Lưu ý: đánh giá H4 (`CANDIDATES-H4.md`) đòi hỏi ≥ 5 trạm cách nhau 1–30 km. Pretrain chỉ cần **một trạm dài, tần suất cao**. Vì vậy các bộ bị loại ở H4 (ví dụ logger AIMS, PacIOOS) được chấm lại từ đầu.

### 2.2 Thang điểm (chốt trước khi chấm)

Mỗi tiêu chí 0–3, nhân trọng số. Điểm cuối = tổng / tối đa (%).

**(a) Dự báo — tối đa 36**

| Mã | Tiêu chí | Trọng số | 3 | 2 | 1 | 0 |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | **Mùa lạnh** (trung vị tháng lạnh nhất) | ×2 | 14–20 °C (như Cát Bà ≈ 15–20) | 20–23 hoặc 10–14 | 23–25 hoặc 5–10 | > 25 (không có mùa lạnh) hoặc < 5 |
| A2 | Chế độ mặn | ×1 | 20–34 psu, có xung nước sông | biển ổn định hoặc cửa sông rất rộng | gần ngọt / quá mặn | nước ngọt |
| A3 | **Triều** (biên độ) | ×1 | ≥ 3 m | 1,5–3 m | 0,5–1,5 m | < 0,5 m |
| A4 | Môi trường sống | ×1 | vịnh kín có lồng/bè | vịnh hở, đầm phá | lòng kênh cửa sông, đầm lầy, ao | hồ ngọt, trong nhà |
| A5 | Trùng biến sensor {Temp, pH, NH4, đục/TSS} | ×2 | 4 biến | 3 | 2 | ≤ 1 |
| A6 | Tần suất | ×1 | ≤ 15 phút | ≤ 1 giờ | ngày | tháng |
| A7 | Độ dài | ×2 | ≥ 10 năm | 3–10 | 1–3 | < 1 |
| A8 | Truy cập / giấy phép | ×1 | mở, không đăng nhập, được phân phối lại | mở có điều kiện / khóa miễn phí | phải xin | đóng |
| A9 | Liên quan nuôi trồng | ×1 | đo tại lồng/bè | trong vùng nuôi | gần vùng nuôi | không |

**(b) Imputer — tối đa 33**

| Mã | Tiêu chí | Trọng số | 3 | 2 | 1 | 0 |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | Đích đo cùng mẫu {DO, Sal, PO4, NH3/NH4, độ trong} | ×2 | ≥ 4 | 3 | 1–2 | 0 |
| B2 | Đầu vào {Temp, pH, TSS mg/L, NH3/NH4} | ×2 | đủ 4, TSS bằng mg/L | 3, hoặc độ đục thay TSS | 2 | ≤ 1 |
| B3 | Đơn vị khớp (NH3-N/NH4-N, TSS mg/L), ít bị kiểm duyệt "<LOQ" | ×1 | khớp | đổi được | đổi có giả định | không |
| B4 | Mùa lạnh (thang A1) | ×1 | | | | |
| B5 | Chế độ mặn ven bờ (thang A2) | ×1 | | | | |
| B6 | Cỡ mẫu (số mẫu đủ biến) | ×2 | ≥ 10.000 | 2.000–10.000 | 500–2.000 | < 500 |
| B7 | Truy cập (thang A8) | ×1 | | | | |
| B8 | Liên quan nuôi trồng (thang A9) | ×1 | | | | |

Tham chiếu Cát Bà: mùa lạnh 15–20 °C, độ mặn 20–33 psu, triều nhật ~3–4 m, vịnh kín giữa đảo đá vôi, có lồng; sensor đo Temp, pH, NH4, TSS, COD.

## 3. Kết quả

### 3.1 Ứng viên mới, đã kiểm chứng được (K1/K2)

| # | Bộ dữ liệu | Nhà cung cấp, URL | Vùng, tọa độ | Môi trường | Biến | Tần suất | Thời kỳ | Khí hậu / mặn / triều | Truy cập, giấy phép | QC | Kích thước | Kiểm chứng |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N1 | **Đài Loan OCA "海域水質"** (quan trắc nước biển quốc gia) | Ocean Conservation Administration; https://data.gov.tw/dataset/155934 ; CSV số liệu `https://iocean.oca.gov.tw/oca_datahub/WebService/GetData.ashx?id=d8044a92-1a43-4563-8c57-e6387e8c9fba` ; trạm `…id=f60dc979-b6bf-4494-ae86-f2fb615fcf25` | Toàn bờ Đài Loan + Bành Hồ, Kim Môn; **265 trạm có tọa độ** (đã tải danh sách) | ven bờ, cảng, cửa sông, vùng nuôi Bành Hồ | Temp, Sal, pH, DO (chuẩn độ + điện cực), DO %, **SS (mg/L)**, Chl-a, **NH3_N**, NO3_N, **PO4**, NO2_N, SiO2, kim loại, độ sâu mẫu | mẫu theo quý (2002: tháng 3, 6, 9, 11) | 2002-11 → nay (cập nhật 6 tháng/lần) | phía bắc / Bành Hồ mùa đông ~17–20 °C (ước lượng); bờ tây triều 3–5 m, bờ đông vi triều (ước lượng) | CSV/JSON/GeoJSON mở, không đăng nhập; Giấy phép Dữ liệu Mở Chính phủ v1.0 | không có cột cờ; giá trị "<" (dưới LOQ) và "－" (không đo) | chưa biết (ước lượng chục MB) | **K1**: tải 28 KB danh sách trạm, 4 KB đầu tệp số liệu (2002, Keelung) |
| N2 | Đài Loan OCA "海域水質(地方測站)" | https://data.gov.tw/dataset/157566 | trạm địa phương | ven bờ | như N1 + sóng | không đều | 2022-05 → | như N1 | như N1 | — | — | K2 |
| N3 | **PacIOOS WQB-04 Hilo Bay** (+ WQB-05 Pelekane Bay) | PacIOOS / Đại học Hawaii; ERDDAP `https://pae-paha.pacioos.hawaii.edu/erddap/tabledap/wqb_04` | 19.734 N, 155.082 W | vịnh hở có xung sông Wailuku | Temp, Sal, turbidity, Chl, DO, DO %, pH (**pH từ 2015 toàn bộ cờ 9 = không có**) | 15 phút | 2010-10-23 → 2026-10-25 | năm 2023: Temp 17,0–27,9 °C, Sal 3,3–36,0 (cờ QARTOD 1); tháng 2/2024 ~24 °C → **không có mùa lạnh thực**; vi triều < 1 m (ước lượng) | mở, "used and redistributed for free" | QARTOD đầy đủ (agg + từng test) | ~16 năm × 35k dòng/năm | **K1** (metadata + 1 giờ dữ liệu + min/max phía server) |
| N4 | **AIMS MMP logger ven bờ GBR** (Chl huỳnh quang + độ đục; Temp/Sal SBE37) | AIMS / GBRMPA; CKAN data.gov.au; NetCDF 2023→ `https://thredds.aodn.org.au/thredds/catalog/AIMS/Marine_Monitoring_Program/FLNTU_timeseries/catalog.html` (và `SBE37_timeseries`); bản cũ: `https://data.aims.gov.au/data-download/rwqpp/envlogger/daily-data.zip` | ~20 điểm ven bờ GBR, 10–20° S | rạn ven bờ chịu vệt lũ sông | Temp, độ đục (NTU), Chl; Temp/Sal ở bộ riêng | ~10 phút gốc; tải sẵn theo giờ/ngày | 2007 → 2026 (đổi máy 4 tháng/lần) | mùa đông ven bờ ~21–23 °C (ước lượng); triều 2–4 m, Mackay tới ~6 m (ước lượng) | tải mở; CKAN ghi giấy phép "notspecified" → **cần xác minh** | QA/QC theo báo cáo MMP | hourly ~23 MB (theo trang) | K2 (CKAN API + THREDDS có thư mục tới 2026) |
| N5 | **AIMS MMP Phys-Chem & Nutrient** (mẫu nước) | `https://data.aims.gov.au/water-quality/` (trang tải chưa hiện nội dung) | ven bờ GBR | như N4 | theo mô tả CKAN: lý-hóa + dinh dưỡng; danh sách cột **chưa thấy** | chuyến khảo sát (vài lần/năm) | 2005 → | như N4 | công cụ tải mở; giấy phép chưa rõ | báo cáo QA/QC | chưa biết | K2 (chỉ CKAN) |
| N6 | AIMS Temperature Logger Program | `https://open-aims.github.io/data-platform/` (API DOI 10.25845/5b4eb0f9bb848) | ~80 điểm GBR, Coral Sea, WA… | rạn | chỉ Temp | 5–10 phút | từ 1980s–1990s tùy điểm | như N4 | **cần khóa API miễn phí** (không đăng ký theo yêu cầu) | có | lớn | K2 (trang tài liệu API) |
| N7 | **NERRS nutrient (tệp `*nut*.csv`) trong NCEI 0052765** | `https://www.ncei.noaa.gov/data/oceans/archive/arc0023/0052765/2.2/data/0-data/NERRS_CDMO_Archive_8.3.11/` | 26 khu NERRS (Jobos, Rookery, Apalachicola, GTM, Weeks Bay, Grand Bay, Mission-Aransas, Sapelo…) | cửa sông, đầm, rừng ngập mặn | PO4F, **NH4F (mg/L as N)**, NO2F, NO3F, NO23F, Chl-a; cùng điểm với sonde 15 phút (Temp, Sal, DO, pH, Turb) | mẫu tháng + mẫu ngày–đêm (ISCO, 2 giờ/lần trong 24 h; `CollMethd=2`) | 2002 → 2011 (bản NCEI) | như bộ NERRS đã có | công khai (NOAA), trích dẫn CDMO | **cờ CDMO `<0>`, `<-4>`…** | ~1.000 tệp × 3–10 KB | **K1** (liệt kê thư mục: số tệp nut theo khu: apa 99, cbv 54, del 49, jac 45, kac 45, job 36, rkb 36, gtm 36, wkb 39, sap 35, gnd 26, mar 19…; đọc header `job09nut2009.csv`) |
| N8 | **HK EPD lịch sử 1986–2014** (phần trước của bộ đã có) | https://data.gov.hk/en-data/dataset/hk-epd-marineteam-marine-water-quality-historical-data-en | 94 trạm HK | như bộ đã có | như bộ đã có (xem 3.2) | tháng | 1986 → 2024 (repo chỉ có 2015–2025) | như bộ đã có | mở | — | ~30 MB (ước lượng) | K2 (trang dataset trên data.gov.hk qua tìm kiếm) |

### 3.2 Bộ đã có trong repo (chấm lại cho mục đích pretrain)

| Bộ (thư mục) | Biến | Tần suất / thời kỳ trong repo | Khí hậu, mặn, triều | Ghi chú cho pretrain |
| --- | --- | --- | --- | --- |
| **HK EPD** (`data/foreign/hk_epd/`) | Temp, Sal, pH, DO, **NH3-N (tổng amoni, mg/L N)**, **UIA (NH3 không ion)**, **PO4-P**, **Secchi**, **SS mg/L**, Turb NTU, BOD5, TN, TP, Chl… | tháng, 3 độ sâu; 2015–2025, 30.760 dòng, 10.878 mẫu mặt | **tính lại từ repo:** Temp mặt p5–p95 17,4–30,0 °C (min 13,8, max 33,4); trung vị T2 = **17,8 °C**, T7 = 28,8 °C → **mùa lạnh giống Cát Bà**; Sal p5–p95 18,6–33,4; pH 7,3–8,3; DO 4,4–8,3; NH3-N 0,007–0,26 (3,4 % "<"); PO4-P 17,4 % "<"; Secchi 1,5–4,9 m; SS 1–16 mg/L. Triều hỗn hợp ~1–2,5 m (ước lượng) | Bộ duy nhất có **đủ 5 đích + đủ 4 đầu vào cùng mẫu** và cùng kiểu lấy mẫu với VN |
| NERRS 8 khu (`nerrs_ncei/`) | Temp, Sal, DO, pH, Turb (sonde) | 15 phút, 2007–2011 | Apalachicola/Weeks/Grand Bay đông ~10–14 °C, Rookery ~18–20, Jobos ~25 (ước lượng); phần lớn vi triều, Sapelo/GTM 2–3 m | không NH4 liên tục; nutrient N7 chưa tải |
| IRLON (`irlon_secoora/`) | Temp, Sal, DO, pH, Turb, **NO3, PO4 (sensor)**, Chl | giờ, 2014–2026 | đông ~16–20 °C (ước lượng); đầm phá vi triều; xung nước ngọt St. Lucie | không NH4 |
| Texas TWDB (`texas_twdb/`) | Temp, Sal, DO | giờ, 2008–2019 | đông ~10–14 °C; vi triều | không pH, không đục |
| Chesapeake MD DNR (`chesapeake_mddnr/`) | Temp, Sal, DO, pH, Turb | 15 phút, chỉ tháng 4–10 | ôn đới, **không có mùa đông trong dữ liệu** | cấm phân phối lại dữ liệu thô |
| USGS SF Bay (`usgs_sfbay/`) | Temp, SpC/Sal, Turb (DO/pH ít) | 15 phút, 2017–2025 | Địa Trung Hải | khí hậu khác xa |
| Hàn Quốc KOEM (`probe_korea_irlon/`) | Temp, Sal, pH, DO, Turb, Chl (Songdo: thêm NH4, NO3 theo mô tả, **chưa kiểm**) | ~5 phút không đều; tệp mở chỉ 1 năm/trạm (Songdo 571 nghìn dòng tới 2022) | đông 2–10 °C (ước lượng); **triều lớn 3–8 m**; gió mùa | không tọa độ, không cờ QC |

### 3.3 Ứng viên chưa kiểm chứng được hoặc bị chặn

| Bộ | Nguồn | Điều đã biết | Vì sao chưa dùng được | Kiểm chứng |
| --- | --- | --- | --- | --- |
| HK EPD phao khoa học (Tsuen Wan 22°21.942'N 114°06.646'E, bắc Lantau, North Point 2023–2025, Lamma 2024) | văn bản Marine Department HK (ví dụ https://www.mardep.gov.hk/filemanager/en/share/aboutus/pdf/pac/pacp1_24.pdf) | đo thủy văn + chất lượng nước tần suất cao, truyền thời gian thực về Smart Water Science Centre | không tìm thấy trang tải công khai | K3 |
| HK AFCD giám sát vùng nuôi cá (FCZ) thời gian thực | (đã ghi ở CANDIDATES-H4) | 16 vùng nuôi lồng, giống trường hợp sử dụng nhất | chỉ có bảng hiển thị, phải xin AFCD | K2 (10-17) |
| Nhật, biển Ariake / Yatsushiro (phao tự động; Kumamoto 4 trạm 20 phút, 0,5 m dưới mặt; phao Kyushu đo Temp, Sal, DO, đục, Chl, pH) | cổng `akashiwo.jp` (Viện NC Thủy sản FRA); trang tỉnh Kumamoto https://www.pref.kumamoto.jp/soshiki/95/80686.html | vịnh trong, triều 4–6 m, nuôi rong nori + nhuyễn thể; đông ~8–11 °C (ước lượng) | `akashiwo.jp` trả 403 / lỗi TLS từ máy dev; `akashio.fra.go.jp` không phân giải | **X** |
| Hàn Quốc NIFS "실시간 수온 정보" (trại nuôi: Temp/Sal/DO theo độ sâu + khí tượng) | https://www.data.go.kr/data/15130641/fileData.do | có thông tin QC; "không giới hạn quyền sử dụng" | trang chỉ có 1 tệp "1 dòng" (có thể là mô tả, không phải chuỗi); chuỗi đầy đủ qua OpenAPI cần khóa | K2 |
| Hàn Quốc KOEM tàu tuyến cố định (25+ biến gồm NH4, PO4, độ truyền quang) | https://www.data.go.kr/data/15148601/fileData.do | có tọa độ | **KOGL loại 4: phi thương mại, cấm chỉnh sửa**; dạng shapefile | K2 |
| Ấn Độ INCOIS (phao chất lượng nước Kochi, Visakhapatnam) | https://iioe-2.incois.gov.in/site/services/water_quality.jsp | nhiều biến sinh địa hóa | không thấy cách tải lịch sử; nhiệt đới, không mùa lạnh | K2 |
| Thái Lan DMCR (7 trạm: 4 bờ, 2 đảo, 1 phao; Temp, Sal, đục, Chl, DO, pH); PCD (mẫu ven bờ) | tìm kiếm; PCD "cung cấp theo yêu cầu" | — | không có cổng mở | K3 |
| Singapore SFA Aquaculture Sensing Network (eo Johor, Aqua TROLL 500 + RDO; Sal, Chl, pH, Temp, DO) | https://aquaasiapac.com/2022/01/15/continuous-data-delivers-added-protection-for-singapore-fish-farmers/ | đo tại trại cá lồng | cổng dành cho người nuôi; xích đạo, không mùa lạnh | K3 |
| Trung Quốc: Ocean Cloud (NMDIS) | https://oceancloud.nmdis.org.cn/home | T, S, dòng, sóng; "tải miễn phí / theo yêu cầu" | chưa thấy biến chất lượng nước; có thể cần đăng ký | K3 |
| Trung Quốc: Vịnh Bắc Bộ (Khâm Châu, Phòng Thành), Hạ Môn, Trạm Giang, Hải Nam | bài báo (ví dụ DO Khâm Châu, Acta Oceanol. Sin. 2024 doi:10.1007/s13131-023-2243-1, chưa mở); figshare "Data-Beibu_Gulf" (44 trạm, 3 mùa, đồng vị + NH4, NO3) https://figshare.com/articles/dataset/Data-Beibu_Gulf_xls/15059718 | Vịnh Bắc Bộ là tương đồng nhất (cùng hệ triều nhật, cùng gió mùa) | **không tìm thấy chuỗi tần suất cao mở**; figshare chỉ là một chuyến khảo sát | K3 |
| Philippines BFAR (mariculture park) | FOI https://www.foi.gov.ph | — | chỉ qua yêu cầu FOI | K3 |
| Malaysia (DOF) | open.dosm.gov.my | chỉ thống kê sản lượng | không có chất lượng nước mở | K3 |
| Indonesia | — | — | **không khảo sát riêng**; không gặp nguồn mở nào trong các lượt tìm chung | — |
| GCOOS (vịnh Mexico) | ERDDAP GCOOS | phao/trạm Texas–Florida | **không khảo sát riêng**; vịnh Mexico đã có đại diện là Texas TWDB và NERRS (apa, wkb, gnd, mar, rkb) | — |

### 3.4 Bộ IoT nuôi trồng trên kho mở

| Bộ | URL | Nội dung | Nhận xét |
| --- | --- | --- | --- |
| Aquaponics fish pond IoT (Nigeria) | https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9253161/ (Data in Brief; dữ liệu trên Kaggle) | 12 ao, Temp, pH, DO, đục, **NH3**, NO3, 5 giây/lần | nước ngọt, vài tháng; chỉ hữu ích để thử kiến trúc, không để học động lực biển. K3 (chỉ kết quả tìm kiếm) |
| Mendeley "Aquaculture - Water Quality Dataset" | https://data.mendeley.com/datasets/y78ty2g293/1 | ao: Temp, đục, DO, BOD, CO2, pH, kiềm, NH3, NO2, P, H2S… | nước ngọt, nhãn chất lượng; không phải chuỗi thời gian dài |
| Mendeley "Environmental Parameters in Aquaculture" | https://data.mendeley.com/datasets/8s73jfvgr5/1 | Temp, DO, pH, đục (Bangladesh) | nước ngọt |
| "AquaSense_Dataset" (Mendeley, 08/2026) | (theo kết quả tìm kiếm) | 15 ao **giả định**, 30 ngày | **dữ liệu tổng hợp** → không dùng làm bằng chứng |
| Zenodo (REST API, 5 truy vấn) | `zenodo.org/api/records` | toàn bài báo hoặc dữ liệu không liên quan (ví dụ "shrimppond" 10.5281/zenodo.6137885 là tệp mô hình nước ngầm) | không có chuỗi sensor nuôi biển |

Kết luận 3.4: **không tìm thấy bộ IoT lồng nuôi biển mở nào**; mọi bộ IoT mở là ao nước ngọt, ngắn (K1 cho Zenodo; K3 cho Mendeley/PMC/Kaggle — chỉ thấy qua tìm kiếm).

### 3.5 Đặc điểm đơn vị (bắt buộc kiểm trước khi gộp)

| Bộ | Amoni | Chất rắn / đục | Độ sâu | Thời điểm lấy mẫu |
| --- | --- | --- | --- | --- |
| Cát Bà (GreenLab) | "NH4" thô, giả định µg/L × 0,001 → mg/L, rồi Emerson → NH3; **chưa có xác nhận nhà cung cấp** (`NH4_CONVERSION_CONFIRMED`) | "TSS" cảm biến (bản chất quang hay trọng lượng: chưa rõ) | gần mặt, trong lồng | liên tục |
| VN tỉnh (QN/HP) | NH3 (mg/L) theo QCVN | TSS mg/L | mặt | ban ngày |
| HK EPD | NH3-N = tổng amoni tính theo N (mg/L) + UIA (NH3 không ion, mg/L) | SS mg/L **và** Turb NTU | mặt / giữa / đáy | ban ngày |
| Đài Loan OCA | NH3_N "氨氮" (tổng amoni theo N, mg/L) | SS mg/L | cột DEPTH (thường 1 m) | ban ngày |
| NERRS | NH4F mg/L as N (lọc) | Turb NTU (sonde YSI 6136 / EXO, khác đời máy) | sonde cố định, thường đáy+0,5 m | grab tháng + 24 h |
| IRLON | không amoni; NO3, PO4 bằng sensor quang/hóa ướt (µmol/L hoặc mg/L) | Turb NTU | ~1 m | giờ |
| PacIOOS | không | turbidity (đơn vị ERDDAP ghi "1") | ~1 m | 15 phút |
| AIMS MMP | (phys-chem: chưa thấy) | turbidity NTU (ECO FLNTU) | ~gần đáy rạn | 10 phút |

### 3.6 Nguồn Việt Nam gặp trong lúc tìm — chỉ liệt kê

- CSIRO AquaWatch, điểm trình diễn An Lão (Hải Phòng), ao tôm, ra mắt 12/2024: https://www.csiro.au/en/news/All/News/2024/December/Vietnam-partners-with-Australia-to-pioneer-water-quality-monitoring — sensor + vệ tinh, **không thấy dữ liệu mở** (K3).
- Vịnh Xuân Đài (Phú Yên, UTS) và MRC (WQ tháng): đã ghi ở `CANDIDATES-H4.md`, không mở.
- Bài IoT nuôi trồng VN trên Zenodo (10.11591/eei.v12i4.5180): bài báo, không có dữ liệu.
- Bản tin quan trắc Viện NC NTTS I, báo cáo VEA: PDF (xem `docs/eval/2026-10-24-data-sources.md`).

## 4. Xếp hạng

### 4.1 Điểm (a) — dự báo tần suất cao (tối đa 36)

| Bộ | A1 lạnh ×2 | A2 mặn | A3 triều | A4 sống | A5 biến ×2 | A6 tần suất | A7 độ dài ×2 | A8 truy cập | A9 nuôi | Tổng | % | Kiểm chứng |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IRLON (có sẵn) | 3 | 3 | 0 | 2 | 2 | 2 | 3 | 3 | 1 | 27 | 75 | K1 |
| NERRS SWMP (có sẵn 2007–2011; mở rộng qua NCEI/CDMO) | 2 | 2 | 1 | 2 | 2 | 3 | 3 | 3 | 1 | 26 | 72 | K1 |
| Nhật Ariake/Yatsushiro | 1 | 3 | 3 | 3 | 2 | 2 | 2? | 1 | 3 | 25 | 69 | **X** (chưa vào được) |
| Hàn Quốc KOEM Songdo (có NH4 theo mô tả) | 0 | 2 | 3 | 2 | 3? | 3 | 2 | 3 | 0 | 23 | 64 | K2 (cột NH4 chưa thấy) |
| Hàn Quốc KOEM trạm khác (có sẵn) | 1 | 2 | 3 | 2 | 2 | 3 | 1 | 3 | 1 | 22 | 61 | K1 |
| AIMS MMP logger (N4) | 2 | 2 | 2 | 2 | 1 | 2 | 3 | 2 | 0 | 22 | 61 | K2 |
| PacIOOS Hilo (N3) | 1 | 2 | 1 | 2 | 1 | 3 | 3 | 3 | 0 | 21 | 58 | K1 |
| AIMS logger nhiệt độ (N6) | 2 | 2 | 2 | 2 | 0 | 3 | 3 | 2 | 0 | 21 | 58 | K2 |
| Chesapeake (có sẵn) | 0 | 2 | 1 | 2 | 2 | 3 | 3 | 2 | 1 | 21 | 58 | K1 |
| USGS SF Bay (có sẵn) | 1 | 2 | 2 | 1 | 1 | 3 | 3 | 3 | 0 | 21 | 58 | K1 |
| Texas TWDB (có sẵn) | 2 | 2 | 0 | 2 | 0 | 2 | 3 | 3 | 1 | 20 | 56 | K1 |
| INCOIS Kochi | 0 | 2 | 1 | 2 | 2? | 2? | 2? | 1 | 0 | 16 | 44 | K2 |
| IoT ao (Kaggle Nigeria) | 0 | 0 | 0 | 0 | 3 | 3 | 0 | 2 | 2 | 13 | 36 | K2 |

"?" = chấm theo mô tả, chưa thấy dữ liệu. HK EPD, Đài Loan OCA, GBR phys-chem bị loại khỏi (a) vì là mẫu tháng/quý (A6 = 0).

Nhận xét: **không bộ nào cao hơn 75 %**. Không bộ mở nào vừa có mùa lạnh 15–20 °C, vừa có triều ≥ 3 m, vừa đo **NH4 liên tục**. pH liên tục có ở NERRS, IRLON, Chesapeake, KOEM; độ đục liên tục có ở hầu hết; **NH4 liên tục chỉ có (theo mô tả) ở KOEM Songdo và ở ao IoT nước ngọt**.

### 4.2 Điểm (b) — imputer (tối đa 33)

| Bộ | B1 đích ×2 | B2 đầu vào ×2 | B3 đơn vị | B4 lạnh | B5 mặn | B6 cỡ ×2 | B7 truy cập | B8 nuôi | Tổng | % | Kiểm chứng |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **HK EPD** (có sẵn; + 1986–2014 N8) | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 2 | 32 | 97 | K1 (repo) |
| **Đài Loan OCA** (N1) | 3 | 3 | 2 | 3 | 2 | 3? | 3 | 2 | 30 | 91 | K1 |
| **NERRS nutrient + sonde** (N7) | 3 | 2 | 2 | 2 | 2 | 3? | 3 | 1 | 26 | 79 | K1 |
| IRLON (có sẵn) | 2 | 2 | 1 | 3 | 3 | 3 | 3 | 1 | 25 | 76 | K1 |
| AIMS MMP phys-chem (N5) | 2? | 2? | 2 | 2 | 2 | 2? | 2 | 0 | 20 | 61 | K2 |
| KOEM tự động (có sẵn) | 1 | 2 | 1 | 1 | 2 | 3 | 3 | 1 | 20 | 61 | K1 |
| Texas TWDB (có sẵn) | 1 | 0 | 1 | 2 | 2 | 3 | 3 | 1 | 17 | 52 | K1 |
| IoT ao (Mendeley) | 1 | 2 | 1 | 0 | 0 | 1 | 3 | 2 | 14 | 42 | K2 |

B6 "?": Đài Loan ước 265 trạm × 4 lần/năm × ~20 năm (cột rỗng "－" nhiều ở năm đầu, chưa đếm); NERRS ước ~26 khu × 4 trạm × 12 tháng × 10 năm.

### 4.3 Chọn để lấy trước

**(a) Dự báo — 4 bộ đáng lấy (theo thứ tự):**

1. **NERRS SWMP mở rộng** — thêm các khu cận nhiệt đới có mùa đông rõ và triều trung bình (Sapelo, GTM) cùng các năm ngoài 2007–2011 (NCEI 0052765 công khai; bản 1995–2025 qua CDMO AQS cần xác minh đăng nhập). Lợi ích kỳ vọng: học **biên độ ngày–đêm và chuyển mùa thu → đông** của Temp/pH/đục mà Cát Bà chưa có; cờ QC tốt nhất.
2. **IRLON** (đã có, 2014–2026) — mùa đông gần Cát Bà nhất trong các bộ mở, có xung nước ngọt; nhưng vi triều.
3. **AIMS MMP logger + PacIOOS Hilo** — chuỗi độ đục 10–15 phút dài 16–19 năm ở bờ nhiệt đới có vệt lũ; dùng cho **riêng mô hình TSS/đục** (sự kiện mưa → đục). PacIOOS không có mùa lạnh.
4. **Nhật Ariake** — giống nhất về triều lớn + vùng nuôi, nhưng **chưa vào được**; nên gửi email hỏi FRA/tỉnh Kumamoto. Không lấy trước khi có trả lời.

Ghi chú quan trọng: H1.4 (RL-62) cho thấy **Chronos-Bolt / TimesFM zero-shot đã thắng ridge 44–57 % ở 3–12 h cho nhiệt độ**, và đối chứng "chu kỳ ngày 7 ngày" chiếm ~70–80 % lợi thế. Mọi mô hình pretrain trên dữ liệu ngoài phải **so với Chronos zero-shot**, không chỉ với ridge. Đường rẻ nhất để có "mùa đông" cho nhiệt độ có thể không phải sensor nước ngoài mà là **GLORYS12 / OISST tại NB1 1993–2026** (đã có, RL-44), dùng làm tiền huấn luyện mùa vụ ở thang ngày.

**(b) Imputer — 4 bộ đáng lấy:**

1. **HK EPD** — đã có; tải thêm 1986–2014 (N8). Chọn trạm **chế độ biển (Sal mùa mưa ≥ 28 psu)** cho khớp NB1 (RL-25 xếp NB1 vào chế độ biển). Lợi ích: đủ cả 5 đích và 4 đầu vào cùng mẫu, mùa đông 17–19 °C như Cát Bà, kiểu lấy mẫu ban ngày như VN; có sẵn UIA (NH3) nên không cần tự đổi đơn vị.
2. **Đài Loan OCA** — cùng cấu trúc (SS mg/L, NH3_N, PO4, DO, Sal, pH, Temp), 265 trạm, từ 2002, giấy phép mở; thiếu độ trong (Secchi). Cần xử lý "<LOQ" và "－".
3. **NERRS nutrient + sonde** — ghép mẫu NH4F/PO4F với giá trị sonde cùng thời điểm (Temp, Sal, DO, pH, Turb). Gói nhỏ (vài MB). Có thêm mẫu ngày–đêm 24 h → học được quan hệ theo giờ trong ngày mà mẫu ban ngày VN không có.
4. **IRLON** — PO4/NO3 bằng sensor theo giờ; chỉ dùng làm bổ sung cho PO4 (không có NH4, không có Secchi).

Lợi ích kỳ vọng cho (b): tăng cỡ mẫu từ hàng trăm (VN, 16–22 đợt) lên hàng chục nghìn; học được quan hệ vật lý tổng quát (DO bão hòa giảm khi Temp và Sal tăng; UIA theo pH, Temp). **Không kỳ vọng** cải thiện lớn cho PO4 và NH3 (RL-14, RL-25: TSS, NH3 không chuyển được ngay cả giữa trạm gần nhau).

## 5. Rủi ro

| Rủi ro | Ảnh hưởng | Cách kiểm |
| --- | --- | --- |
| **Lệch miền (domain shift):** Hilo, GBR, Jobos không có mùa lạnh; Hàn, Nhật, Chesapeake quá lạnh; hầu hết bộ Mỹ vi triều | mô hình học sai biên độ triều và mùa | chấm A1/A3 như trên; luôn so với mô hình chỉ học VN và với Chronos zero-shot |
| **Chế độ mặn khác** (HK trạm cửa Châu Giang, St. Lucie) | RL-14/20/25: chế độ mặn quyết định khả năng chuyển | lọc trạm cùng chế độ biển trước khi pretrain |
| **Đơn vị amoni:** NH4 (ion) / NH3-N / NH4-N / tổng amoni / UIA; số VN thô chưa xác nhận đơn vị | sai một bậc độ lớn (×1.000 nếu µg vs mg) | đưa mọi bộ về **tổng amoni-N mg/L + UIA tính bằng Emerson** với cùng công thức `core/chemistry`; ghi rõ cơ sở; không trộn khi `NH4_CONVERSION_CONFIRMED` còn false |
| **Độ đục NTU vs TSS mg/L** | quan hệ đục–TSS phụ thuộc hạt, mỗi vùng một hệ số | chỉ dùng HK/Đài Loan (SS mg/L) cho TSS; với bộ chỉ có NTU, chuẩn hóa theo trạm (z-score) và chỉ học hình dạng |
| **Khác loại sensor và độ sâu** (sonde đáy NERRS, logger rạn AIMS, mẫu 3 tầng HK, sensor trong lồng VN) | lệch mức và biên độ ngày | dùng mẫu mặt; đặc trưng độ sâu nếu có; chuẩn hóa theo trạm |
| **Bám bẩn (fouling)** và trôi sensor | chuỗi trôi chậm giống tín hiệu thật (pH Cát Bà trôi từ 19/09, RL-13) | chỉ dùng giá trị qua QC (cờ `<0>`, QARTOD 1); với bộ không cờ (KOEM, Texas) áp QC kiểu `core/quality` |
| **Kiểm duyệt "<LOQ"** (HK PO4 17 %, Đài Loan "<0,05", QN PO4 hằng số) | imputer học giá trị trần giả | mô hình có kiểm duyệt hoặc loại; báo tỷ lệ "<" |
| **Mẫu ban ngày** (HK, Đài Loan, VN) | DO thiên cao so với đêm | NERRS mẫu 24 h để ước lượng thiên lệch |
| **Đích VN không phải số đo:** độ mặn, nhiệt độ HP là GLORYS (RL-25) | tinh chỉnh/kiểm tra trên số mô hình | chỉ dùng độ mặn QN (đo thật) làm tập kiểm tra |
| **Giấy phép:** MD DNR cấm phân phối lại; KOEM tàu tuyến KOGL-4 phi thương mại; AIMS giấy phép chưa rõ | hạn chế công bố/phát hành mô hình | ghi nguồn; không commit dữ liệu thô (`data/` đã gitignore) |
| **Lợi ích thật nhỏ hơn kỳ vọng** | công sức tải và làm sạch lớn | thử nghiệm nhỏ trước (mục 7) với gate #16 |

## 6. Tài liệu: học chuyển giao / pretrain cho chất lượng nước khi dữ liệu tại chỗ ít

DOI 1–5 và 8 đã mở được trang của nhà xuất bản/kho (USGS, PSU Pure, PMC, Portsmouth, Frontiers); #7 kiểm qua arXiv API; #6 chỉ kiểm DOI phân giải được; ngày 25/10/2026. con số chỉ lấy từ phần đã đọc (thường là tóm tắt).

| # | Bài | DOI / ID | Bối cảnh | Kết quả báo cáo | Liên quan Cát Bà |
| --- | --- | --- | --- | --- | --- |
| 1 | Willard et al. 2021, Water Resources Research 57(7) | 10.1029/2021WR029579 | nhiệt độ theo độ sâu ở 305 hồ "không có quan trắc", nguồn là 145 hồ có quan trắc; meta-learning chọn nguồn | RMSE trung vị 2,52 °C (không hiệu chỉnh) → 2,16 (PGDL-MTL) → **1,88 °C** (tổ hợp 9 nguồn), ~25 %; **độ tương đồng nguồn–đích (độ sâu tối đa) là yếu tố dự báo thành công chuyển giao quan trọng nhất** | ủng hộ chọn nguồn theo độ giống (thang điểm ở trên) |
| 2 | Ma et al. 2021, WRR 57(5) | 10.1029/2020WR028600 | LSTM dòng chảy pretrain trên Mỹ, chuyển sang Anh, Chile, Trung Quốc (5 lưu vực) | mô hình chuyển giao "tốt hơn rõ rệt" mô hình chỉ học tại chỗ ở Chile và Trung Quốc; lợi ích tăng theo **độ đa dạng và cỡ** dữ liệu nguồn; hơn cả pretrain trên đầu ra mô hình vật lý chưa hiệu chỉnh (tóm tắt không cho số) | gộp nhiều nguồn đa dạng tốt hơn một nguồn |
| 3 | Zhi et al. 2021, Environ. Sci. Technol. 55(4):2357–2368 | 10.1021/acs.est.0c06783 | LSTM DO trên 236 sông Mỹ (CAMELS-chem) | mô hình học được quan hệ hòa tan (DO giảm khi nhiệt tăng); **không tốt hơn ở trạm nhiều dữ liệu hơn**; tốt ở nơi biến động thấp | quan hệ T→DO là thứ imputer cần; số liệu theo ngày, sông |
| 4 | Peng et al. 2022, Water Research | 10.1016/j.watres.2022.119171 | Transformer + tinh chỉnh lặp (TLT), 120 trạm sông/hồ Trung Quốc; pH, DO, NH3-N, COD | "cải thiện độ chính xác dự báo dài hạn" ở trạm ít dữ liệu (phần đã đọc không có số) | cùng bộ biến với sensor VN; nước ngọt |
| 5 | Zhou et al. 2021, Sensors 21:7271 | 10.3390/s21217271 | chuyển giao đa nguồn trên **HK EPD** (~15 ngày/mẫu); DO, PO4, nhiệt độ, NO2 | MSE không chuyển giao → chuyển giao: 0,0167 → 0,0048 (−71 %, "Oxtail Sea" theo bài) và 0,0128 → 0,0104 (−19 %, Western Buffer) | **dùng đúng bộ HK EPD**; gần thang tháng; chỉ 2 vùng đích |
| 6 | Michieletto, Ouyang & Wills 2020, Proc. SPIE 11395 | 10.1117/12.2560794 (doi.org trả 302 → SPIE; nội dung chỉ từ kết quả tìm kiếm, K3) | DO trại cá, dữ liệu nhỏ, thiếu, nhiễu; chuyển giao từ bộ chất lượng nước lớn + loss correntropy | chỉ mô tả định tính trong tóm tắt | gần bài toán nhất (trại cá) nhưng không có số |
| 7 | Ansari et al. 2024 (Chronos); Das et al. 2023 (TimesFM) | arXiv:2403.07815; arXiv:2310.10688 | mô hình nền pretrain trên kho chuỗi thời gian lớn | (chung) zero-shot cạnh tranh với mô hình học riêng | RL-62: đã thắng ridge cho nhiệt độ Cát Bà; là **mốc phải vượt** |
| 8 | Lv et al. 2025, Frontiers in Water | 10.3389/frwa.2025.1635275 | DOM ao nuôi từ phổ, tinh chỉnh năm 2023 → 2024 (150 → 88 mẫu) | R² +30,67 %, RMSE −17 % | bằng chứng yếu: viễn thám, n nhỏ, không phải chuỗi thời gian |
| 9 | He et al. 2025 (tóm tắt hội nghị XMAS) | không có DOI; https://www.aconf.org/conf_198615/abstract/577.html | cửa Châu Giang: pretrain trên mô phỏng số, tinh chỉnh trên quan trắc | độ chính xác 86 % (N vô cơ), 82 % (P hoạt tính) | chỉ là tóm tắt hội nghị |

Đánh giá trung thực:

- Bằng chứng mạnh nhất là **sông, hồ, dòng chảy** (1–4). Cho **ven biển / nuôi lồng** chỉ có 5 (HK, mẫu tháng) và 6 (không có số). Không tìm thấy bài nào pretrain trên dữ liệu nước ngoài rồi tinh chỉnh cho **cảm biến lồng nuôi biển** tần suất cao.
- Mức lợi 10–70 % thường ở bài toán mà đích **đã có một ít dữ liệu** và nguồn **giống đích**; bài 1 cho thấy chọn nguồn sai làm chuyển giao kém đi.
- Với dự báo nhiệt độ Cát Bà, phần lớn lợi ích "kiến thức có sẵn" đã có qua mô hình nền zero-shot (RL-62). Phần còn trống là **mùa đông chưa thấy**, và không bài nào chứng minh pretrain nước ngoài lấp được khoảng đó.

## 7. Đề xuất bước tiếp (chủ dự án quyết)

1. **(b) trước, vì rẻ và có bằng chứng hơn:** dùng HK EPD đã có, lọc trạm chế độ biển, huấn luyện imputer cùng bộ đặc trưng `FEATURES_4` (NH3 = UIA, pH, Temp, SS mg/L, + tháng). Kiểm tra trên **QN đo thật** theo 3 cách: (i) chỉ VN (hiện tại), (ii) chỉ HK zero-shot, (iii) HK pretrain + tinh chỉnh VN; CV bỏ một đợt. Báo R²/MAE theo đích và tỷ lệ "<LOQ". Nếu (iii) không hơn (i) → dừng, không tải thêm.
2. Nếu bước 1 có lợi: tải HK 1986–2014 và Đài Loan OCA (một lần, ghi manifest sha256, `data/foreign/<tên>/SOURCES.md`), lặp lại.
3. **NERRS nutrient** (vài MB): ghép với sonde đã có; dùng mẫu 24 h để ước lượng thiên lệch DO ban ngày.
4. **(a):** chỉ làm sau khi có ≥ 1 mùa đông thật ở Cát Bà hoặc khi Chronos shadow chạy đủ 4 tuần. Thử nghiệm: pretrain Temp/pH/đục trên NERRS + IRLON, so với Chronos zero-shot và ridge + chu kỳ ngày trên cùng lockbox, gate #16. Song song thử pretrain mùa vụ bằng GLORYS12 tại NB1 (đã có).
5. Gửi thư hỏi dữ liệu: FRA / tỉnh Kumamoto (Ariake), HK EPD (phao khoa học), HK AFCD (FCZ), Viện Hải dương học Quảng Tây / Vịnh Bắc Bộ. Không chờ để làm bước 1–3.
6. Xác minh trước khi dùng: giấy phép AIMS MMP; cột NH4 của KOEM Songdo; số mẫu thực của Đài Loan OCA.
