# Kế hoạch triển khai tổng — Hydro-Aqua-Predict (10/2026 → 03/2027)

> **For agentic workers:** Đây là kế hoạch cấp phase. Mỗi phase có plan chi tiết riêng (TDD, từng bước) trong `docs/superpowers/plans/`. Hiện chỉ Phase 0 có plan chi tiết: [2026-10-15-phase0-data-foundation.md](2026-10-15-phase0-data-foundation.md). Viết plan chi tiết cho phase kế tiếp khi phase trước qua gate.

**Goal:** Đưa 4 hướng phát triển từ trạng thái "pipeline có sẵn, chưa kiểm chứng" tới "shadow pilot có số liệu", theo thứ tự **1 → 2 ‖ 3 → 4**.

**Architecture:** Giữ nguyên kiến trúc hiện tại (`core/` pipeline, `experiments/` benchmark, `research-map/` bản đồ). Phase 0 sửa nền dữ liệu. Các phase sau gate theo số liệu trong `experiments/RESULTS.md`.

**Tech Stack:** Python 3.11 (pandas, xgboost, pytest), Node (fetcher cũ), Windows Task Scheduler, FastAPI + React (research-map).

---

## 1. Vì sao thứ tự là 1 → 2 ‖ 3 → 4

| Hướng | Bị giới hạn bởi | Hệ quả xếp lịch |
| --- | --- | --- |
| 1 Dự báo sâu | Công sức (sau backfill) | Mạch chính, làm ngay sau Phase 0 |
| 2 Cảnh báo thời tiết | **Lịch**: cần ~63 ngày bản tin as-issued liên tục, không backfill được | Bắt đầu thu ngay; phần phân tích B5 chờ dữ liệu |
| 3 Phân vùng tiềm năng | Công sức (dữ liệu quan trắc đã có) | Lấp khoảng chờ của hướng 2 |
| 4 Bản đồ tin cậy | Dữ liệu + phần cứng (1 sensor, cần điểm đối chứng) + kết quả hướng 2 | Chỉ làm sớm H4.1 (sửa lỗi rò rỉ) và H4.2 (interface); phần còn lại chờ gate |

Ghi quyết định này ở `docs/decisions.md` #10 (thay thế #8) — Task 1 của Phase 0.

## 2. Lịch tổng (tuần tính từ thứ Năm 2026-10-15)

```
Tuần         1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22
Phase 0     ██ ██                                                             dữ liệu đủ và đúng
Thu bản tin ── liên tục (chạy nền) ──────────────────────────────────────────▶ đếm 63 ngày
Phase 1           ██ ██ ██ ██                                                 H1.1–H1.3
Phase 1 shadow                ░░ ░░ ░░ ░░                                     H1.5 ≥ 4 tuần sổ ghi
Phase 3 (‖)       ██ ██ ██ ██ ██ ██                                           H3.1–H3.3
Phase 4a                   ██ ██ ██                                           H4.1, H4.2
Phase 2                                  ██ ██ ██ ██ ██                       H2.2–H2.5 (khi đủ origin)
Phase 2 pilot                                           ░░ ░░ ░░ ░░ ░░ ░░     H2.6 4–8 tuần
Phase 4b                                                ██ ██ ██ ██           H4.3–H4.5 (gate)
D0.6 ground truth ── song song, phụ thuộc người ─────────────────────────────▶
```

Mốc lịch sớm nhất cho B5 (H2.2): **63 ngày sau ngày việc thu bản tin đạt ≥ 90% độ phủ liên tục**. Nếu sửa xong trong tuần 1 thì khoảng giữa tháng 12/2026. Mỗi ngày thủng làm lùi mốc này.

## 3. Phase 0 — Dữ liệu đủ và đúng (tuần 1–2) · plan chi tiết: [phase0](2026-10-15-phase0-data-foundation.md)

