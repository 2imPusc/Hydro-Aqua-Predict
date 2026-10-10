# Lộ trình phát triển Hydro-Aqua-Predict

**Cập nhật:** 2026-10-10. **Nguồn:** slide seminar 10/2026 (slide 17/20 "Bốn hướng phát triển"), quyết định thứ tự của chủ dự án.

**Thứ tự ưu tiên đã chốt: 1 → 2 → 4 → 3.**
Trên slide đề xuất làm 3 song song và 4 sau 3. Chủ dự án chọn làm 4 trước 3; các điểm phụ thuộc phát sinh từ lựa chọn này ghi ở mục Hướng 4.

| # | Hướng | Mức sẵn sàng (slide) | Ưu tiên |
| --- | --- | --- | --- |
| 1 | Dự báo sâu hơn các chỉ số tương lai | Cao | **1** |
| 2 | Cảnh báo kết hợp thời tiết tại điểm nuôi | Trung bình | **2** |
| 4 | Bản đồ tin cậy nuôi trồng có yếu tố thời tiết | Thấp | **3** |
| 3 | Bản đồ phân vùng tiềm năng nuôi trồng | Trung bình | **4** |

## Nguyên tắc chung (áp dụng cho mọi hướng)

1. **Shadow trước, phát hành sau.** Mọi kết quả mới ghi sổ và chấm điểm. Chỉ chuyển sang hiển thị cho người nuôi khi đã qua gate có số liệu.
2. **Phải thắng baseline mới được dùng.** Dự báo phải thắng persistence (giữ giá trị gần nhất) trên cùng origin, đánh giá theo đúng trình tự thời gian (rolling-origin, có purge). Cảnh báo phải có tỷ lệ bỏ sót và báo nhầm đo trên sự kiện thật.
3. **Không dùng thông tin tương lai.** Bản tin thời tiết chỉ được ghép khi `retrieved_at` ≤ origin. Bản tin `pseudo`/`oracle` chỉ dùng cho phân tích thăm dò.
4. **Ghi rõ nguồn của từng giá trị:** đo được, suy luận, hay dự báo. Cũng ghi rõ dữ liệu là live, cache cũ hay mock.
5. **Kết quả chỉ được tính khi có thể tái tạo.** Mỗi lần chạy nằm trong `artifacts/experiments/<run>/` kèm manifest (input hash, tham số), và có một dòng trong `experiments/RESULTS.md`.
6. **Dùng AI để viết pipeline, nhưng luôn kèm test đầu-cuối và test chống rò rỉ thời gian** (theo bài Martina và cs. 2026, slide 20). Ghi lại số lần phải sửa lỗi cho từng tác vụ, để biết công cụ nào đáng tin.

---

## Giai đoạn 0 — Dữ liệu đúng và đủ (chặn mọi hướng, làm ngay)

Hiện trạng ngày 2026-10-10:

- **Lịch sử sensor bị đứt đoạn.** `data/greenlab/exports/all_data` chỉ tới 2026-07-04; `intervals/` tới 2026-07-26. Postgres của research-map chỉ có khoảng 1.500 mốc trong 4 ngày (những lúc worker chạy).
- Vì thế B5 (benchmark thời tiết) đang có **0 origin đủ điều kiện**: snapshot thời tiết dày lên từ giữa tháng 9, nhưng không có dữ liệu sensor cùng thời gian.
- **API GreenLab `by-date` lấy lại được lịch sử** (đã thử 2026-09-20 → 21: 28.690 dòng).
- Snapshot thời tiết đang được thu mỗi giờ bằng task `HAP-WeatherSnapshot-06M26042804`, kể cả khi máy chạy pin. Trước đây task bị treo khi máy dùng pin, gây ra các khoảng trống.

