# Nhật ký quyết định

Mỗi mục gồm: ngày, quyết định, lý do, hệ quả. Mục mới thêm ở cuối. Không sửa mục cũ; nếu đổi ý, thêm mục mới và ghi "thay thế #N".

## #1 — 2026-10-08 · Tách khỏi DATN-20225064 bằng cách chép, không di chuyển

- **Quyết định:** chép `lab-realtime/`, `realtime-data/` và các file dữ liệu cần dùng sang repo riêng. Import mới, không giữ lịch sử git. Bản trong DATN giữ nguyên để phục vụ đồ án.
- **Lý do:** sản phẩm realtime cần phát triển độc lập với đồ án. Lịch sử git chỉ có 2 commit nên không đáng giữ.
- **Hệ quả:** `hap_shared/` là bản sao của DATN `src/` (scoring, preprocessing) và từ nay do repo này sở hữu. Không import ngược về DATN.

## #2 — 2026-10-08 · Mọi đường dẫn đi qua `core/paths.py`

- **Lý do:** code cũ tự dò thư mục bằng `parents[N]`, nên sẽ âm thầm trỏ sai khi bố cục thư mục thay đổi.
- **Hệ quả:** `data/`, `artifacts/`, `runtime/` có thể chuyển sang ổ khác bằng biến `HAP_*`. `scripts/check_isolation.py` chặn trường hợp import hoặc đường dẫn thoát ra ngoài repo.

## #3 — 2026-10-08 · Hai virtualenv

- **Lý do:** streamlit 1.64 kéo theo một phiên bản starlette làm hỏng fastapi 0.115 (lỗi `Router.__init__() got an unexpected keyword argument 'on_startup'`).
- **Hệ quả:** venv gốc dùng cho core, app, test, experiments; `research-map/backend-fastapi/.venv` dùng cho API và worker.

## #4 — 2026-10-08 · Dữ liệu không vào git; output thí nghiệm là artifact

- **Quyết định:** `data/` (đầu vào), `artifacts/` (output tái tạo được), `runtime/` (trạng thái chạy) đều gitignored. Bảng chỉ mục `experiments/RESULTS.md` và `docs/data-manifest.md` thì được track.
- **Lý do:** dữ liệu thuộc đối tác và cơ quan quan trắc, có file chứa credential, và output thí nghiệm nặng khoảng 300 MB.

## #5 — 2026-10-08 · Water mask cắt theo vùng

- **Quyết định:** dùng tập con các polygon OSM giao với bbox 105.5–108.5°E × 20–22°N (2.3 MB) thay cho file toàn cầu 1.2 GB.
- **Kiểm chứng:** hình học trùng khít bản gốc ở 6 vùng thử (`equals=True`). Tạo lại bằng `scripts/clip_water_mask.py`.

## #6 — 2026-10-10 · Cut-over sang repo mới

- **Quyết định:** disable task `DATN-WeatherSnapshot-06M26042804` (không xóa). Bật `HAP-WeatherSnapshot-06M26042804`. Stack research-map chạy từ repo này và dùng chung volume Postgres `research-map_context_postgres_v1`.
- **Đồng bộ:** `weather-snapshots.jsonl` (đã kiểm tra bản mới là phần đầu của bản DATN trước khi chép), collector log và `research-map/cache`.

## #7 — 2026-10-10 · Task thu bản tin chạy cả khi dùng pin

- **Lý do:** với cấu hình mặc định "no start on batteries", task bị xếp hàng chờ khi laptop chạy pin, tạo khoảng trống trong chuỗi bản tin. Trong khi đó B5 cần chuỗi bản tin liên tục.
- **Hệ quả:** thêm `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`. Mỗi lần chạy chỉ mất vài giây.

## #8 — 2026-10-10 · Thứ tự ưu tiên 1 → 2 → 4 → 3

- **Quyết định của chủ dự án:** dự báo sâu → cảnh báo thời tiết → bản đồ tin cậy → bản đồ phân vùng. Slide đề xuất làm 3 song song, 4 sau 3.
- **Hệ quả:** hướng 4 dùng tạm bộ chấm điểm theo luật hiện có, đặt sau interface `SuitabilityScorer`, để hướng 3 lắp vào sau mà không phải làm lại. Chi tiết ở [roadmap.md](roadmap.md).

## #9 — 2026-10-10 · Test cô lập và có thể chạy trên CI

