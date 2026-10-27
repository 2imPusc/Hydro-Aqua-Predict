# Bàn giao phiên mới — Bài báo 1: Chronos-2 + bản tin thời tiết cho nhiệt độ nước lồng nuôi

Ngày: 28/10/2026. Phiên điều phối (vận hành hệ thống) vẫn chạy song song; phiên này chỉ làm **thử nghiệm**
cho bài báo. Phần viết bài làm sau, khi đã có kết quả.

## Môi trường (đã tạo sẵn 28/10)

- Thư mục làm việc riêng (git worktree): `D:/2impusc/HAP-paper1`, nhánh `paper/chronos2-weather`. **Không** đổi nhánh trong
  `D:/2impusc/Hydro-Aqua-Predict` — shadow runner và Docker chạy code từ thư mục đó.
- `data/`, `artifacts/`, `runtime/` và venv không nằm trong worktree; dùng chung từ thư mục chính:
  ```powershell
  $env:HAP_DATA_DIR='D:/2impusc/Hydro-Aqua-Predict/data'
  $env:HAP_ARTIFACTS_DIR='D:/2impusc/Hydro-Aqua-Predict/artifacts'
  $env:HAP_RUNTIME_DIR='D:/2impusc/Hydro-Aqua-Predict/runtime'
  D:/2impusc/Hydro-Aqua-Predict/.venv/Scripts/python ...      # core / experiments
  D:/2impusc/Hydro-Aqua-Predict/.venv-fm/Scripts/python ...   # torch / Chronos
  ```
- Kết quả ghi vào thư mục chạy MỚI trong artifacts chung (ghi một lần). Không ghi gì vào `runtime/`.

## Đọc trước (theo thứ tự)

1. `AGENTS.md` — quy tắc cứng (ghi một lần, đường dẫn qua `core/paths.py`, shadow, không push khi chưa được phép).
2. `docs/paper/2026-10-27-sota-and-plan.md` — khảo sát SOTA, đề tài 1 (mục khuyến nghị), tạp chí, lộ trình.
3. `docs/research-log.md`: RL-08, RL-18, RL-19 (conformal theo biên độ), RL-54 (H1 chạy lại), RL-57 (biên độ
   ngày–đêm ×5 từ giữa T8, nghi đầu dò), RL-59 (thu bản tin thật), RL-62 (Chronos / TimesFM zero-shot),
   RL-66 (ridge B4D / B5D), RL-68 (học trước NERRS), RL-72 (bước nhảy thiết bị 31/07, 12/08, 16/09).
4. `docs/decisions.md` #13 (bản tin dựng lại), #16 (gate), #26 (hai nguồn bản tin).
5. Mã nền: `experiments/forecast_sensor_v2.py` (benchmark, B4D/B5D), `experiments/foundation_zero_shot.py`
   (Chronos/TimesFM, kiểm tra không nhìn trước), `experiments/forecast_h1_diurnal.py`,
   `experiments/transfer_forecast.py` (nạp NERRS), `experiments/forecast_snapshot_coverage.py`.

## Câu hỏi nghiên cứu

Chronos-2 (arXiv:2510.15821, có biến ngoại sinh) với bản tin thời tiết **đúng lúc phát hành** + triều làm biến
"biết trước tương lai", dự báo trên phần dị thường so với chu kỳ ngày 7 ngày, có vượt ridge B5D (mốc mạnh
của mình) ở 15 phút–12 giờ không? Và giá trị của thời tiết thay đổi thế nào theo **nguồn bản tin**:
không có → giả → dựng lại (Open-Meteo Previous Runs) → thu thật → quan trắc?

## Đăng ký trước (chốt trong file `preregistration.json` của lần chạy TRƯỚC khi xem kết quả)

- Mốc so: persistence, ridge B4D, **ridge B5D** (mốc chính), diurnal-anomaly-7d, Chronos-Bolt base,
  TimesFM 2.5, TiRex nếu chạy được trên CPU.
- Giả thuyết chính H1: Chronos-2 + thời tiết (bản tin dựng lại) giảm MAE ≥ 5 % so với B5D ở 6–12 h và đạt
  gate #16 (≥ 4/5 fold thắng MAE và RMSE + DM-HLN lockbox p < 0,05).
