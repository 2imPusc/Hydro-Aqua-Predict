# Bàn giao vòng 2 cho Gemini Pro 3.5: sửa pilot thời tiết và rủi ro nuôi

**Ngày đối chiếu:** 26/09/2026. **Trạm pilot:** `06M26042804`. **Người kiểm tra sau bàn giao:** Codex. Thực hiện từ repo root. Đây là vòng sửa các lỗi đã xác minh, không phải yêu cầu viết lại toàn bộ `lab-realtime`.

## 1. Kết quả kiểm tra vòng 1 phải được xử lý

1. P0 báo 15.475 mẫu đến 19/06 vì `pilot_p0_inventory.py` chỉ đọc MongoDB/CSV. `core.greenlab_api.load_cached_history('06M26042804')` hiện đọc được **80.670 mẫu đến 04/09/2026 23:05:55 UTC**. Việc lấy bù đến ngày chạy chưa được chứng minh.
2. P1 chưa được sửa: `forecast_external_context.join_as_issued` chưa bắt buộc station/location và chưa giới hạn tuổi bản tin. `weather_advisory` vẫn dùng `rows[:hours]`, nên giờ bị khuyết có thể kéo dài cửa sổ; trạng thái stale vẫn có thể thành `ready`.
3. P2 manifest chỉ có B0–B4; B5 weather **không chạy** dù có đường dẫn snapshot. `HORIZONS` bị đổi toàn cục thành 15–1440 phút, `LOCKBOX_DAYS=4`, `FOLD_DAYS=3`, `N_FOLDS=2`, `PURGE=60 phút`; artifact thực tế chỉ có **một** rolling fold. Test hiện có thất bại: `test_rolling_folds_respect_purge_and_lockbox` (mong 5 fold, nhận 2).
4. P3 chưa có risk engine hai nhánh, quyết định tổng hợp hoặc `risk_decisions.jsonl`. P4 mới có mẫu nhập liệu, chưa có sự kiện thực địa.
5. `agent_changes.diff` của vòng 1 lấy cả dirty working tree và bỏ sót file untracked. Không dùng file đó làm bằng chứng phần việc của agent.

**Nguyên tắc sửa:** chỉ báo gate `đạt` khi có mã, test và artifact chứng minh. Đánh dấu `chưa đủ dữ liệu` khi không thể đánh giá; không giảm số fold hoặc thu hẹp lockbox chỉ để tạo verdict. Không sửa/xóa/ghi đè dữ liệu trong `data/`, `map/`, `tieu-chi/`, `model/output/**/*.pkl`, `model/cache/`, `output/`. Không sửa log và artifact cũ. Repo có nhiều thay đổi chưa commit: tuyệt đối không `git reset`, `git clean`, merge hoặc checkout đè. Chỉ tạo artifact mới dưới `artifacts/experiments/weather-risk-pilot/round2/<run_id>/`.

## 2. Các gói việc theo thứ tự bắt buộc

### R0 — Khôi phục benchmark gốc và tạo baseline kiểm tra

- Khôi phục mặc định của `forecast_sensor_v2.py`: `HORIZONS=(15,30,60)`, lockbox 14 ngày, năm fold 7 ngày. Nếu cần nghiên cứu 1–24 giờ, tạo preset/CLI riêng và manifest ghi rõ từng tham số; không thay mặc định của bài benchmark cũ.
- Với mọi chân trời, train chỉ chứa mẫu có **`valid_at < test_start`**; áp dụng purge ít nhất bằng chân trời, cộng tolerance nếu cần. Thêm test có dữ liệu nhỏ chứng minh nhãn train không chạm kỳ test, cả ở rolling fold và lockbox.
- Chạy test mục tiêu trước khi tiếp tục. **Gate R0:** test `test_forecast_sensor_v2.py` pass; cấu hình gốc không đổi; artifact vòng 1 vẫn nguyên vẹn.

### R1 — Kiểm kê đúng nguồn và lấy bù có kiểm toán

