# Kế hoạch bàn giao: pilot dự báo và cảnh báo điều kiện nuôi tại một trạm

**Người thực hiện:** một agent Gemini Pro 3.5. **Người phản biện:** Codex, sau khi nhận mã nguồn và bộ kết quả. **Ngày lập:** 26/09/2026 (Asia/Ho_Chi_Minh). Chạy mọi lệnh từ root repo `D:\2impusc\DATN-20225064`, trừ khi lệnh ghi rõ thư mục khác.

## 1. Mục tiêu và ranh giới

Pilot tại sensor `06M26042804`, Hải Phòng, loài cá giò. Tạo kết quả nghiên cứu chạy được ngay từ dữ liệu hiện có và một luồng shadow tiếp tục thu thập. Đầu ra gồm: (1) dự báo các chỉ số nước đo trực tiếp, (2) ngữ cảnh mưa/gió/sóng/dòng chảy cho 6–24 giờ, (3) đánh giá điều kiện **vận hành lồng hiện tại**, (4) log đủ để tái dựng dự báo và đánh giá kết quả. Không tuyên bố dự báo tỷ lệ chết, không coi DO suy ra là DO đo, không phát thông báo hoặc điều khiển thiết bị.

`lab-realtime/` là nơi triển khai nghiên cứu. `webapp/` là entrypoint vận hành chính của repo; chỉ lập giao diện/hợp đồng tích hợp, không âm thầm chuyển pilot sang production. Không xóa, ghi đè hoặc làm mất dữ liệu trong `data/`, `map/`, `tieu-chi/`, `model/output/**/*.pkl`, `model/cache/`, `output/`. Các file runtime và research JSONL hiện có cũng phải giữ nguyên; dữ liệu mới chỉ append hoặc ghi vào thư mục output mới. Repo đang có nhiều thay đổi chưa commit: kiểm tra `git status --short`, không reset/clean/checkout/merge đè công việc của người khác.

## 2. Hiện trạng cần đối chiếu trước khi sửa

- `core/greenlab_api.py` chỉ gọi `LastestDataByDevice`; nó **không** cung cấp backfill lịch sử. `core/fetch.py` có đường đọc MongoDB và cache/export. Kiểm tra nguồn nào thực sự còn dữ liệu trước khi viết adapter lịch sử; không giả định API có endpoint phân trang.
- `experiments/forecast_snapshot_store.py` lưu forecast Open-Meteo dạng JSONL. `experiments/forecast_external_context.py` ghép theo thời gian nhưng hiện chưa bắt buộc station/product và chưa có giới hạn tuổi bản tin. `experiments/forecast_sensor_v2.py` có rolling folds, lockbox và B5 external.
- `core/forecast_evaluation.py` có sổ shadow forecast/outcome; `core/shadow_runner.py` từ chối dữ liệu cũ. `core/weather_advisory.py` dùng ngưỡng thử nghiệm; cần sửa cửa sổ theo timestamp, kiểm tra giờ thiếu và trạng thái stale.
- `research-map/` đã có context khí tượng/hải văn và sensor riêng. Tránh tạo nguồn sự thật thứ hai hoặc hiểu lầm ô hiển thị 1 km là độ phân giải mô hình biển 1 km.
- Tại lần kiểm tra 26/09: cache GreenLab local mới nhất 05/09; snapshot thời tiết có 143 lần lấy từ 01/08 đến 25/09, khoảng trống lớn nhất ~833 giờ. Báo cáo coverage cũ dùng telemetry kết thúc 26/07 nên ghi 0 cặp as-issued. **Đây là mốc kiểm tra, không phải trạng thái cố định:** agent phải đo lại và ghi timestamp thực tế của lần chạy.

## 3. Thứ tự triển khai và sản phẩm từng giai đoạn

### P0 — Kiểm kê và lấy bù dữ liệu đến thời điểm chạy