| ID | Việc | Kết quả mong đợi | Gate |
| --- | --- | --- | --- |
| D0.1 | Backfill sensor 2026-07-26 → nay bằng `node ingest/fetch_api.js by-date -s 06M26042804 --start … --end … --csv` theo từng đoạn ≤ 7 ngày | File mới trong `data/greenlab/exports/intervals/`; không ghi đè file cũ | Số mốc/ngày ≥ 90% của 1.440; liệt kê các khoảng trống |
| D0.2 | Kiểm tra loader `core/fetch.py`/`core/forecast_train.py` đọc được định dạng dài (`Date,DeviceSerialNumber,SensorType,Value`) của `by-date` | Lịch sử liền mạch từ 2026-05-29 tới nay | Test tích hợp với fixture nhỏ |
| D0.3 | Thu sensor liên tục: task `HAP-SensorCollector` (hằng ngày chạy `by-date` cho ngày hôm trước), hoặc worker research-map ghi ra file | Không còn phụ thuộc vào việc worker có đang chạy | Healthcheck tương tự `weather_snapshot_health.py` |
| D0.4 | Hợp nhất nguồn: chọn **một** kho lịch sử chuẩn (file append-only trong `data/greenlab/`); Postgres chỉ để phục vụ bản đồ | Một hàm `load_sensor_history()` dùng chung | Ghi quyết định vào `docs/decisions.md` |
| D0.5 | Kiểm tra lại COD: ngày 2026-09-20 COD = 189.8 chứ không kẹt ở 558.8 | Xác định sensor COD đã hoạt động lại hay chưa; cập nhật `core/quality.py` và AGENTS.md | Thống kê flatline/rail theo từng ngày |
| D0.6 | Hồ sơ ngoài phần mềm: xác nhận đơn vị NH4 với nhà cung cấp, GPS lồng nuôi, DO đo tay, nhật ký sự kiện ≥ 10 sự kiện (`docs/guide/09-ground-truth-protocol.md`) | Ground truth cho hướng 2 và 4 | Không có thì gate của hướng 2 chỉ được ghi `insufficient_evidence` |

---

## Hướng 1 — Dự báo sâu hơn (ưu tiên 1)

**Đã có:** dự báo cảm biến 15/30/60 phút (`core/sensor_future.py`, `core/models/sensor_future/`); bộ thí nghiệm B0–B5 (`experiments/forecast_sensor_v2.py`); sổ ghi dự báo và chấm điểm (`core/forecast_evaluation.py`, `core/shadow_runner.py`); dự báo XGBoost kiểu cũ theo minute/hour/day (`core/forecast_train.py`).

**Hạn chế hiện tại:** mới có khoảng 3 tháng dữ liệu của 1 trạm, còn nhiều khoảng trống; pH và NH4 chưa thắng persistence; DO không đo được; dự báo chưa có khoảng tin cậy.

| Mốc | Việc | Gate để xem là xong |
| --- | --- | --- |
| H1.1 | Chạy lại benchmark B0–B4 trên lịch sử sau backfill (sau D0.1–D0.2). Rolling-origin có purge, giữ lockbox | Bảng MASE theo biến × chân trời; ghi vào `RESULTS.md` |
| H1.2 | Mở rộng chân trời lên 3/6/12 giờ cho Temperature, TSS, NH4, pH | Ở từng chân trời, mô hình phải thắng persistence (MASE < 1, kiểm định Diebold–Mariano p < 0.05). Biến nào không thắng thì giữ persistence |
| H1.3 | Khoảng tin cậy: conformal split theo thời gian (đã làm được với ARWS ở DATN) | Độ phủ thực tế của PI 80% nằm trong [0.75, 0.85] trên lockbox |
| H1.4 | So sánh với mô hình nền zero-shot (Chronos-Bolt / TimesFM / Moirai) | Chỉ đưa vào nếu thắng XGBoost trên cùng origin; nếu thua vẫn ghi lại kết quả |
| H1.5 | Đưa vào shadow runner: chân trời và PI mới được ghi sổ và chấm điểm tự động | Có ≥ 4 tuần sổ ghi, metric ổn định |

**Thành phần chính:** `core/sensor_future.py`, `core/forecast_evaluation.py`, `experiments/sensor_forecast_model_benchmark.py`, `experiments/forecast_sensor_v2.py`.

---

## Hướng 2 — Cảnh báo kết hợp thời tiết tại điểm nuôi (ưu tiên 2)