- Sửa `pilot_p0_inventory.py` để đọc toàn bộ nguồn đã có: `load_cached_history`, CSV fallback và MongoDB nếu truy cập được. Không gọi API `latest` để giả làm backfill. Chỉ thêm adapter API lịch sử nếu đã kiểm tra được endpoint/hợp đồng từ tài liệu hoặc phản hồi thực; ghi rõ nguồn và phạm vi. Tách dữ liệu nguồn ra, không drop duplicate theo timestamp trước khi kiểm tra xung đột từng tham số.
- Dữ liệu chuẩn hóa cần `station_id`, `observed_at_utc`, `parameter`, `value`, `original_unit` nếu biết, `source`, `source_record_id`; `received_at_utc` để null nếu nguồn không có. Quy tắc hợp nhất phải tái lập được: ưu tiên bản ghi có QC hợp lệ và provenance rõ; nếu hai nguồn bất đồng, ghi vào `conflicts.csv`, không âm thầm chọn theo thứ tự sort. Không tự khẳng định đơn vị NH4 đã xác nhận.
- Tạo `source_inventory.json` cho **từng nguồn**, `coverage_by_day.csv` theo sensor và số lần thu forecast riêng, `gaps.csv` với start/end/duration, `overlap_by_hour.csv` giữa sensor và weather. Forecast snapshot có nhiều dòng valid hour cho mỗi lần capture: đếm **distinct `issued_at`** khi báo số lần thu, không dùng số dòng JSONL. Thêm `run_started_at`, thời gian cuối dữ liệu mỗi nguồn, số bản ghi, số trùng/xung đột và nguyên nhân nguồn không truy cập được.
- Chạy đối chiếu trực tiếp với `load_cached_history` và ghi số trước/sau hợp nhất. **Gate R1:** báo cáo không còn kết luận chỉ có 21 ngày khi cache dài hơn; khoảng từ dữ liệu cuối đến ngày chạy có trạng thái `recovered` hoặc `unrecoverable` theo từng nguồn. Nếu không có quyền truy cập nguồn mới, hoàn thành kiểm kê local và nêu rõ giới hạn.

### R2 — Sửa hợp đồng forecast thời tiết và phép ghép

- Trong snapshot collector, `retrieved_at` là thời điểm **sau khi nhận thành công** response; `issued_at` là thời điểm hệ thống lưu/công bố bản ghi; `provider_run_at` chỉ ghi nếu provider trả và đã parse được, còn lại null. Lưu `station_id`, location ID/version, provider, product, units, raw payload hash, `valid_at` và `provenance_class` (`captured_live`, `reconstructed_run`, `pseudo`, `oracle`). Không đổi tên/ý nghĩa trường cũ mà không có adapter đọc tương thích.
- Phép ghép chỉ nhận snapshot đúng station/location, `retrieved_at <= forecast_origin`, valid hour tương ứng, đủ feature và không quá tuổi cấu hình; trả metadata chọn snapshot ID, age, reason khi bị chặn. Nếu frame không có station hoặc snapshot thiếu định danh, phải từ chối hoặc nhận station rõ qua tham số, không tự ghép mọi trạm. Một provider/product không được lẫn vào provider/product khác mà không có lựa chọn explicit.
- Tính weather advisory theo khoảng thời gian thực, đủ 3/6/12/24 giờ liên tiếp cho mỗi cửa sổ. Thiếu giờ hay giá trị bắt buộc => window `partial`/`unavailable`, không cộng thiếu thành 0 và không hiển thị `NORMAL` như dữ liệu đầy đủ. Weather `stale` phải giữ trạng thái stale, không xuất `ready`.
- **Gate R2:** test các ca trạm khác, tọa độ khác, bản tin đến sau origin, quá hạn, thiếu giờ, nhiều product, đổi múi giờ, `valid_at` sát ranh giới giờ. Không có feature nào đến từ thông tin chưa sẵn có tại origin.

### R3 — Chạy benchmark có thể kết luận đúng mức

- Tạo một run sensor-only với nguồn R1 và một run B5 **chỉ khi có overlap hợp lệ**. CLI phải chọn `--feature-set B5_external_as_issued` rõ ràng; manifest phải ghi feature set thực chạy, số cặp train/test sau lọc, source hash và phân bố snapshot age. So sánh B5 với baseline B4/sensor-only trên **cùng `issued_at`, `valid_at`, target và fold**; không so MAE của hai tập mẫu khác nhau.
- Nếu số fold/coverage không đạt gate định trước, vẫn có thể xuất metric chẩn đoán nhưng verdict bắt buộc là `insufficient_evidence`; không gọi tác động thời tiết là đã được xác nhận. Giữ `pseudo` và `oracle` ngoài B5 chính. Báo MAE, RMSE, bias, p95, số mẫu, tỷ lệ loại, theo mưa/không mưa, giá trị cao, ngày/đêm và gap nếu đủ mẫu. CI theo block ngày/sự kiện; ghi số block, không báo CI khi không đủ block.
- Viết `immediate-results.md` mới từ metric/manifest thực tế bằng đường dẫn đúng; không ghi claim về B5 nếu B5 chưa được chạy. **Gate R3:** có phép đối chiếu paired hoặc verdict `insufficient_evidence` có lý do định lượng; tái chạy với cùng input tạo cùng metric.

### R4 — Shadow risk engine và log quyết định