1. Đọc cấu hình nguồn, dữ liệu sensor, cache/export, MongoDB (nếu truy cập được) và weather snapshot ở chế độ read-only. Ghi UTC `run_started_at`, thời gian đầu/cuối, số timestamp duy nhất, đơn vị, tỷ lệ null theo tham số và các khoảng trống >5 phút, >1 giờ, >1 ngày. Tạo báo cáo `source_inventory.json` và `coverage_by_day.csv` trong một run directory mới dưới `artifacts/experiments/weather-risk-pilot/<run_id>/`.
2. Xác định phương án backfill theo thứ tự: MongoDB lịch sử hiện có; GreenLab export đã có; endpoint lịch sử **chỉ khi kiểm chứng được hợp đồng API**. API `latest` chỉ dùng cho dữ liệu mới. Giữ bản gốc bất biến; tạo dataset chuẩn hóa mới có `station_id`, `observed_at_utc`, `received_at_utc` nếu biết, tham số, giá trị, đơn vị gốc, QC, nguồn và ID/hash nguồn. Khử trùng theo `(station_id, observed_at_utc, parameter, source)` mà không che xung đột giá trị; xung đột vào log riêng. Không sửa `greenlab_export.csv` hoặc các cache đang có.
3. Với dự báo thời tiết, thống kê các snapshot thực sự đã thu và giờ thiếu. Nếu thử Open-Meteo Single Runs để dựng lại lịch sử, kiểm tra phạm vi model/run thực tế, ghi `provenance_class=reconstructed_run` và timestamp model run. Giữ riêng `captured_live`, `reconstructed_run`, `pseudo` và `oracle`; chỉ `captured_live` hoặc run lịch sử đã xác minh thời điểm sẵn có được phép vào so sánh as-issued chính. Không dùng API forecast hiện tại để lấp một thời điểm quá khứ.
4. **Gate P0:** báo cáo được số giờ sensor/weather chồng nhau theo ngày và theo chân trời; khoảng không lấy bù được hiển thị rõ. Nếu không có nguồn lịch sử, vẫn hoàn thành báo cáo và tiếp tục với phần nghiên cứu khả thi, không dựng dữ liệu giả.

### P1 — Hợp đồng dữ liệu và phép ghép nhân quả

1. Dùng UTC trong lưu trữ; phân biệt `observed_at`, `received_at`, `issued_at` (lúc hệ thống ra quyết định), `retrieved_at` (lúc nhận bản tin), `provider_run_at` nếu biết, `valid_at` (giờ dự báo có hiệu lực). Thời điểm gửi request không được ghi thành `retrieved_at`; nếu provider không trả thời gian phát hành, lưu `provider_run_at=null`, không suy đoán.
2. Sửa phép ghép weather/marine để bắt buộc đúng station và phiên bản tọa độ; chọn bản tin có `retrieved_at <= issued_at`, `valid_at` tương ứng và tuổi không vượt cấu hình. Với bản tin dự báo theo giờ, định nghĩa rõ giá trị mưa là khoảng giờ nào; không trộn giá trị tức thời và lượng tích lũy. Thiếu giờ/biến bắt buộc trả `partial` hoặc `unavailable`, không điền 0.
3. Tách `data_quality` (`complete`, `partial`, `stale`, `missing`) khỏi `risk_severity` (`NORMAL`, `WATCH`, `WARNING`, `UNAVAILABLE`). Cảnh báo có bằng chứng hợp lệ từ một nhánh không biến mất vì nhánh khác mất kết nối; tuy nhiên không được hiển thị `NORMAL` nếu một nhánh bắt buộc thiếu dữ liệu.
4. **Gate P1:** test cho bản tin đến muộn, trạm khác, đổi vị trí, nhiều provider, thiếu giờ, UTC/local, stale và chạy lại cho cùng kết quả. Không có mẫu nào lấy feature được biết sau `issued_at`.

### P2 — Kết quả có thể chạy ngay: benchmark hồi cứu

1. Đóng băng `run_id`, hash dataset, khoảng train/test, model/policy version và tập mẫu chung cho các so sánh. Dự báo trực tiếp Temperature, pH, NH4, TSS. Dùng persistence làm baseline; so sánh sensor-only, sensor+calendar, sensor+weather lag quá khứ; B5 as-issued chỉ chạy trên phần có forecast hợp lệ. Báo cáo riêng 15/30/60 phút đã có và nghiên cứu mở rộng 1/3/6/12/24 giờ nếu số mẫu/coverage cho phép. Không tự động huấn luyện DO suy ra như ground truth.
2. Dùng rolling-origin, purge phù hợp chân trời lớn nhất và lockbox cuối kỳ; không chọn model/ngưỡng trên lockbox. So sánh từng cặp trên **cùng origin và target**; báo cáo cả độ phủ mẫu bị loại. Với TSS/NH4, phân tầng mưa, gió, giá trị cao, ngày/đêm, gap sensor. Tính MAE, RMSE, bias, p95 absolute error; CI bằng block bootstrap theo ngày/sự kiện nếu đủ block, ghi `insufficient_evidence` nếu không đủ.
3. Tạo `immediate-results.md` nói rõ những gì chứng minh được ngay, những gì mới là tín hiệu hồi cứu và những gì chưa đánh giá được. Mọi pseudo/oracle phải có tiêu đề `diagnostic_only`; không dùng để chọn model vận hành.
4. **Gate P2:** một lệnh chạy lại tạo cùng manifest và metric (cho phép khác đường dẫn/thời gian chạy); không có claim về hiệu quả cảnh báo nếu chưa có nhãn sự kiện độc lập.