- H2 (nguồn bản tin): thứ tự giá trị không ≤ giả ≤ dựng lại ≤ thu thật ≤ quan trắc; báo cáo chênh lệch kèm CI.
- H3 (khoảng tin cậy): PI80 của Chronos-2 sau conformal (aci_amp, RL-19) nằm trong [0,75; 0,85] ở cả hai
  chế độ biên độ (trước / sau giữa T8).
- Đánh giá trên **NERRS (nhiều trạm, công khai) là chính**, NB1 là nghiên cứu tình huống.
- Mọi thay đổi sau khi xem kết quả ghi rõ "post-hoc".

## Dữ liệu

| Dữ liệu | Có sẵn? | Việc cần làm |
| --- | --- | --- |
| NB1 nhiệt độ + QC | Có (`sensor-history-20261024`, lịch sử trực tiếp) | Áp cờ thiết bị RL-72 khi dùng NH4/TSS (không ảnh hưởng nhiệt độ) |
| Bản tin dựng lại NB1 | Có (`external-context-06M26042804-*`) | — |
| Bản tin thu thật NB1 | Đang thu (task + worker) | Dùng khi độ phủ đủ (sớm nhất ~09/12) |
| NERRS 2007–2011 | Có (`data/foreign/nerrs_ncei/`) | Đủ cho benchmark nhiều trạm với thời tiết quan trắc (trạm khí tượng NERRS) |
| NERRS 2012–2025 | **Chưa** | Chủ dự án tải qua CDMO (hướng dẫn trong chat 28/10), lưu `data/foreign/nerrs_cdmo/raw/` |
| Bản tin thật cho NERRS quá khứ | **Chưa** | GFS/GEFS lưu trữ NOAA trên AWS (miễn phí) hoặc Open-Meteo Previous Runs (từ 2024) — kiểm tra phạm vi trước khi tải |
| Triều NERRS | Một phần (độ sâu sonde) | NOAA CO-OPS nếu cần |

## Kế hoạch thử nghiệm (không viết bài)

- **T1 (tuần 1):** venv `.venv-fm` cài `chronos-forecasting` bản có Chronos-2; đo tốc độ CPU bản small/base;
  chạy zero-shot Chronos-2 không biến ngoại sinh trên đúng origin H1.4 → so B4D / Chronos-Bolt.
- **T2 (tuần 1–2):** Chronos-2 + thời tiết dựng lại + biến lịch / triều trên NB1; dự báo dị thường so với chu kỳ
  7 ngày (phần dư) và dự báo trực tiếp; gate so với B5D.
- **T3 (tuần 2–3):** NERRS nhiều trạm: thời tiết quan trắc (trạm met) làm "trần trên"; 2012–2025 khi có dữ liệu.
- **T4 (tuần 3):** conformal (aci_amp, ACI theo độ trễ) trên quantile của Chronos-2; độ phủ theo chế độ biên độ.
- **T5 (khi có ≥ 57/63 ngày bản tin thật):** bậc "thu thật" của thang nguồn bản tin.
- Mỗi bước: thư mục chạy mới `paper1-<bước>-<YYYYMMDD>/` có NOTES.md, manifest sha256; một dòng RESULTS, một mục RL.

## Quy tắc phối hợp với phiên điều phối

- Làm trên nhánh `paper/chronos2-weather` trong worktree `D:/2impusc/HAP-paper1`. Không push khi chưa được phép.
- Mã mới chỉ ở `experiments/paper1_*.py` và `tests/test_paper1_*.py`; không sửa `core/`, `research-map/`,
  task Windows. Cần sửa file dùng chung (ví dụ `forecast_sensor_v2.py`) thì thêm hàm, không đổi đầu ra cũ.
- Thêm RL / RESULTS ở cuối file; khi merge xung đột thì đánh lại số RL.
- Đưa mô hình vào runtime chỉ qua một quyết định mới trong `docs/decisions.md` do chủ dự án duyệt.
- CPU: tối đa 2 lõi khi phiên khác đang chạy (đặt OMP/MKL/torch threads).

## Câu mở đầu cho phiên mới (dán vào)

> Đọc `docs/paper/HANDOFF-paper1.md` và các tài liệu nó liệt kê. Làm việc trong worktree
> `D:/2impusc/HAP-paper1` (nhánh `paper/chronos2-weather` đã tạo sẵn), rồi thực hiện bước T1 theo đúng quy tắc trong file. Báo cáo bằng tiếng Việt.