- **Quyết định:** test cần `data/` được gắn marker `requires_data` và tự skip khi thiếu dữ liệu. Test NH4 dùng monkeypatch thay vì đọc `.env` thật. Thêm CI GitHub Actions (core, backend, frontend).
- **Hệ quả:** có dữ liệu: 136/136 pass. Không có dữ liệu: 133 pass, 3 skip. Backend: 14/14 (đã thêm `h5py`, cho test ghi netCDF bằng `engine="h5netcdf"`).

## #11 — 2026-10-15 · Kho lịch sử sensor chuẩn

- **Quyết định:** nguồn chuẩn là các file append-only trong `data/greenlab/exports/` (`all_data/`, `intervals/`, `live-cache/`), gộp bằng `core.greenlab_api.load_cached_history()`. Postgres của research-map chỉ phục vụ bản đồ. Benchmark đọc bản xuất cố định từ `scripts/export_sensor_history.py` (có sha256 trong manifest).
- **Lý do:** Postgres chỉ có những ngày worker chạy; `DataByDate` lấy lại được mọi ngày.
- **Hệ quả:** `HAP-SensorCollector` (Task 9) giữ kho này liên tục.

## #12 — 2026-10-15 · Múi giờ trong file export GreenLab

- **Kết quả kiểm tra:** so dữ liệu `DataByDate` vừa backfill với cache live (có múi giờ UTC) trên 7 mốc trùng: dịch −7 h khớp tuyệt đối (sai lệch trung vị Temperature/pH/TSS = 0/0/0); 0 h lệch 1.0/0.03/4.65. File `all_data/*_All.csv` khớp với `intervals/` ở 0 h, tức cùng quy ước. Các ngày ở ranh giới file chỉ có 1.020/1.440 phút khi chia theo ngày địa phương.
- **Quyết định:** giá trị thời gian không có múi giờ trong `all_data/` và `intervals/` (cột `Date` và `fetchedAt`) là giờ Asia/Ho_Chi_Minh; `core.greenlab_api._normalize_export` localize rồi đổi sang UTC. Giá trị đã có múi giờ giữ nguyên.
- **Hệ quả:** mọi kết quả trước ngày này dựng từ các file export (forecast-v2, weather-risk-pilot, retrospective…) dùng mốc lệch 7 h: ghép thời tiết và đặc trưng giờ trong ngày bị sai; chuỗi gộp với cache live bị lệch giữa hai nguồn. Phải chạy lại trên bản xuất mới (Task 10). `core/forecast_train.py` (mô hình XGBoost cũ) vẫn đọc `all_data` trực tiếp, chưa sửa — việc tiếp theo.

## #10 — 2026-10-16 · Thứ tự ưu tiên 1 → 2 ‖ 3 → 4 (thay thế #8)

- **Quyết định của chủ dự án:** mạch chính 1 → 2. Hướng 3 chạy song song để lấp khoảng chờ dữ liệu của hướng 2. Hướng 4 chỉ làm sớm H4.1 (sửa HSI rò rỉ) và H4.2 (interface); H4.3–H4.5 chờ verdict B5 (H2.2) và một điểm đo đối chứng.
- **Lý do:** hướng 2 bị giới hạn bởi lịch (cần ~63 ngày bản tin as-issued liên tục, không backfill được). Hướng 4 có mức sẵn sàng thấp, phụ thuộc kết quả hướng 2 và phần cứng (chỉ 1 sensor). Hướng 3 đã có dữ liệu quan trắc và có phương pháp tham khảo (Ghaderi 2026).
- **Hệ quả:** cập nhật bảng ưu tiên trong `roadmap.md`. Kế hoạch: `docs/superpowers/plans/2026-10-15-master-execution-plan.md`. Ghi chú: mục #10 được ghi sau #11, #12 vì chờ chủ dự án xác nhận.

## #13 — 2026-10-16 · Cho phép bản tin dựng lại (`reconstructed_run`) cho phân tích sơ bộ

- **Quyết định của chủ dự án:** dùng bản tin lưu trữ của Open-Meteo (Previous Runs API) để chạy B5 và các thử nghiệm thời tiết của hướng 1 ngay, không chờ đủ 63 ngày `captured_live`.
- **Điều kiện:** gắn nhãn `reconstructed_run` và không bao giờ trộn với `captured_live`. Bản tin "phát hành trước N ngày" chỉ coi là có sẵn sau mốc run + độ trễ an toàn (mặc định 12 h). Kết luận chỉ là sơ bộ; kết luận chính thức vẫn dùng `captured_live`.
- **Lý do:** kho lưu trữ có đủ 100 % số giờ cho 2026-07-26 → 2026-10-14 tại NB1 (đã kiểm tra), tức ~80 ngày origin có sẵn ngay.