### P3 — Shadow risk engine và log đánh giá

1. Giữ dự báo sensor và weather/marine thành hai nhánh. Nhánh nước đưa ra mức rủi ro từ sensor hợp lệ và dự báo đã qua gate; DO/Salinity suy ra chỉ hiển thị `inferred` với trạng thái kiểm định. Nhánh vận hành tóm tắt mưa, gió, sóng/dòng chảy theo cửa sổ 3/6/12/24 giờ đầy đủ. Các ngưỡng hiện tại là `pilot_policy_v1` và phải có file cấu hình phiên bản, đơn vị, nguồn căn cứ; chưa gọi là ngưỡng sinh học đã xác nhận.
2. Tổng hợp hai nhánh thành điều kiện vận hành `NORMAL/WATCH/WARNING/UNAVAILABLE` kèm `drivers`, `evidence_ids`, thời gian tác động dự kiến, trạng thái dữ liệu và khuyến nghị kiểm tra. Giữ điểm rủi ro nước và vật lý riêng để người xem biết nguồn nguy cơ. Không dùng weather advisory để suy luận rằng DO sẽ giảm nếu chưa có mô hình đã được kiểm chứng.
3. Shadow runner ghi quyết định mới chỉ khi sensor còn hạn; nếu weather thiếu, vẫn ghi trạng thái weather `UNAVAILABLE` và lý do. Không phát notification (`notification_sent=false`) và không đổi chính sách alert khẩn cấp hiện có. Cung cấp bảng/CLI đọc kết quả, coverage và outcome; không cần giao diện mới phức tạp.
4. **Gate P3:** replay offline từ log cho ra cùng quyết định; lỗi một provider không làm mất bằng chứng nguồn khác; retry không ghi trùng; không có alert khẩn cấp từ DO suy ra.

### P4 — Thu thập thực tế và quyết định mở rộng

1. Đưa lệnh chạy collector và shadow runner, healthcheck, log lỗi và lịch chạy đề xuất vào runbook. Không tự đăng ký Scheduled Task hoặc thay đổi dịch vụ vận hành nếu chưa được người vận hành yêu cầu. Theo dõi coverage hằng ngày; nếu collector dừng, ghi khoảng trống và khởi động lại từ thời điểm mới, không backdate snapshot.
2. Chuẩn bị mẫu nhập sự kiện thực địa: thời gian bắt đầu/kết thúc, lồng/vị trí, DO đo trực tiếp hoặc mẫu lab nếu có, dấu hiệu cá, mưa/gió tại chỗ, thao tác cho ăn/sục khí/thay nước, người xác nhận và độ chắc chắn nhãn. Không tự tạo ground truth từ ngưỡng dự báo.
3. Sau tối thiểu 8 tuần shadow liên tục, đánh giá event recall, false alerts mỗi lồng-tuần, median lead time, tỷ lệ `UNAVAILABLE`, tỷ lệ cảnh báo được xác nhận/hành động, và sai số theo mùa/sự kiện. Nếu số sự kiện quá ít, báo `insufficient_evidence`; không coi đủ 8 tuần là tự động đạt gate.

## 4. Hợp đồng log và artifact bắt buộc

Tất cả log JSONL append-only, UTF-8, `schema_version`, `record_id` ổn định, `run_id`, `station_id`, UTC ISO-8601, `created_at`, `source_ids` và không chứa credentials. ID dựa trên khóa nghiệp vụ và version; retry là idempotent. Ghi lỗi thành trạng thái có lý do, không bỏ qua im lặng.