**Đã có:** luật mưa/gió (`core/weather_advisory.py`); thu bản tin thời tiết mỗi giờ; tổng hợp mức rủi ro (`core/forecast_advisory.py`, `core/alerts.py`); đường B5 đã sửa và nghiệm thu vòng 3 trên fixture (gate A/B/C passed), nhưng **0 origin thật**.

**Hạn chế hiện tại:** chưa có cặp dữ liệu sensor–bản tin để kiểm chứng (cần khoảng 63 ngày bản tin liên tục trùng với sensor); ngưỡng đặt thủ công; chưa có sự kiện thực địa; bản tin lấy tại cảng NB1 chứ không phải GPS lồng.

Hướng 1 và 2 dùng chung dữ liệu sensor và bản tin, nên làm nối tiếp nhau.

| Mốc | Việc | Gate để xem là xong |
| --- | --- | --- |
| H2.1 | Theo dõi độ phủ B5 hằng tuần: `experiments/forecast_snapshot_coverage.py` | Tăng đều; báo cáo số origin nhân quả |
| H2.2 | Khi đủ origin: chạy `B5_external_as_issued` (sensor + bản tin) so với `B4_quality` (chỉ sensor) **trên cùng origin** | Chỉ được claim thời tiết có ích nếu B5 thắng B4 có ý nghĩa thống kê. Nếu không đủ thì giữ verdict `insufficient_evidence` |
| H2.3 | Lượng hóa độ trễ mưa → NH4/TSS (`experiments/weather_lag_sensor_ablation.py`) | Biết độ trễ và hướng tác động, có khoảng tin cậy |
| H2.4 | Hiệu chỉnh ngưỡng cảnh báo bằng sự kiện thực (sau D0.6) | Tỷ lệ bỏ sót và báo nhầm trên ≥ 10 sự kiện; ngưỡng có giải thích |
| H2.5 | Phát hiện sự kiện: xác suất DO thấp hoặc TSS tăng vọt trong N giờ | Brier score tốt hơn tần suất nền |
| H2.6 | Shadow pilot 4–8 tuần, xem lại cùng người nuôi | Biên bản review; quyết định có đưa vào webapp hay không |

**Thành phần chính:** `core/weather.py`, `core/weather_advisory.py`, `core/forecast_advisory.py`, `experiments/forecast_snapshot_store.py`, `docs/guide/22-weather-as-issued-operations.md`, `docs/guide/26-weather-risk-pilot-round3-handoff.md`.

---

## Hướng 4 — Bản đồ tin cậy có yếu tố thời tiết (ưu tiên 3)

**Đã có:** bán kính theo chênh lệch HSI; phân vùng tin cậy theo sai số (P1, `experiments/spatial_applicability.py`, `core/spatial_overlay.py`); lưới thời tiết khoảng 1 km và stack research-map (FastAPI + worker + React).

**Hạn chế hiện tại:**
- Cách tính HSI cũ đọc nhầm dữ liệu của chính trạm cần đoán (lỗi rò rỉ, được đánh dấu `diagnostic_only_observed_hsi_leakage`).
- Gate P1 mới đạt 1/36 trường hợp.
- Chỉ có 1 trạm sensor.
- Dòng chảy Open-Meteo có độ phân giải khoảng 8 km.

**Phụ thuộc do làm 4 trước 3:** bản đồ tin cậy cần một điểm phù hợp cho từng ô. Khi chưa làm hướng 3, dùng tạm **điểm chấm theo luật hiện có** (`hap_shared/classification._classify_by_scoring`, ngưỡng cá giò), nhưng thiết kế điểm phù hợp như một **interface có thể thay thế** (`SuitabilityScorer`). Nhờ vậy hướng 3 (logic mờ) chỉ cần lắp vào, không phải làm lại bản đồ.