## #14 — 2026-10-16 · Dữ liệu thử nghiệm hướng 4: NERRS Jobos Bay (chính), HK EPD (phụ)

- **Quyết định:** thử phương pháp bản đồ tin cậy trên NERRS Jobos Bay (Puerto Rico, 18°N; 4 trạm chất lượng nước 15 phút, cách trạm khí tượng 1.8–4.2 km). Trước mắt dùng bản lưu trữ NCEI 1995–2011; dữ liệu gần đây sẽ lấy qua form CDMO khi chủ dự án đăng ký xong. HK EPD (94 trạm, đo hằng tháng, cùng bộ chỉ số với HP/QN) là bộ phụ cho phần suy giảm theo khoảng cách và kiểm chứng hướng 3. USGS là dự phòng.
- **Lưu ý:** chỉ chuyển phương pháp và gate, không chuyển con số. Áp dụng ở VN vẫn cần ≥ 1 điểm đo đối chứng (H4.4).

## #15 — 2026-10-16 · Thử hiệu chỉnh tiêu chí phù hợp cho lồng gần bờ (hướng 3)

- **Quyết định:** thử một bộ tiêu chí gần bờ bên cạnh bộ của Ghaderi. Ngưỡng phải đặt trước, theo tài liệu và thực tế nuôi lồng ven bờ, **không** chỉnh để khớp với các vùng nuôi OSM dùng làm kiểm chứng.
- **Hệ quả:** mọi thử nghiệm ghi vào `docs/research-log.md` (nhật ký nghiên cứu, ngắn gọn, đủ thông tin).

## #16 — 2026-10-16 · Gate đánh giá dự báo cho chân trời dài (H1.2)

- **Quyết định:**
  - Bỏ điều kiện "MASE < 1": MASE chuẩn hóa theo sai số naive 1 bước, nên ở chân trời 720 phút chính persistence cũng có MASE ≈ 12.
  - Gate mới: thắng persistence ở ≥ 4/5 fold, và kiểm định Diebold–Mariano trên lockbox với loss tuyệt đối, kernel **rectangular**, p < 0.05.
  - Purge = max(60 phút, chân trời).
  - Không nhãn nào của fold trượt được chạm vào lockbox.
- **Lý do:** mô phỏng Monte Carlo cho thấy kernel Bartlett bác bỏ sai giả thuyết đúng tới 8–11 % (danh nghĩa 5 %), theo hướng có lợi cho mô hình. Kernel rectangular cho 5–7 %.
- **Hệ quả:** kết quả H1.1 (RL-03) dùng purge cũ và fold 5 có nhãn lấn sang lockbox. So với H1.2, các con số 15/30/60 phút có thể lệch nhẹ.

## #17 — 2026-10-22 · Hướng lý thuyết + dữ liệu công khai cho cảnh báo bão và nắng nóng

- **Quyết định:** cảm biến và lấy mẫu nước khó mở rộng, nên cảnh báo bão và nắng nóng đi theo hướng lý thuyết + dữ liệu công khai trước (chủ dự án chốt 2026-10-22).
  - Bão: IBTrACS v04r01 chỉ là **oracle** để tính mức phơi nhiễm tại NB1 (hồi cứu, khí hậu). Không dùng để nói về độ chính xác dự báo hay thời gian báo trước.
  - Ngưỡng lấy từ QĐ 18/2021/QĐ-TTg (cấp bão, cấp độ rủi ro), Sun & Chen 2014 (31 / 33 °C) và Le et al. 2024 (34 °C).
  - `hap_shared/thresholds/cobia_thresholds.json` **giữ nguyên**.
  - Bậc hành động tại lồng (cấp 6/8/10/12) và ngưỡng sóng cho lồng cần chuyên gia / người nuôi xem lại. Chưa có ngưỡng sóng.
- **Lý do:** tài liệu về nhiệt độ tối ưu của cá giò mâu thuẫn (27–29 °C cho cá ~22 g trong Le et al. 2024, so với 33 °C trong Sun & Chen 2014). Vì vậy mức nhiệt được gọi là rủi ro tăng trưởng/stress, không phải tử vong.
- **Hệ quả:** mọi đầu ra mang `used_by_alerts: False`, `notification_eligible: False`, `basis: "theory_only_unvalidated"`. Mapping Điều 42 của QĐ 18 lấy từ bản tóm tắt thứ cấp; cần đối chiếu bản .doc gốc trước khi dùng trong luận văn. Chi tiết: `docs/guide/27-hazard-advisory-theory.md`, RL-29, RL-30.

## #18 — 2026-10-23 · Dữ liệu tái phân tích phải ghi rõ mô hình

