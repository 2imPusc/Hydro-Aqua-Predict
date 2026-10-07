# Bàn giao Gemini Pro 3.5 — vòng 3: dữ liệu, B5 và thu thập liên tục

**Ngày lập:** 26/09/2026. **Trạm:** `06M26042804`. **Mục tiêu vòng này:** tạo nền dữ liệu đúng, làm đường benchmark thời tiết B5 chạy được và chứng minh collector đang thu bản tin mới. Đây là gói sửa kỹ thuật; chưa hiệu chuẩn ngưỡng nuôi cá, chưa đưa vào `webapp/`, chưa bật thông báo.

## 1. Sự thật đầu vào cần giữ nguyên

- Cache hiện đọc được 80.670 timestamp sensor đến `2026-09-04T23:05:55Z`; file CSV cũ có 15.475 timestamp. Artifact hợp nhất vòng 2 có 96.144 timestamp nhưng `load_sensor_data()` chỉ parse 80.670 do chuỗi thời gian trộn định dạng có/không có phần mili giây.
- Vòng 2 báo một giờ đồng hồ trùng giữa sensor và weather, nhưng sensor cuối lúc `23:05:55Z`, weather capture đầu cùng giờ lúc `23:06:25Z`. **Số cặp nhân quả hợp lệ hiện là 0**, trừ khi tìm được nguồn lịch sử khác.
- B5 hiện chưa chạy: `build_frame()` không có cột `station`, còn `join_as_issued()` mới yêu cầu cột này. Phép ghép cũng chưa kiểm location, chưa loại `pseudo`/`oracle`, và tính tuổi từ `snapshot_issued_at` thay vì `retrieved_at`.
- Script R1 tự đặt `MONGODB_URI=""`, rồi báo MongoDB `unrecoverable` dù không thử. Risk log hiện thiếu input IDs; phần đó **không thuộc gate hoàn thành vòng 3**, chỉ giữ nguyên shadow-only và không tuyên bố replay được.

Không xóa, ghi đè hoặc làm mất dữ liệu trong `data/`, `map/`, `tieu-chi/`, `model/output/**/*.pkl`, `model/cache/`, `output/`. Không sửa hoặc ghi đè artifact vòng 1/vòng 2. Repo có dirty working tree; không `git reset`, `git clean`, checkout hay merge đè. Mọi artifact mới vào `artifacts/experiments/weather-risk-pilot/round3/<run_id>/`. Không ghi credentials hoặc URI có mật khẩu vào log.

## 2. Gói A — chuẩn hóa và kiểm kê sensor

1. Bỏ dòng ép `MONGODB_URI=""`. Kiểm tra MongoDB có cấu hình hay không và truy vấn đọc có timeout hữu hạn. Phân biệt `not_configured`, `timeout`, `auth_error`, `query_empty`, `success`; không gọi `unrecoverable` nếu chưa kiểm chứng. Nếu nguồn không truy cập được, tiếp tục với cache/CSV và ghi rõ giới hạn. Không gọi GreenLab `latest` để lấp lịch sử.
2. Đọc cache và CSV, giữ provenance từng bản ghi. Chuẩn hóa timestamp về UTC với một định dạng duy nhất khi xuất CSV, ví dụ ISO-8601 có `Z` và phần giây cố định. Test nạp lại file xuất bằng **đúng `load_sensor_data()` của benchmark**, yêu cầu số timestamp hợp lệ sau parse bằng số timestamp hợp lệ trước xuất. Không thay `errors='coerce'` chỉ để giấu lỗi; báo riêng các timestamp không parse được.
3. Phân biệt `n_sensor_timestamps`, `n_parameter_rows`, `n_source_records`. Không cộng năm tham số thành năm mẫu độc lập. Kiểm tra duplicate theo `(station, observed_at, parameter)` và near-duplicate do hai nguồn lệch mili giây; **không tự gộp gần nhau** nếu chưa chứng minh chúng cùng lần đo. Ghi số và ví dụ ẩn dữ liệu nhạy cảm; quyết định giữ hay gộp phải có quy tắc và test.
4. Không tự gán NH4 là `µg/L` hoặc một cơ sở hóa học đã xác nhận; giữ `unit_unconfirmed` nếu nguồn không có metadata. Đầu ra bắt buộc: `source_inventory.json` (min/max/count/status từng nguồn), `sensor_parse_audit.json`, `duplicates.csv`, `gaps.csv`, `standardized_sensor_data.csv` và hash đầu vào. Ghi timestamp cuối tới lúc chạy và khoảng chưa thể lấy bù.

**Gate A:** test đọc lại 100% timestamp hợp lệ của output; số lượng và khoảng thời gian được đối chiếu với cache/CSV gốc; trạng thái MongoDB phản ánh một lần kiểm tra thực tế hoặc `not_configured`.

## 3. Gói B — sửa B5 end-to-end và chống rò rỉ thời gian