| Việc | Roadmap | Gate |
| --- | --- | --- |
| Ghi quyết định thứ tự mới | — | `decisions.md` #10, `roadmap.md` cập nhật |
| Healthcheck tính độ phủ 7 ngày, trả `degraded` | (rule 4) | Test pass; chạy thật hiện `degraded` ở ~32% |
| Giảm thủng bản tin trên laptop (`WakeToRun`) | D0.3 | Độ phủ 7 ngày ≥ 90% sau 1 tuần, hoặc chuyển sang máy luôn bật |
| Client `DataByDate` + script backfill không ghi đè | D0.1 | Test; file mới trong `intervals/` |
| Kiểm tra múi giờ cột `Date` | D0.2 | Kết luận ghi vào `decisions.md`; test nếu phải sửa |
| Báo cáo độ phủ theo ngày + trạng thái COD | D0.1, D0.5 | Mỗi ngày ≥ 90% của 1.440 mốc, hoặc liệt kê khoảng thủng |
| Task thu sensor hằng ngày, tự đuổi bù | D0.3 | Task chạy, báo cáo độ phủ 7 ngày xanh |
| Xuất lịch sử chuẩn ra 1 CSV có hash | D0.4 | Benchmark đọc được, manifest có sha256 |
| Điền cột Key result trong `RESULTS.md` | nguyên tắc 5 | Không còn dòng trống ở các run chính |

## 4. Phase 1 — Dự báo sâu (tuần 3–6, shadow tới tuần 10)

Viết plan chi tiết khi Phase 0 xong. Nội dung dự kiến:

| Mốc | Việc | Gate | File chính |
| --- | --- | --- | --- |
| H1.1 | Chạy lại B0–B4 trên CSV lịch sử của Phase 0, rolling-origin có purge, giữ lockbox | Bảng MASE biến × chân trời trong `RESULTS.md` | `experiments/forecast_sensor_v2.py` |
| H1.2 | Thêm chân trời 180/360/720 phút cho Temperature, TSS, NH4, pH | MASE < 1 và Diebold–Mariano p < 0.05 so với persistence; biến không thắng thì giữ persistence | `forecast_sensor_v2.py` (`HORIZONS`), `core/sensor_future.py` |
| H1.3 | Conformal split theo thời gian cho PI 80% | Độ phủ thực tế trên lockbox trong [0.75, 0.85] | module mới `core/conformal.py` |
| H1.4 | (tùy chọn) Chronos-Bolt zero-shot cùng origin | Chỉ dùng nếu thắng XGBoost; thua vẫn ghi kết quả | `experiments/` (venv riêng nếu cần torch) |
| H1.5 | Shadow runner ghi sổ chân trời mới + PI | ≥ 4 tuần sổ ghi, metric ổn định | `core/shadow_runner.py`, `core/forecast_evaluation.py` |

Rủi ro: sau backfill vẫn chỉ ~4,5 tháng của 1 trạm. Chân trời 12 giờ có thể không thắng persistence; khi đó đó là kết quả, không phải thất bại.

## 5. Phase 3 — Phân vùng tiềm năng, chạy song song (tuần 3–8)

| Mốc | Việc | Gate | File chính |
| --- | --- | --- | --- |
| H3.1 | Hàm thuộc mờ (hình thang) thay ngưỡng cứng cho bộ tiêu chí cá giò | Test đơn điệu; giá trị sát ngưỡng không đổi nhãn đột ngột | module mới `hap_shared/fuzzy_suitability.py`, `hap_shared/thresholds/cobia_thresholds.json` |
| H3.2 | Độ nhạy trọng số: đều vs chuyên gia vs Monte Carlo ±20% | Bảng ổn định xếp hạng trạm (Kendall τ) | `experiments/suitability_weight_sensitivity.py` |
| H3.3 | Thêm tiêu chí dòng chảy, sóng, độ sâu | Mỗi tiêu chí ghi nguồn và độ phân giải | `data/depth`, CMEMS cache |
| H3.4 | Lắp vào `SuitabilityScorer` (H4.2) | Sau Phase 4a | — |

Nằm ngoài phạm vi: quy hoạch chính thức. Đầu ra là bản đồ nghiên cứu kèm độ tin cậy.