- **Quyết định:** mọi tải từ archive Open-Meteo phải truyền `models=` và ghi model vào tên file + manifest. "ERA5" chỉ dùng cho `models=era5`. File tải không có `models=` (best_match: ERA5 < 2017, ECMWF IFS 9 km từ 2017) chỉ được gọi là best_match/IFS.
- **Lý do:** review phát hiện file "ERA5" thực ra là IFS từ 2017; Previous Runs lead 0 trùng 100 %, nên đánh giá thời gian báo trước bị vòng tròn; con số Yagi 29.56 m/s sai nguồn (ERA5 thật 18.86 m/s).
- **Hệ quả:** đánh giá dự báo phải có chặn tự động "giá trị thật ≠ lead 0"; mô hình dự báo được cố định (`ecmwf_ifs025`). Các run bị thay thế liệt kê ở RL-31.

## #19 — 2026-10-23 · Nguồn độ sâu cho research-map: ETOPO 2022, không lấp SDB

- **Quyết định:** lớp độ sâu mặc định dùng NOAA ETOPO 2022 15″ (~460 m), dải độ sâu + đường đẳng sâu cắt theo mặt nước OSM, có cờ "thô"/"nghi ngờ". Copernicus SDB chỉ là lớp bãi triều, tắt mặc định; ETOPO không bao giờ được dùng để lấp chỗ trống của SDB.
- **Lý do:** SDB không có dữ liệu ở Cát Bà / Hạ Long; ETOPO phủ đều nhưng thô và có lỗi nguồn ở vài cửa sông.
- **Hệ quả:** chú giải ghi lưới, datum (EGM2008) và "không dùng cho hàng hải". Nâng cấp tiếp theo: GEBCO 2024 (kèm TID) hoặc hải đồ / đo sâu tại lồng.


## #20 — 2026-10-23 · Bậc cảnh báo do admin cấu hình; ngoại lệ ghi duy nhất của API

- **Quyết định (chủ dự án):** ngưỡng và hành động của các bậc cảnh báo được admin chỉnh ngay trong giao diện research-map (`#/settings/alerts`). Chưa làm tài khoản / phân quyền; thiết kế sau.
- **Ngoại lệ:** API research-map vốn không ghi file nào; nay được ghi **duy nhất** vào `runtime/alert-config/`, mỗi lần lưu là một file phiên bản mới (tạo độc quyền, không ghi đè, không xóa). Mặc định nằm trong `config/alert_tiers.default.json` (theo dõi bằng git).
- **Hệ quả:** mọi bản ghi cảnh báo shadow mang `config_version`; Docker cần mount ghi được riêng cho `runtime/alert-config/`. `MARINE_ENABLED` và task chạy tự động vẫn tắt cho tới khi chủ dự án bật. Hợp đồng: `docs/superpowers/plans/2026-10-23-phase1-parallel.md`.

## #21 — 2026-10-24 · Độ sâu mặc định: GEBCO 2024 (thay #19), ETOPO để so sánh

- **Quyết định:** lớp độ sâu mặc định của research-map dùng GEBCO 2024 15″ kèm lớp TID (đo trực tiếp / nội suy). ETOPO 2022 giữ làm lớp so sánh, tắt mặc định. SDB vẫn chỉ là lớp bãi triều, không lấp chỗ trống.
- **Lý do:** GEBCO không có các hố sâu sai của ETOPO ở Cửa Lục, Vân Đồn; TID cho biết ô nào được đo.
- **Hệ quả:** chú giải ghi "~97 % ô là nội suy", datum MSL, "không dùng cho hàng hải", ghi công GEBCO Compilation Group (2024). Thư viện tùy chọn cho dữ liệu nguy cơ (`eccodes`, `copernicusmarine`) nằm trong `requirements-hazards.txt`, không bắt buộc cho core/test.


## #22 — 2026-10-24 · Ngưỡng mặc định nguy cơ dịch bệnh 0.85 / 0.95

- **Quyết định (chủ dự án đồng ý đề xuất):** `disease_env` bậc 1/2 đổi từ 0.4/0.75 sang 0.85/0.95 trong `config/alert_tiers.default.json`.
- **Lý do:** chạy thật (RL-47) ngưỡng cũ đưa cả 14 trạm lên bậc 2 ở SST ~29.7 °C; chỉ số chưa có kỹ năng so với khí hậu (RL-34, RL-42), nên ngưỡng thấp chỉ tạo báo động bão hòa.
- **Hệ quả:** admin vẫn chỉnh được trong `#/settings/alerts`; xem lại khi có DO / độ mặn / sự kiện có tên mầm bệnh.
