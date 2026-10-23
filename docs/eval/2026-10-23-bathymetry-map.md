# Đánh giá lớp độ sâu và cách vẽ lớp bản đồ (research-map) — 2026-10-23

Phản hồi của chủ dự án: (1) quanh Cát Bà và Quảng Ninh (vịnh Hạ Long, Bái Tử Long) không thấy độ sâu;
(2) các lớp được vẽ thành ô vuông, xấu và trông không giống thực tế.

## 1. Chẩn đoán

Lớp độ sâu cũ chỉ lấy từ **Copernicus SDB 100 m** (độ sâu suy từ ảnh Sentinel-2,
`data/depth/haiphong_copernicus_bathymetry_100m_202511.nc`, lưới 1056 × 1056, ô ~115 m).

| Kiểm tra | Kết quả |
| --- | --- |
| Ô có giá trị trên toàn tile | 3 829 / 1 115 136 (0,34 %); sâu nhất 4,07 m, trung vị 0,60 m |
| Hộp Cát Bà – Lan Hạ (106.95–107.15, 20.68–20.85) | **0** ô có giá trị |
| Hộp vịnh Hạ Long (107.0–107.25, 20.82–20.98) | **0** ô |
| Hộp quanh NB1 | **0** ô |
| Hộp Bái Tử Long (107.3–107.6, 20.95–21.2) | 30 ô |
| Hộp cửa sông Hải Phòng (106.7–106.95, 20.6–20.9) | 1 820 ô (gần như toàn bộ dữ liệu) |

Nguyên nhân chính: **nguồn không có dữ liệu ở nơi cần xem**. SDB quang học chỉ ước được ở nước trong
và nông, nên ở đây gần như chỉ còn bãi triều cửa sông. Lỗi không nằm ở bbox hay mặt nạ nước.
Chỉ số "coverage 83 %" trong manifest dễ gây hiểu lầm vì mẫu số đã chỉ gồm các ô có giá trị âm.
Thang màu cũ 0–1,2 m cũng được chỉnh theo dữ liệu bãi triều này.
Thêm hai nguyên nhân phụ: `MAP_BOUNDS` cũ (106.78–107.28, 20.58–20.98) không cho kéo bản đồ tới
Bái Tử Long, và các ô SDB được gộp 4×4 hoặc 8×8 pixel thành ô vuông 0,5–1 km.

Các lớp mô hình (mưa, mực nước) được vẽ bằng một ô vuông ~1,2 km cho mỗi điểm truy vấn.
Lưới thật của mô hình lại thô hơn (mực nước ~8 km), nên nhiều ô cạnh nhau có cùng giá trị, tạo
mảng vuông vừa xấu vừa giả độ chi tiết.

## 2. Thay đổi

- **Nguồn mới: NOAA ETOPO 2022 15″** (~460 m, doi:10.25921/fd45-gt74), lấy qua OPeNDAP bằng
  `scripts/download_etopo2022_bathymetry.py`, lưu write-once vào `data/depth/etopo2022-20261023/` (kèm
  sha256 và URL). Vùng tải là 106.5–108.2 E, 20.3–21.6 N. Trong vùng có 74 888 ô nước OSM, trong đó
  70 449 ô có độ sâu. Độ cao lấy theo geoid EGM2008 (≈ mực nước trung bình), **không phải số 0 hải đồ**.
- `research-map/backend-fastapi/app/bathymetry_etopo.py` dựng artifact write-once vào
  `cache/bathymetry-etopo/<key>/`. Worker tự dựng, hoặc chạy `python -m app.bathymetry_etopo`; mất khoảng 40 s.
  - Nội suy song tuyến tính ×4, rồi làm trơn khoảng 1 ô để bỏ bậc thang do giá trị nguyên mét của GEBCO.
    Ô mà ETOPO coi là đất được lấy làm bờ 0 m, nên chỉ nội suy giữa lưới và bờ, không thêm chi tiết mới.
  - Có 7 isoband (0–2, 2–5, 5–10, 10–20, 20–30, 30–50, ≥ 50 m) và các isobath 2/5/10/20/30 m.
    **Mọi hình đều cắt theo mặt nạ nước OSM**, nên đường bờ theo OSM chứ không theo lưới 460 m.
  - Có hai cờ tin cậy, mỗi band được tách theo cờ để bản đồ làm mờ phần kém tin cậy:
    `coarse` là nước theo OSM nhưng ETOPO coi là đất (4 439 ô: lạch hẹp, đảo đá vôi);
    `suspect` là hố sâu > 30 m không thông ra vịnh Bắc Bộ (2 968 ô, đã tính viền 1 ô).
    **Không xoá hay sửa giá trị nào.**
  - API: `/api/v1/bathymetry/etopo/manifest|isobands|isobaths|flags?lod=`. `/bathymetry/sample` có thêm
    khoá `etopo` riêng, để ETOPO không lấp chỗ trống của SDB.