1. Truyền `station_id` và location ID/version vào frame benchmark trước khi gọi `join_as_issued`; giữ các cột này trong dự báo và manifest. Bắt buộc khớp station **và vị trí có phiên bản**. Nếu snapshot cũ thiếu location version, dùng adapter xác định rõ tọa độ đã lưu và một nhãn `legacy_location`; không âm thầm coi là GPS lồng nuôi. Trả `blocked_reason` khi thiếu định danh hoặc nguồn không khớp.
2. Chỉ nhận `captured_live` và `reconstructed_run` đã xác minh vào B5 chính; cấm `pseudo` và `oracle`. Với `reconstructed_run`, lưu `provider_run_at` và thời điểm bản tin thực sự có thể truy cập. Theo tài liệu [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api), giờ khởi tạo run **không phải** giờ bản tin sẵn có; nếu chưa xác minh availability, chỉ dùng làm phân tích thăm dò.
3. Điều kiện nhân quả: `retrieved_at <= forecast_origin`, `valid_at` đúng biến/giờ đích, tuổi tính từ `retrieved_at`, không quá ngưỡng cấu hình. Không chọn một bản tin khác product/provider bằng thứ tự hàng ngẫu nhiên. Ghi snapshot ID, age, provider/product, location, provenance và lý do loại. Đảm bảo `load_sensor_data()` đọc đúng dữ liệu Gói A.
4. Thêm **integration test** đi từ CSV sensor nhỏ + JSONL snapshot qua CLI hoặc `run_benchmark(..., selected_feature_sets=(B5,))`: ca đủ dữ liệu phải tạo manifest/metric B5; ca khác trạm, khác vị trí, `retrieved_at` sau origin, quá hạn, `pseudo`/`oracle`, thiếu valid hour phải không ghép. Test train/test xác nhận nhãn train kết thúc trước test. Không cần API thật trong test.
5. Chạy coverage trên dữ liệu thực **theo từng origin**; không dùng phép giao cùng giờ làm coverage. Nếu không có cặp nhân quả, xuất `b5_coverage.json` với `eligible_origins=0` và verdict `insufficient_evidence`. Chỉ chạy benchmark thật khi đủ origin và fold theo gate nghiên cứu hiện có. Nếu có run hồi cứu Single Runs, báo riêng `reconstructed_run`; không trộn với captured-live.

**Gate B:** B5 chạy hết luồng trên fixture tích hợp; không rò rỉ trong các ca âm; báo cáo thực nêu đúng số origin ghép được. Không claim cải thiện weather khi chưa có paired comparison trên cùng origin.

## 4. Gói C — collector và healthcheck

1. Giữ snapshot collector append-only. `retrieved_at` phải ghi sau khi nhận response; `provider_run_at=null` nếu API không trả. Lưu station, tọa độ/location version, provider/product, units, hash, `valid_at`, `provenance_class=captured_live`. Mỗi lần capture có capture ID ổn định; số lần thu tính theo capture ID/distinct issue time, không theo số dòng valid hour.
2. Tạo lệnh **read-only** `weather_snapshot_health` để báo: timestamp capture cuối, tuổi, số capture trong 24 giờ/7 ngày, các khoảng gián đoạn >2 giờ, số giờ dự báo thiếu, location hiện tại và status `healthy/stale/missing`. Nếu cấu hình chu kỳ 6 giờ thì ngưỡng healthcheck phải tương ứng; nếu giữ chu kỳ 1 giờ thì không đổi runbook thành 6 giờ. Chốt **mặc định một lần mỗi giờ** cho pilot để dễ đo coverage.
3. Chạy một lần collector khi mạng/API sẵn có, ghi exit code, số dòng mới, capture ID và healthcheck sau chạy. Nếu mạng không cho phép, test bằng response giả và ghi trạng thái `external_api_unavailable`; không tạo snapshot backdate. Không tự đăng ký Scheduled Task hoặc thay đổi service. Cung cấp lệnh cài đặt lịch như bước vận hành tùy chọn, không tự thực hiện.

**Gate C:** một capture thật mới hoặc báo lỗi API cụ thể; healthcheck đọc được kho cũ và phát hiện đúng gap lớn hiện có; retry không nhân đôi bản ghi; runbook khớp đúng lệnh và đường dẫn log thực.

## 5. Kiểm thử và báo cáo bàn giao

Chạy và ghi **exit code thật**:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_forecast_sensor_v2.py tests/test_forecast_snapshot_store.py tests/test_weather_advisory.py tests/test_shadow_runner.py -q
.venv\Scripts\python.exe -m pytest tests/test_pilot_p0_inventory.py tests/test_weather_snapshot_health.py -q
git diff --check
```

Nếu tạo test khác tên, dùng tên thực và ghi lệnh tương ứng. Sửa trailing whitespace trong **file agent đã sửa**, không quy lỗi đó cho LF/CRLF. Test cũ phải tiếp tục pass. Không sửa test chỉ để hợp thức hóa hành vi sai.

Nộp `round3-handoff.md` với ba gate A/B/C (`passed`, `partial`, `insufficient_evidence`, `blocked`), link mã/test/artifact, số timestamp sensor hợp lệ trước/sau xuất, trạng thái MongoDB, số capture weather distinct và thời điểm cuối, số cặp B5 nhân quả, run ID và input hashes. Liệt kê file agent sở hữu, gồm file untracked; không dùng `git diff` toàn repo làm diff riêng. Chỉ đánh dấu một gate `passed` khi test và artifact đúng tiêu chí. Không đánh dấu hệ thống cảnh báo nuôi trồng là hoàn thành trong vòng này.

**Codex sẽ nghiệm thu lại:** kiểm đếm timestamp bằng parser benchmark, chạy fixture B5 end-to-end, đối chiếu causality theo từng origin, kiểm healthcheck và một lần capture, kiểm test/diff và xem log có đủ provenance. Nếu B5 không có dữ liệu thực, vẫn có thể nghiệm thu kỹ thuật B5 trên fixture; hiệu quả mô hình vẫn là `insufficient_evidence`.
