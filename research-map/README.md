# Research Map

Ứng dụng bản đồ nghiên cứu (research only, **shadow mode**) cho vùng nuôi lồng Cát Bà / Hải Phòng.
Không có gì ở đây phát cảnh báo hay khuyến nghị tới người nuôi; không thay đổi bán kính HSI,
độ tin cậy hay logic alert của `core/`.

- **Giám sát vùng biển** (`#/monitor`): context môi trường (gió, sóng, dòng chảy, mưa, mực nước,
  độ sâu), cảm biến GreenLab `06M26042804`, vùng HSI lịch sử, mạng trạm, dòng chảy. Cần Postgres + worker.
- **Các hướng nghiên cứu** (đọc file, không cần Postgres):
  - `#/forecast` H1 · dự báo ngắn hạn: ledger shadow `runtime/forecast-shadow/long_*.jsonl` + benchmark gate #16.
  - `#/weather` H2 · độ phủ snapshot thời tiết Open-Meteo (chỉ quan sát, không lái alert).
  - `#/zoning` H3 · bản đồ phù hợp nuôi trồng VN / HK, biến thể `N1_W_SUM` | `A_W_SUM`.
  - `#/reliability` H4 · độ tin cậy ngoại suy không gian: lớp chế độ mặn VN và kiểm chứng
    trên bộ dữ liệu nước ngoài (`#/reliability/foreign/<id>`).