| Mốc | Việc | Gate để xem là xong |
| --- | --- | --- |
| H4.1 | Thay HSI bị rò rỉ bằng HSI dự báo từ trạm neo (không đọc dữ liệu trạm đích); chạy lại P0/P1 cho HP và QN | Gate 80/90/95 theo biến × khoảng cách; số trường hợp đạt được báo cáo trung thực |
| H4.2 | Tách `SuitabilityScorer` (rule hiện có) và `ReliabilityModel` (sai số theo khoảng cách/vùng) | Có unit test; research-map gọi qua interface |
| H4.3 | Ghép rủi ro thời tiết (từ hướng 2) với độ tin cậy không gian trên cùng một lớp bản đồ | Mỗi ô có `estimate`, `reliability`, `weather_risk`, `data_age`; ô không qua gate thì không hiển thị giá trị |
| H4.4 | Thêm điểm đo đối chứng (đo tay hoặc sensor thứ 2) để kiểm chứng ngoài mẫu | ≥ 1 điểm độc lập; sai số nằm trong error bound đã hứa |
| H4.5 | Dòng chảy độ phân giải cao hơn (Copernicus), có điều kiện: cần credentials | Lớp `current` có nguồn và độ phân giải rõ ràng |

**Thành phần chính:** `core/spatial_overlay.py`, `experiments/spatial_applicability.py`, `research-map/backend-fastapi/app/{aquaculture_artifacts,domain,flow_artifacts}.py`, `docs/guide/19-spatial-applicability-plan.md`, `20-…-run-log.md`, `23-research-map-implementation-roadmap.md`.

---

## Hướng 3 — Bản đồ phân vùng tiềm năng (ưu tiên 4)

**Đã có:** tiêu chí cho cá giò (`hap_shared/thresholds/cobia_thresholds.json`); dữ liệu quan trắc lịch sử HP/QN/HY (`data/*/clean_data.csv`); dòng chảy và sóng (Copernicus); độ sâu (GEBCO, Copernicus bathymetry).

**Tham khảo:** Ghaderi (2026), *Regional Studies in Marine Science* 101:105287, doi:10.1016/j.rsma.2026.105287 — logic mờ kết hợp đánh giá đa tiêu chí cho lồng nuôi xa bờ.

**Lưu ý về độc lập dữ liệu:** slide nhắc tới khoảng 200 trạm giai đoạn 2020–2024 ở DATN. Repo này hiện mới chép `clean_data` của 3 vùng. Nếu cần thêm dữ liệu, **chép vào `data/`** và cập nhật `docs/data-manifest.md`; không đọc trực tiếp từ DATN.

| Mốc | Việc | Gate để xem là xong |
| --- | --- | --- |
| H3.1 | Thay ngưỡng cứng bằng hàm thuộc mờ cho bộ tiêu chí cá giò | Giá trị sát ngưỡng không làm nhãn đổi đột ngột; có test tính đơn điệu |
| H3.2 | Phân tích độ nhạy trọng số: trọng số đều so với trọng số chuyên gia | Bảng mức độ ổn định của xếp hạng vùng |
| H3.3 | Thêm tiêu chí dòng chảy, sóng, độ sâu | Từng tiêu chí ghi rõ nguồn và độ phân giải |
| H3.4 | Lắp vào `SuitabilityScorer` (H4.2) để tạo bản đồ quy hoạch có kèm độ tin cậy | So khớp với vùng nuôi hiện hữu (nếu có số liệu vụ nuôi) |

---

## Đưa lên webapp (sau cùng, theo gate)

Chỉ đưa một chức năng sang `webapp/` (DATN) hoặc API công khai khi:
1. Chức năng đó đã qua gate của mốc tương ứng.
2. Shadow pilot đã chạy ≥ 4 tuần.
3. Đã review cùng người nuôi.
4. Thông báo bật theo gate, không bật toàn bộ.

## Ánh xạ sang lộ trình 5 giai đoạn trên slide

| Giai đoạn (slide) | Ở tài liệu này |
| --- | --- |
| 1. Dữ liệu đúng và đủ | Giai đoạn 0 (D0.1–D0.6) |
| 2. Ground truth | D0.6, H2.4 |
| 3. B5 + khoảng tin cậy | H1.3, H2.2 |
| 4. Shadow pilot | H1.5, H2.6 |
| 5. Tích hợp webapp | mục "Đưa lên webapp" |