- Frontend:
  - Lớp "Độ sâu vùng biển" và "Đường đẳng sâu" bật mặc định. Dùng thang xanh một sắc độ (`SEQUENTIAL`
    đã kiểm định), nhãn isobath có viền chữ. Phần `coarse` mờ 0,32, phần `suspect` mờ 0,12 và có viền cam.
    Chú giải ghi rõ lưới, mốc độ cao và "không dùng cho hàng hải".
  - SDB được đổi tên thành lớp "Bãi triều (SDB vệ tinh)" và tắt mặc định.
  - `MAP_BOUNDS` được mở tới 106.55–107.95 E, 20.40–21.45 N.
  - Mưa, mực nước, MLD: thay ô vuông bằng **một trường canvas mượt**. Giữa các điểm mẫu dùng nội suy
    song tuyến tính, phần hiển thị cắt theo vùng nước context. Chú giải ghi lưới nguồn của mô hình.
    Trong backend, `source_grid_resolution` của mưa và mực nước được sửa: mực nước giờ ghi
    "~8 km (0.08°)" thay vì "display grid ~1.2 km".

## 3. Kiểm tra độ chính xác

**So với Copernicus SDB**, tại 2 510 pixel SDB hợp lệ, giá trị ETOPO lấy theo cách của endpoint sample:

| | Giá trị |
| --- | --- |
| Trung vị SDB / ETOPO | 0,59 m / 0,60 m |
| ETOPO − SDB: trung vị · trung bình · MAE · p90\|Δ\| | +0,06 · +3,4 · 3,9 · 9,6 m |
| Chỉ xét pixel có ô ETOPO gần nhất là biển (43 %) | MAE 7,0 m |
| Chỉ xét pixel có ô ETOPO gần nhất là đất | MAE 1,6 m |

ETOPO không phân giải được bãi triều. Ở ô biển, ETOPO sâu hơn SDB khoảng 7 m. Phép so sánh này còn bị
lệch mẫu, vì SDB chỉ có giá trị khi nước nông ≤ 4 m.

**Theo vùng** (trung vị độ sâu ETOPO trên ô nước OSM):

| Vùng | Trung vị | p10–p90 |
| --- | --- | --- |
| Quanh NB1 | 6 m | 2–9 m |
| Cát Bà – Lan Hạ | 11,5 m | 3–19 m |
| Vịnh Hạ Long | 5 m | 2–11 m |
| Bái Tử Long | 6 m | 2–28 m |
| Biển ngoài phía nam | 27 m | 22–32 m |

Các số này cùng bậc với mô tả chung về vịnh Hạ Long (nông, phần lớn khoảng 5–10 m). Tuy vậy
**chưa đối chiếu với hải đồ hay số đo hồi âm**, vì trong repo không có điểm đo nào để trích dẫn.

**Sai lệch rõ ràng:**

- Cửa Lục có giá trị 60–92 m.
- Cửa Ông – Vân Đồn – Tiên Yên – Đầm Hà có giá trị 90–149 m (ví dụ 107.40 E, 21.12 N: 88 m).
  Các vùng này thực tế nông, và ETOPO1 cũng cho giá trị tương tự, nên lỗi đến từ nguồn gốc dữ liệu
  (GEBCO), không phải từ bước tải. Những vùng này đều bị gắn cờ `suspect` và làm mờ.
- Tại NB1 (107.0426 E, 20.7189 N), giá trị song tuyến tính chỉ 1,0 m. Vị trí đặt lồng thực tế thường sâu hơn,
  do lưới 460 m kéo giá trị về bờ 0 m.
- Luồng nạo vét hẹp (Lạch Huyện, Cái Lân) không thể hiện được.
- Mốc độ cao lệch khoảng 1,5–2 m so với số 0 hải đồ (biên độ triều Hòn Dấu khoảng 3–4 m).

## 4. Ảnh trước / sau

Ảnh nằm trong thư mục scratchpad `.../scratchpad/ui/` của phiên làm việc, không commit:

- `bathy-before-*.png`: chỉ có SDB, Cát Bà và Hạ Long trống.
- `bathy-after-*.png` và `bathy-after-dark-*.png`: các khung 1 Cát Bà, 2 Hạ Long, 3 Bái Tử Long,
  4 Lan Hạ phóng to, 5 Vân Đồn (vùng `suspect`).
- `bathy-after-sealevel-smooth*.png`: trường mực nước vẽ mượt.

## 5. Giới hạn còn lại

- ETOPO/GEBCO trong vịnh đá vôi chủ yếu là nội suy. Cần **GEBCO 2024 kèm lưới TID** (cho biết ô nào đo
  trực tiếp, ô nào nội suy) hoặc DEM từ hải đồ Việt Nam / số đo tại lồng để có độ sâu đáng tin.
  Ngưỡng `suspect` 30 m chỉ là luật thô (heuristic).
- Mặt nạ OSM coi một số bãi bồi hoặc rừng ngập mặn là nước, nên chúng hiện thành vùng `coarse`.
- Sau khi merge, worker phải chạy lại để tạo `cache/bathymetry-etopo/`. Trước đó, API trả `building`.
- Mặc định ETOPO trên Docker là `/workspace/data/depth/etopo2022-20261023/...`. Cần chạy script tải trên
  máy host trước, rồi rebuild image backend (requirements thêm `contourpy`).
