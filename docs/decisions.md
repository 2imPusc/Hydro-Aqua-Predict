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
