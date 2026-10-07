# Chính sách dữ liệu — cái gì lên GitHub, cái gì giữ local

Repo GitHub `2imPusc/Hydro-Aqua-Predict` để **private**. Dù private, vẫn không đưa lên git:
secret, dữ liệu quan trắc gốc, và file nặng có thể tái tạo. Danh sách file local
cần có (kèm sha256) nằm ở [data-manifest.md](data-manifest.md).

## 1. Đẩy lên GitHub (tracked)

| Nhóm | Đường dẫn | Ghi chú |
| --- | --- | --- |
| Code | `core/`, `app/`, `hap_shared/`, `ingest/*.js`, `ingest/app_crawler.py`, `research-map/` (trừ cache), `scripts/`, `experiments/*.py` | |
| Test | `tests/`, `pytest.ini` | |
| Tài liệu | `docs/`, `README.md`, `AGENTS.md`, `report/` | Báo cáo/slide nguồn `.tex/.md/.png/.pdf`; file build LaTeX bị ignore |
| Cấu hình | `ingest/stations.yaml`, `.env.example`, `research-map/.env.example`, `requirements*.txt` | Không chứa credential |
| Model runtime nhỏ | `core/models/**` (~14 MB) | Imputer, forecast, contextual, spatial. Cần để pipeline chạy ngay sau khi clone |
| Ngưỡng phân loại | `hap_shared/thresholds/*.json` | Vendored từ DATN `model/output/` |
| Gate không gian | `assets/spatial_applicability/*.json` | |
| Kết quả thí nghiệm dạng tóm tắt | `experiments/*.md`, `experiments/*.png`, `experiments/RESULTS.md` | Chỉ bảng/biểu đồ tổng hợp |
| Ảnh tham khảo | `ingest/thongtin tram.png` | Ảnh dashboard 4 trạm, không có credential |

## 2. Không đẩy (gitignored, giữ local)

| Nhóm | Đường dẫn | Lý do |
| --- | --- | --- |
| **Secret** | `.env`, `research-map/.env` | MongoDB URI, tài khoản GreenLab (`TK_DHTB`/`MK_DHTB`), mật khẩu Postgres |
| **Tài liệu bàn giao có credential** | `data/greenlab/handover/*.docx` | Chứa chuỗi kết nối MongoDB kèm mật khẩu dạng plaintext |
| Dữ liệu sensor GreenLab gốc | `data/greenlab/exports/**` (~268 MB), `data/greenlab/greenlab_export.csv` | Dữ liệu quan trắc gốc của đối tác; lớn; append-only |
| Dữ liệu quan trắc tỉnh | `data/{haiphong,quangninh,hungyen}/clean_data.csv` | Thuộc sở hữu cơ quan quan trắc; dùng cho đồ án/nghiên cứu |
| Dữ liệu ngoài | `data/depth/*.nc` (Copernicus), `data/haiphong/_cmems_cache/` | Có thể tải lại từ nguồn; giấy phép riêng |
| Water mask | `data/map/water_polygons_clip/` (2.3 MB) | Cắt từ OSM water polygons (ODbL); tạo lại bằng `scripts/clip_water_mask.py` |
| Toạ độ trạm | `data/map/station_coordinates.csv` | Danh mục trạm quan trắc tỉnh |
| Output thí nghiệm | `artifacts/experiments/**` (~307 MB; `forecast-v2` 233 MB) | Tái tạo được bằng script; vượt giới hạn hợp lý của git |
| Model cũ | `artifacts/legacy-models/` | Bản cũ của `core/models`, không còn được code dùng |
| Trạng thái runtime | `runtime/**` | Log shadow runner, forecast/outcome JSONL |
| Cache research-map | `research-map/cache/**` | Worker tự sinh lại |
| Môi trường | `.venv/`, `node_modules/`, `dist/` | |

## 3. Cần chủ dự án quyết định

Các mục dưới đây nhỏ và giúp bản clone mới chạy được ngay, nhưng có câu hỏi về quyền sở hữu hoặc giấy phép:

| Mục | Kích thước | Hiện trạng | Cách đổi |
| --- | --- | --- | --- |
| `data/map/station_coordinates.csv` | 4 KB | Không track | Muốn đẩy: thêm `!/data/map/station_coordinates.csv` vào `.gitignore` |
| `data/map/water_polygons_clip/` | 2.3 MB | Không track | Muốn đẩy: bỏ ignore và ghi nguồn OSM (ODbL) trong README |
| `haiphong_exogenous.csv` (ở gốc) | 56 KB | **Đang track** (giống DATN) | Bảng dẫn xuất từ `clean_data` HP và dữ liệu thời tiết bàn giao. Không được phép chia sẻ thì `git rm --cached haiphong_exogenous.csv` và thêm vào `.gitignore` |

## 4. Khôi phục dữ liệu trên máy mới

1. Clone repo, rồi tạo `.env` từ `.env.example`.
2. Chép thư mục `data/` từ bản backup (hoặc từ DATN theo bảng ánh xạ dưới).
3. Chạy `python scripts/data_manifest.py --check`; mọi dòng phải `match`.

| Nguồn trong DATN-20225064 | Đích trong repo này |
| --- | --- |
| `realtime-data/exports/` | `data/greenlab/exports/` |
| `realtime-data/greenlab_export.csv` | `data/greenlab/greenlab_export.csv` |
| `data/map/station_coordinates.csv` | `data/map/station_coordinates.csv` |
| `data/{haiphong,quangninh,hungyen}/clean_data.csv` | cùng đường dẫn |
| `data/haiphong/_cmems_cache/` | cùng đường dẫn |
| `data/depth/haiphong_copernicus_bathymetry_100m_202511.nc` | cùng đường dẫn |
| `map/water-polygons-split-4326/` (1.2 GB) | chạy `scripts/clip_water_mask.py --source ...` |
| `lab-realtime/experiments/output/` | `artifacts/experiments/` |
| `lab/models/spatial/` | `core/models/spatial/` (tracked) |
