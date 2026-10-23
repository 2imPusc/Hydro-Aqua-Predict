# GEBCO 2024 (kèm TID) so với ETOPO 2022 — research-map, 2026-10-24

Mục tiêu: xem GEBCO_2024 + lưới Type Identifier (TID) có thay ETOPO 2022 làm nguồn độ sâu mặc định
(decisions #19) được không, và các "hố sâu" của ETOPO có còn trong GEBCO không.

## 1. Dữ liệu

- Nguồn: kho BODC/CEDA, hai tile GeoTIFF 90°×90° `n90.0_s0.0_w90.0_e180.0` (sub-ice elevation 0,93 GB;
  TID 0,47 GB). Không cần tài khoản. Cách lấy nhỏ nhất dùng được: **HTTP range qua GDAL `/vsicurl/`
  (rasterio)**, chỉ đọc 312 hàng của bbox, nên tải vài MB chứ không phải 1,4 GB. WCS/WMS của gebco.net
  trả danh sách rỗng, không dùng được; chưa thử OPeNDAP/THREDDS vì range-read đã đủ.
- Script: `scripts/download_gebco2024_bathymetry.py` (write-once). Ra `data/depth/gebco2024-20261023/`
  `gebco2024_15s_hp_qn.nc` (650 KB, 312×408, cùng bbox 106.5–108.2 E, 20.3–21.6 N và cùng lưới với ETOPO)
  và `.json` (URL, sha256, kích thước/ngày remote, giấy phép).
- Giấy phép: GEBCO Grid thuộc public domain, cần ghi nguồn "GEBCO Compilation Group (2024) GEBCO 2024 Grid".
  Cao độ theo mực nước trung bình, không phải số 0 hải đồ; không dùng cho hàng hải.

## 2. Độ tin cậy theo TID (ô biển trong mặt nạ nước OSM, 72 295 ô)

| Lớp | TID | Số ô | Tỷ lệ |
| --- | --- | --- | --- |
| Đo trực tiếp | 10–17 (trong vùng chỉ có 11, 14, 17) | 1 921 | **2,7 %** |
| Nội suy / dự đoán | 40–45 (chủ yếu 40; 44) | 70 374 | **97,3 %** |
| Khác / không rõ | còn lại | 0 | 0 % |

Theo vùng (tỷ lệ ô đo trực tiếp): quanh NB1 35 % (chỉ 23 ô), Cửa Lục 42 % (19 ô), Vân Đồn–Cửa Ông 33 %,
Bái Tử Long 22 %, Hạ Long 20 %, Cát Bà–Lan Hạ 14 %, biển ngoài phía nam 0 %. Phần "đo trực tiếp"
gần như toàn TID 17; ở đây chỉ có 4 ô multibeam (11) và 198 ô ENC (14). Ngay cả ô "trực tiếp" cũng là
dữ liệu thưa (hải đồ/điểm đo), chưa phải khảo sát phủ kín.

## 3. So sánh với ETOPO 2022 (cùng lưới 15″, cùng mặt nạ OSM)

| Chỉ số | Giá trị |
| --- | --- |
| Ô biển OSM: GEBCO / ETOPO | 72 295 / 70 449 (ETOPO coi nhiều lạch hẹp là đất: `coarse` 4 439 so với 2 594) |
| ETOPO − GEBCO trên ô biển chung (70 392 ô) | GEBCO − ETOPO: trung vị 0 m, trung bình −2,2 m, MAE 4,2 m, p90 \|Δ\| 6 m |
| Ô giống nhau (\|Δ\| < 0,5 m) | 24,8 % (ETOPO 2022 dựa trên GEBCO cũ, đã bị tái xử lý) |
| Hệ số tương quan | 0,55 |
| Độ sâu lớn nhất trong mặt nạ nước | GEBCO **55 m**, ETOPO **149 m** |
| Ô > 30 m | GEBCO 21 709, ETOPO 24 421 |
| Ô `suspect` (hố > 30 m không thông ra vịnh) | GEBCO 772, ETOPO 2 968 |

Trung vị theo vùng (m, GEBCO / ETOPO): NB1 5 / 4; Cát Bà–Lan Hạ 12 / 11; Hạ Long 11 / 5; Bái Tử Long 10 / 5;
Cửa Lục 6 / 3; Vân Đồn–Cửa Ông 7 / 3; biển ngoài 31 / 31. GEBCO sâu hơn ETOPO ở các vịnh nông
(Hạ Long, Bái Tử Long), phần lớn do ETOPO kéo giá trị về bờ 0 m mạnh hơn.

Điểm có tên (ô nước gần nhất; GEBCO nội suy song tuyến tính / ETOPO):

| Điểm | Vị trí | GEBCO (m) | TID | ETOPO (m) | ETOPO `suspect` |
| --- | --- | --- | --- | --- | --- |
| NB1 | 107.0426 E, 20.7189 N | 4,9 | 40 (nội suy) | 1,0 | không |
| Lan Hạ | 107.052, 20.760 | 1,0 | 17 (trực tiếp) | 2,0 | không |
| Hạ Long | 107.081, 20.919 | 7,0 | 40 | 3,0 | không |
| Cửa Lục | 107.081, 20.985 | 6,0 | 40 | **45,0** | **có** |
| Bái Tử Long | 107.45, 21.00 | 11,3 | 40 | 5,3 | không |
| Cửa Ông | 107.369, 21.040 | 10,0 | 44 | 3,0 | không |
| Vân Đồn (hố ETOPO) | 107.402, 21.119 | 10,0 | 40 | **72,0** | **có** |

Các "hố" của ETOPO (Cửa Lục 60–92 m, Vân Đồn 90–149 m) **không có trong GEBCO 2024**: trên 2 968 ô
`suspect` của ETOPO, GEBCO có trung vị 7 m, tối đa 35 m, chỉ 3,3 % ô > 30 m. Các ô đó là nội suy
(88 %) hoặc trực tiếp (11 %) — GEBCO 2024 đã sửa lỗi, không phải ô đo trực tiếp ở đúng chỗ hố.
GEBCO vẫn còn 772 ô `suspect` (hố > 30 m không thông), chủ yếu viền bờ; độ sâu tối đa 55 m hợp lý.

## 4. Khuyến nghị

1. **Đổi mặc định sang GEBCO 2024** (cập nhật decisions #19 khi controller cho phép): không còn hố
   giả 60–149 m, vịnh nông không bị kéo về 0 m quá mức, và có TID để nói rõ độ tin cậy.
2. Vẫn ghi rõ trên bản đồ: **97 % ô là nội suy/dự đoán** (TID 40–45), nên chỉ là bức tranh thô; không
   thay được hải đồ hoặc đo sâu tại lồng. Tại NB1 giá trị 4,9 m là nội suy.
3. Giữ ETOPO như nguồn đối chiếu (tuỳ chọn), không xoá.
4. Vẫn cần mốc thật (hải đồ VN, đo hồi âm tại lồng) để hiệu chuẩn; TID không cho biết sai số.

## 5. Cần nối (controller)

- Backend: `app/bathymetry_gebco.py` — `ensure_gebco_artifact(cache_dir, raw_path, water=None)`,
  `load_manifest`, `load_geojson(kind, lod)`, `sample`. Artifact ở `<cache>/bathymetry-gebco/<key>/`,
  thuộc tính `confidence` của isoband ∈ `direct | indirect | unknown | coarse | suspect`.
- Cần thêm: `gebco_bathymetry_path` trong settings (mặc định
  `data/depth/gebco2024-20261023/gebco2024_15s_hp_qn.nc`), gọi build trong worker, và endpoint
  `/api/v1/bathymetry/gebco/manifest|isobands|isobaths|flags`, `sample` có khoá `gebco`.
- Frontend: kiểu `confidence` mới (`direct` đậm, `indirect` nhạt hơn, `suspect`/`coarse` như cũ); chú giải ghi TID.
- Docker: tải dữ liệu trên máy host trước (`python scripts/download_gebco2024_bathymetry.py`, cần rasterio).