| Artifact | Trường tối thiểu ngoài trường chung | Câu hỏi đánh giá |
| --- | --- | --- |
| `ingestion_attempts.jsonl` | source, request window, started/finished, status, count, error code, cursor nếu có | Có lấy đủ dữ liệu đến hôm nay không? |
| `source_inventory.json`, `coverage_by_day.csv`, `gaps.csv` | min/max timestamp, expected/actual count, duplicates, missing, gaps | Phần dữ liệu nào dùng được? |
| `sensor_observations` chuẩn hóa | observed/received, parameter, value, original_unit, QC, source record ID | Giá trị nào đo trực tiếp, khi nào? |
| `external_snapshots.jsonl` | provenance_class, retrieved/provider-run/valid, product, location/version, values/units, payload hash | Bản tin nào thật sự sẵn có lúc dự báo? |
| `forecast_issuances.jsonl` | origin/valid/horizon, target, prediction, baseline, model/features version, input IDs, rejection reason | Dự báo gì và từ bằng chứng nào? |
| `risk_decisions.jsonl` | policy version, water/physical/combined state, data quality, drivers, evidence IDs, notification_sent | Vì sao đưa ra mức rủi ro? |
| `outcomes.jsonl` | forecast/decision ID, actual value/event ID, matched_at, match tolerance, label source/quality | Kết quả thực tế là gì? |
| `evaluation` CSV/JSON/Markdown | n, coverage, metric/CI theo fold/horizon/stratum, exclusions, verdict | Kết quả có vượt baseline và đáng tin không? |

`outcomes` cho sensor dùng quan trắc hợp lệ gần `valid_at` và ghi sai lệch thời gian ghép; outcome sự kiện cần nhãn độc lập. Ghi cả dự báo chưa có outcome (`pending`, `expired_unmatched`) để tránh thiên lệch chỉ chấm mẫu dễ. Trình bày kết quả metric bên cạnh `n`, thời gian dữ liệu, coverage, số sự kiện và tỷ lệ bị chặn.

## 5. Kiểm thử và điều kiện nghiệm thu

- Unit: chuẩn hóa timestamp/đơn vị; window mưa/gió đủ giờ; join đúng station, đúng valid hour, không nhìn tương lai, giới hạn tuổi; xử lý trùng và xung đột; QC/missing/stale; ID ổn định.
- Integration: replay một ngày có đủ nguồn và một ngày thiếu weather; lỗi API, timeout, mất kết nối, restart/retry; forecast đến hạn được ghép outcome đúng tolerance. Dùng fixture nhỏ, không gọi API thật trong unit test.
- Research: cùng tập mẫu cho ablation; train không chứa target tương lai của test; lockbox không tham gia chọn model; pseudo/oracle không lọt vào verdict as-issued; report có dấu `insufficient_evidence` khi coverage/nhãn thấp.
- Safety: test DO suy ra không tạo Emergency; thiếu dữ liệu không thành `NORMAL`; không có notification gửi thật; dữ liệu bảo vệ và log cũ không bị chỉnh/xóa.
- Kết thúc bằng `git diff --check`, pytest các module liên quan, lệnh benchmark với dữ liệu thực có sẵn và tóm tắt test pass/fail. Không sửa test chỉ để làm kết quả xanh.

## 6. Gói bàn giao cho Codex phản biện

Agent nộp: (1) danh sách file sửa và lý do, (2) commit hoặc `git diff` chỉ gồm thay đổi của agent, (3) lệnh chạy chính xác và exit code, (4) đường dẫn run directory với manifest, coverage, metric, log mẫu đã ẩn credentials, (5) bảng “đạt/chưa đạt/chưa đủ dữ liệu” cho từng gate P0–P4, (6) giới hạn dữ liệu và quyết định không đưa vào vận hành. Không báo “hoàn thành cảnh báo” chỉ vì UI hiển thị. Nếu nguồn backfill hoặc API không truy cập được, nộp lỗi cụ thể và hoàn thành các phần độc lập.

Codex sẽ đọc diff và artifact, tái chạy test và một benchmark có thể tái lập, kiểm tra causality/provenance và an toàn dữ liệu, đối chiếu số metric với log gốc, rồi trả verdict từng gate kèm lỗi chặn và việc cần sửa. Đây là đợt kiểm tra **sau khi agent bàn giao**; tài liệu này không khẳng định phần triển khai đã được kiểm tra.