## 6. Phase 4a — Sửa lỗi và interface của bản đồ tin cậy (tuần 5–7)

| Mốc | Việc | Gate |
| --- | --- | --- |
| H4.1 | HSI dự báo từ trạm neo, không đọc dữ liệu trạm đích; chạy lại P0/P1 cho HP, QN | Báo cáo trung thực số trường hợp đạt gate 80/90/95 (hiện 1/36) |
| H4.2 | Tách `SuitabilityScorer` (protocol, implementation đầu tiên = `_classify_by_scoring`) và `ReliabilityModel` | Unit test; research-map gọi qua interface |

## 7. Phase 2 — Cảnh báo thời tiết (bắt đầu khi đủ origin, dự kiến tuần 9+)

| Mốc | Việc | Bắt đầu khi |
| --- | --- | --- |
| H2.1 | Báo cáo độ phủ B5 hằng tuần (`experiments/forecast_snapshot_coverage.py`) | **Ngay**, chạy định kỳ |
| H2.3 | Độ trễ mưa → NH4/TSS (`experiments/weather_lag_sensor_ablation.py`), dùng thời tiết quan trắc (Archive) | Ngay sau Phase 0 (không cần bản tin as-issued) |
| H2.2 | B5_external_as_issued vs B4_quality cùng origin | ≥ 63 ngày bản tin liên tục trùng sensor |
| H2.4 | Hiệu chỉnh ngưỡng bằng sự kiện thật | ≥ 10 sự kiện thực địa (D0.6) |
| H2.5 | Xác suất DO thấp / TSS tăng vọt trong N giờ (Brier vs tần suất nền) | Sau H1.3 |
| H2.6 | Shadow pilot 4–8 tuần + review với người nuôi | Sau H2.2 hoặc H2.4 |

## 8. Phase 4b — Bản đồ tin cậy đầy đủ (sau gate)

H4.3 (ghép rủi ro thời tiết), H4.4 (điểm đo đối chứng), H4.5 (dòng chảy Copernicus). Chỉ bắt đầu khi H2.2 có verdict **và** có ≥ 1 điểm đo độc lập.

## 9. Việc ngoài phần mềm (D0.6) — bắt đầu tuần 1, song song

| Việc | Ai | Cần cho |
| --- | --- | --- |
| Xác nhận đơn vị NH4 với GreenLab | Chủ dự án | Mọi kết quả NH3 |
| GPS lồng nuôi | Người nuôi / chủ dự án | Bản tin đúng điểm (H2), H4 |
| DO đo tay định kỳ | Cần người ở Cát Bà | Soft sensor DO, H2.5 |
| Nhật ký ≥ 10 sự kiện (`docs/guide/09-ground-truth-protocol.md`) | Người nuôi | H2.4 |

## 10. Quyết định chủ dự án cần chốt

1. **Máy luôn bật cho việc thu bản tin** (VPS / mini PC / máy lab). Laptop chỉ là tạm thời. Đây là việc ảnh hưởng mốc B5 nhiều nhất.
2. **Bản tin dựng lại từ lưu trữ** (Open-Meteo Previous Runs / Historical Forecast) với nhãn riêng `reconstructed_as_issued`: có dùng không. Phải kiểm tra trước API có phủ 2026-07-26 → nay và đủ lead time. Nếu dùng: thêm mục mới vào `decisions.md`, không trộn với `as_issued`.
3. Phạm vi hướng 3: nghiên cứu (bản đồ kèm độ tin cậy) hay sản phẩm cho quy hoạch.

## 11. Quy tắc áp dụng cho mọi phase

- Shadow trước; phải thắng baseline cùng origin; không dùng thông tin tương lai (`retrieved_at ≤ origin`).
- Không ghi đè hay xóa trong `data/`, `artifacts/`, `runtime/`.
- Mỗi run: `paths.EXPERIMENT_OUTPUT_DIR / <run>/` + manifest + 1 dòng `RESULTS.md` có Key result.
- Không push hay mở PR khi chưa được duyệt.
