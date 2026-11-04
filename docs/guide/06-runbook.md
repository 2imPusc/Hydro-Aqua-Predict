
## Pilot D? b?o & C?nh b?o ?i?u ki?n nu?i (Station 06M26042804)

### Thu th?p d? li?u li?n t?c (Weather Snapshot Collector)
L?ch ch?y ?? xu?t: **M?i 1 gi?** (00:00, 01:00, 02:00... UTC). Ch?t 1 l?n m?i gi? cho pilot ?? d? ?o coverage.
L?nh:
`ash
powershell.exe -ExecutionPolicy Bypass -File experiments/run_weather_snapshot.ps1 -Station 06M26042804
`
- **Healthcheck**: 
  `ash
  python experiments/weather_snapshot_health.py --station 06M26042804
  `
  Healthcheck s? ??c file jsonl c?, b?o timestamp capture cu?i, ?? tr? v? c?c kho?ng gap. Ng??ng healthy l? tr? kh?ng qu? 2 gi?.

### Shadow Runner (??nh gi? gi? l?p)
Ch?y daemon li?n t?c m?i 60 gi?y.
`ash
python core/shadow_runner.py --station 06M26042804 --interval-seconds 60
`

### Health check thu thập dữ liệu (HAP-HealthCheck — chưa cài)
Lý do: 30/10 tắt máy không sạch → socket cũ trong `%LOCALAPPDATA%\Docker\run`, Docker Desktop không lên,
worker research-map dừng 3 ngày (31/10–03/11) mà không ai biết; coverage snapshot 7 ngày tụt 0.685.

Chạy tay (từ repo root, venv gốc):
```powershell
.venv\Scripts\python scripts\health_check.py --no-notify     # in bảng + ghi 1 dòng JSON vào runtime\logs\health.log
.venv\Scripts\python scripts\health_check.py --no-log --no-notify   # chỉ in
```
Exit 0 ok / 1 warn / 2 fail. Các kiểm tra:

| Check | FAIL | WARN |
| --- | --- | --- |
| `docker` | docker không trả lời (timeout 30 s) hoặc 1 trong `research-map-{api,worker,postgres,frontend}-1` không `Up` | container `unhealthy` |
| `weather_snapshots_task` / `_worker` | bản ghi mới nhất > 2 h hoặc thiếu file | coverage 7 ngày < 0.9 |
| `shadow_runner_log` / `hazard_jobs_log` | dòng mới nhất > 20 min / > 2 h | — |
| `sensor_coverage_yesterday` | — | ngày hôm qua (giờ VN) < 0.9 × 1440 phút; trước 07:00 chỉ ghi `collector_not_due_yet` |
| `scheduled_tasks` | task `HAP-*` thiếu hoặc Disabled | last result ≠ 0 (trừ đang chạy / IgnoreNew 0x800710E0) |

Popup (WScript.Shell, tự đóng sau 30 s) chỉ khi FAIL, hoặc WARN mà lần trước không phải WARN — tuần coverage thấp
không bật popup mỗi giờ. Đọc lịch sử: `Get-Content runtime\logs\health.log -Tail 5`.

Cài (cần chủ dự án duyệt): `powershell -ExecutionPolicy Bypass -File scripts\install_health_check_task.ps1`;
gỡ: thêm `-Remove`.

### Khôi phục Docker Desktop sau khi tắt máy không sạch (stale socket)
Triệu chứng: `docker ps` treo hoặc báo `error during connect`, Docker Desktop đứng ở "starting" / thoát;
health check báo `docker: FAIL docker_not_responding`.
1. Thoát hẳn Docker Desktop (khay hệ thống → Quit; kiểm tra `tasklist /FI "IMAGENAME eq Docker Desktop.exe"` rỗng).
2. **Đổi tên, không xoá**: `Rename-Item "$env:LOCALAPPDATA\Docker\run" "run.stale-$(Get-Date -Format yyyyMMddTHHmmss)"`.
3. Mở lại Docker Desktop, chờ engine chạy, rồi `docker ps` — các container `research-map-*` có `restart` sẽ tự lên;
   nếu không: `docker compose -p research-map up -d` trong `research-map\`.
4. Chạy `scripts\health_check.py --no-notify`; worker bù lại từ giờ UTC kế tiếp (giờ đã mất không lấy lại được).
5. Thư mục `run.stale-*` có thể để lại; chỉ dọn tay khi chắc không cần.

Tự động (mặc định tắt): `health_check.py --fix-docker-stale-sockets` (hoặc cài task với `-FixDockerStaleSockets`)
làm bước 2–3 chỉ khi docker FAIL **và** không có process Docker Desktop; kết quả ghi ở `checks[docker].fix`.