- Tạo `risk_decisions.jsonl` append-only cho trạm pilot. Mỗi bản ghi có `schema_version`, `decision_id`, `station_id`, `issued_at`, `valid_window`, sensor/weather snapshot IDs, model/policy versions, `data_quality`, `water_risk`, `physical_risk`, `combined_severity`, drivers, block reasons, `notification_sent=false`. Không log credentials. Retry phải idempotent.
- Nhánh nước chỉ dùng sensor trực tiếp hợp lệ và dự báo đã được chọn qua gate; DO/Salinity suy ra gắn `inferred` và không tạo Emergency. Nhánh vật lý tính mưa/gió/sóng/dòng chảy từ dữ liệu có sẵn; thiếu marine thì chỉ đánh giá phần có đủ bằng chứng, nêu rõ `partial`, không suy ra sóng/dòng chảy bằng 0. Policy ngưỡng được version hóa, giữ nhãn `pilot_unvalidated` và không khẳng định mức phù hợp sinh học đã được hiệu chuẩn.
- `NORMAL` chỉ khi mọi nguồn **bắt buộc** cho kết luận đó đủ và còn hạn. Nếu một nhánh có WARNING hợp lệ, nguồn khác mất kết nối không xóa WARNING; giữ `data_quality=partial` và bằng chứng. Chạy shadow không gửi thông báo thật, không tự đăng ký Scheduled Task, không sửa chính sách alert khẩn cấp hiện hành.
- **Gate R4:** replay từ input IDs cho cùng quyết định; test duplicate/restart, stale, missing marine/weather, WARNING kèm nguồn khác mất, inferred DO, no notification. Có lệnh read-only in số quyết định, trạng thái, tuổi dữ liệu và outcome đang chờ.

### R5 — Hồ sơ nghiên cứu thực địa

- Giữ mẫu sự kiện nhưng chuyển thành CSV/JSON schema có trường thời gian bắt đầu/kết thúc UTC, station/lồng, loại sự kiện, DO đo hoặc mẫu lab nếu có, dấu hiệu cá, hành động, người xác nhận, `label_quality`, nguồn bằng chứng. Không tự sinh nhãn từ policy dự báo.
- Runbook ghi rõ collector bao lâu chạy, healthcheck kiểm tra **timestamp bản tin cuối**, không chỉ kích thước file; nơi ghi log thực tế phải khớp mã. Runner sensor 60 giây và weather collector theo chu kỳ riêng; nếu chọn chu kỳ khác, giải thích ảnh hưởng đến coverage và freshness. P4 ở vòng này chỉ được ghi `prepared_for_collection`, chưa `passed` trước khi có sự kiện thực địa và đủ thời gian shadow.

## 3. Kiểm tra bắt buộc trước bàn giao

Chạy từ root, ghi nguyên lệnh, exit code và bản tóm tắt output:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_forecast_sensor_v2.py tests/test_forecast_snapshot_store.py tests/test_weather_advisory.py tests/test_shadow_runner.py -q
git diff --check
```

Thêm test mới cho R0–R4; chạy chúng cùng lệnh trên. Chạy P0/R1 trên nguồn local thực và xuất run directory mới. Chỉ chạy B5 khi coverage script báo có cặp hợp lệ; nếu không, xuất báo cáo coverage và verdict `insufficient_evidence`. Không cần gọi API thật trong unit test. Không thay đổi test cũ để che lỗi.

## 4. Gói bàn giao để Codex kiểm tra lại

Nộp **một** `round2-handoff.md` có:

1. Bảng R0–R5: `passed`, `partial`, `insufficient_evidence`, hoặc `blocked`, mỗi dòng kèm link mã, test và artifact. P4 phải là `prepared_for_collection` nếu chưa có quan trắc thực địa.
2. Phạm vi dữ liệu từng nguồn và cuối dữ liệu theo UTC; số lần capture weather distinct; overlap sensor-weather; số origin B5 được ghép; số event ground truth. Phân biệt kết quả hồi cứu, as-issued thực, và shadow live.
3. Đường dẫn manifest, metric, coverage, log mẫu, source hashes; giải thích mọi thay đổi benchmark preset và gate. Nếu không tạo được kết quả B5, nêu đúng nguyên nhân thay vì suy diễn hiệu quả weather.
4. Danh sách chính xác file agent đã sửa/tạo. Không dùng `git diff` toàn repo làm diff riêng khi working tree đã dirty; đối chiếu từng path agent sở hữu, liệt kê cả file untracked, hoặc tạo commit riêng chỉ gồm file agent được phép sửa nếu an toàn.
5. Danh sách giới hạn còn lại và quyết định có/không được đưa vào vận hành. Không tuyên bố production-ready khi chưa có nhãn sự kiện và hiệu chuẩn ngưỡng.

Codex sẽ kiểm tra lại dữ liệu nguồn, phép ghép nhân quả, test, manifest/metric và log quyết định. Kết quả vòng 2 được chấp nhận theo từng gate, không theo việc script chạy exit code 0.