- **Cảnh báo theo trạm** (`#/alerts`): sổ shadow `runtime/hazard-shadow/hazard_*.jsonl` (`core/hazard_runner.py`,
  `experiments/ecmwf_opendata.py`); lý thuyết, không gửi thông báo. **Cấu hình cảnh báo** (`#/settings/alerts`):
  admin chỉnh ngưỡng / hành động, mỗi lần lưu là một phiên bản mới (decisions #20, chưa có phân quyền).

Thiết kế/tiến trình: [`docs/superpowers/plans/2026-10-17-research-map-redesign.md`](../docs/superpowers/plans/2026-10-17-research-map-redesign.md),
lộ trình cũ: [`docs/guide/23-research-map-implementation-roadmap.md`](../docs/guide/23-research-map-implementation-roadmap.md).

## Chạy

**Docker** (đọc `research-map/.env`, không đọc `.env` gốc):

```powershell
cd research-map
Copy-Item .env.example .env      # điền TK_DHTB / MK_DHTB nếu muốn worker poll GreenLab
docker compose up --build        # frontend :8083, api :8010 (/docs), postgres :5434
```

**Dev local** (Postgres trong Docker; API, worker, Vite chạy trên máy):

```powershell
powershell -ExecutionPolicy Bypass -File research-map\dev-local.ps1 [-NoWorker]
# api http://localhost:8010/docs · vite http://localhost:5173 (5174 nếu 5173 bận)
```

Chỉ chạy một stack (docker hoặc `dev-local.ps1`) tại một thời điểm — cả hai dùng cổng 8010/5434.

- API **khởi động được khi không có Postgres**: các endpoint `/api/v1/research/*` (đọc file) vẫn chạy;
  endpoint dựa trên DB trả `503 {"status":"unavailable","reason":"database_unavailable"}` (kèm header CORS),
  `/api/v1/status` báo `degraded`.
- CORS mặc định cho `localhost` và `127.0.0.1` ở cổng 5173, 5174, 8083; đổi bằng `CORS_ALLOW_ORIGINS` (phân cách dấu phẩy).
- Frontend gọi `VITE_CONTEXT_API_URL` (mặc định `http://localhost:8010/api/v1`).

Test / build:

```powershell
cd research-map\backend-fastapi; $env:PYTHONPATH='.'; .venv\Scripts\python -m pytest tests -q
cd research-map\frontend; npm run build      # tsc -b && vite build
```

## Xuất artifact nghiên cứu

Các view H1–H4 đọc JSON nhỏ đã xuất sẵn từ các run trong `experiments/RESULTS.md`:

```powershell
.venv\Scripts\python scripts\export_research_map_artifacts.py [--stamp 20261017-1500]
```

Mỗi lần chạy ghi một thư mục mới `artifacts/research-map/<YYYYMMDD-HHMM>/` (write-once, kèm
`manifest.json` có sha256 nguồn/đầu ra và danh sách output bị bỏ qua + lý do). API luôn phục vụ thư mục
mới nhất có `manifest.json`; thư mục cũ không bị sửa. Input thiếu thì bị bỏ qua, không bao giờ điền giả.
Docker mount repo read-only tại `/workspace`, nên export trên máy host hiện ngay trong container.

## Endpoint

Giám sát (Postgres): `GET /api/v1/health`, `/context/latest`, `/context/{snapshot_id}/layers/{layer}`,
`/stations`, `/stations/{serial}/latest`, `/stations/{serial}/context`, `POST /stations/{serial}/observations`
(token `SENSOR_INGEST_TOKEN`), `/flow/latest`, `/flow/scenarios`, `/flow/{id}/artifact|streamlines|station-routes`.
Lớp tĩnh/cache: `/hsi-zones`, `/aquaculture-map`, `/context-domain`, `/station-network`,
`/bathymetry/manifest|depth-bands|contours|sample`.

Trạng thái: `GET /api/v1/status?station=` — tóm tắt nhẹ context / sensor / research (`fresh|stale|unavailable`, tuổi dữ liệu,
`export_version`); nhớ lỗi DB vài giây để không chặn top bar.

Nghiên cứu (`/api/v1/research`, chỉ đọc file):

| Endpoint | Nguồn |
| --- | --- |
| `/overview` | headline/finding H1–H4 |
| `/forecast/benchmark` | bảng gate #16 + conformal coverage |
| `/forecast/long?station=` | ledger shadow `runtime/forecast-shadow/long_*.jsonl` (`used_by_alerts: false`) |
| `/weather/status?station=` | `weather-snapshots.jsonl`, độ phủ 24 h / 7 ngày |
| `/hazards` | `hazards.json`: khí hậu + kỹ năng báo trước bão, nắng nóng, dịch bệnh, lịch thả giống (lý thuyết, chưa kiểm chứng hiện trường) |
| `/suitability?region=vn\|hk&variant=N1_W_SUM\|A_W_SUM` | ô phù hợp + trại + AUC |
| `/reliability/vn` | lớp chế độ mặn VN (A6) |
| `/reliability/foreign` | thẻ bộ dữ liệu nước ngoài |
| `/reliability/foreign/{id}?var=&scale=&transfer=` | trạm, thống kê theo cặp, bảng bán kính |
| `/reliability/summary` | bán kính gate 80 % xuyên bộ dữ liệu |

Khi thiếu export hay file, endpoint trả `{"status":"unavailable","reason":...}` thay vì lỗi.

Cảnh báo shadow: `GET /api/v1/research/hazards/stations` (bậc hiện tại + 5 khối 24 h theo trạm; `date` = ngày địa
phương có 12:00 nằm trong khối), `/research/storms/active` (ECMWF Open Data ENS). Cấu hình (`/api/v1/admin`, chưa
có phân quyền): `GET /alert-config`, `/alert-config/versions`, `/alert-config/versions/{v}`,
`POST /alert-config/preview` (không ghi), `POST /alert-config` (body ≤ 256 KB; 201 / 422 / 503 khi thư mục không ghi được).

## Nguồn dữ liệu và giấy phép

- **Maryland DNR (Chesapeake, Eyes on the Bay)**: chính sách không cho phát tán lại dữ liệu thô — chỉ xuất
  thống kê tổng hợp theo cặp/bán kính và toạ độ trạm. Ghi công: *Data provided by the Maryland Department of
  Natural Resources, Tidewater Ecosystem Assessment Division.*
- **Hong Kong EPD**: điều khoản sử dụng chưa được xác minh trong repo → cũng chỉ xuất thống kê tổng hợp.
- **NOAA NERRS SWMP** (CDMO, qua NCEI), **USGS NWIS**, **TWDB Texas Coastal Hydrology**, **IRLON** (HBOI-FAU, qua
  SECOORA ERDDAP): dữ liệu công khai; ghi công đầy đủ hiển thị trên từng thẻ bộ dữ liệu.
- Context môi trường: Open-Meteo (lưới mẫu ~1 km, mô hình dòng chảy ~8 km — không tăng độ phân giải thật);
  Copernicus / GEBCO chỉ hiện khi đã cấu hình, không bao giờ lấy giá trị từ nguồn khác bù vào.
- Độ sâu mặc định: **GEBCO 2024 15″** (~460 m, so với mực nước TB, không phải số 0 hải đồ; không dùng cho hàng hải)
  kèm lưới **TID** nên mỗi isoband có `confidence` = `direct` (TID 10–17, đo trực tiếp; vẽ đậm) | `indirect`
  (TID 40–45, nội suy/dự đoán) | `unknown` | `coarse` | `suspect` (mờ, viền đứt). Trong vùng chỉ ~3 % ô là đo trực tiếp,
  ~97 % là nội suy. Tải một lần bằng `python scripts/download_gebco2024_bathymetry.py`
  (`data/depth/gebco2024-20261023/gebco2024_15s_hp_qn.nc`, write-once; đổi đường dẫn bằng `GEBCO_BATHYMETRY_PATH`).
  Worker dựng artifact vào `cache/bathymetry-gebco/<key>/` (hoặc `python -m app.bathymetry_gebco`); lỗi chỉ ghi log,
  API trả `building` / `unavailable`. API `/bathymetry/gebco/manifest|isobands|isobaths|flags?lod=`;
  `/bathymetry/sample` có khoá `gebco` (độ sâu + lớp TID) bên cạnh `etopo`. GEBCO không bao giờ lấp chỗ trống của SDB.
  Ghi công: GEBCO Compilation Group (2024) GEBCO 2024 Grid.
- **ETOPO 2022 15″** vẫn còn như lớp so sánh (tắt mặc định, bật "So sánh: ETOPO 2022" trong Độ sâu):
  `data/depth/etopo2022-20261023/`, `cache/bathymetry-etopo/<key>/`, API `/bathymetry/etopo/...`. Có hố sâu giả ở Cửa Lục / Vân Đồn
  (cờ `suspect`). Copernicus SDB 100 m chỉ còn là lớp "bãi triều" (gần như không có pixel quanh Cát Bà / Hạ Long).
  Đánh giá: [`docs/eval/2026-10-23-bathymetry-map.md`](../docs/eval/2026-10-23-bathymetry-map.md),
  [`docs/eval/2026-10-24-gebco-vs-etopo.md`](../docs/eval/2026-10-24-gebco-vs-etopo.md).
- Dữ liệu cảm biến GreenLab là append-only; đơn vị NH4 vẫn chờ xác nhận nhà cung cấp.

Credit/licence của từng bộ nằm trong `FOREIGN` của `scripts/export_research_map_artifacts.py` (lấy từ
`data/foreign/*/SOURCES.md`).

## Frontend

React 18 + Vite 6 + Tailwind v4 + Leaflet, `frontend/src/`:

- `app/` — shell (rail điều hướng, top bar trạng thái từ `/status`), router theo hash (`routes.ts`), `LiveDataContext`.
- `views/<monitor|forecast|weather|zoning|reliability>/` — mỗi view lazy-load; `views/shared/research.tsx` cho trạng thái unavailable/finding.
- `components/ui` (Chip, Segmented, Select, Legend, Panel…), `components/charts` (SVG thuần), `components/map` (`ResearchMap`, canvas layer).
- `api/` client theo nhóm endpoint, `types/` khớp schema backend, `lib/format.ts` (nhãn tiếng Việt), `lib/palette.ts` (thang màu).

Design token là CSS custom properties trong `src/style.css` (`--bg`, `--surface*`, `--fg*`, `--accent`,
`--ok|warn|danger|info|mock|neutral` + `-bg`/`-line`, `--radius-*`, `--shadow-*`, `--series-*`), có bộ giá trị
riêng cho `[data-theme="dark"]`. Dữ liệu mock luôn mang tông `--mock` và nhãn riêng.

## Ranh giới

- Database riêng `context_research`; worker lưu snapshot bất biến mỗi 30 phút và bảng `sensor_observations`
  append-only (insert idempotent, không ghi đè). Lỗi provider giữ giá trị tốt cuối và hiện là `stale`.
- `stale` = đang phục vụ snapshot cũ quá hạn, không phải giá trị hiện tại.
- API không bao giờ ghi vào `artifacts/`, `runtime/` hay `data/`, trừ một ngoại lệ (decisions #20): tạo file phiên bản
  mới (tạo độc quyền, không ghi đè, không xóa) trong `runtime/alert-config/`. Docker mount riêng thư mục này ghi được.
