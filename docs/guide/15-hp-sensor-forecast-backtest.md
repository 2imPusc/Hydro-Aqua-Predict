# Backtest forecast sensor — Hai Phong

Nguon: `data/greenlab/greenlab_export.csv`, tram `06M26042804`. Chuoi duoc
median theo 3 phut, khong interpolate; temporal holdout 20%. So sanh XGBoost
voi persistence (giu gia tri sensor gan nhat) tai 15/30/60 phut.

| Sensor | 15 phut | 30 phut | 60 phut | Verdict hien tai |
|---|---|---|---|---|
| Temperature | XGB RMSE 0.167 < persistence 0.206 | 0.173 < 0.201 | 0.190 < 0.221 | XGB candidate |
| pH | XGB 0.033 > 0.015 | 0.039 > 0.019 | 0.049 > 0.027 | Persistence |
| NH4 | XGB 1.622 > 1.241 | 2.488 > 1.839 | 3.932 > 2.686 | Persistence |
| TSS | XGB 12.746 > 12.554 | 14.272 < 17.069 | 15.627 < 17.940 | Chua promote: RMSE tot hon o 30/60 nhung MAE cao hon |

Bang day du: `artifacts/experiments/retrospective-2026-07-25/`
`hp_sensor_forecast_backtest.csv`.

Ket qua nay chi danh gia sensor do truc tiep. Forecast DO hien tai la chuoi
forecast tren DO noi suy, nen chua duoc dung de nang cap inferred-DO alert cho
den khi co uncertainty va bang chung target DO doc lap.

## Benchmark da mo rong: model + time feature

Ngay 2026-07-25, da chay lai tren cung chuoi 3 phut voi Ridge, ExtraTrees,
XGBoost va persistence. Moi model duoc so sanh tai 15/30/60 phut; model chi
duoc chon khi dong thoi giam ca MAE va RMSE so voi persistence o ca ba horizon.

| Sensor | Ket qua chon | Quyet dinh |
|---|---|---|
| Temperature | XGBoost + calendar time vuot persistence 3/3 horizon; RMSE trung binh 0.168 | Candidate realtime |
| pH | Khong model nao vuot persistence o ca 3 horizon | Persistence |
| NH4 | Khong model nao vuot persistence o ca 3 horizon | Persistence |
| TSS | Ridge tot hon ca hai metric o 2/3 horizon, chua dat gate | Persistence |

File chi tiet: `artifacts/experiments/retrospective-2026-07-25/`
`hp_sensor_forecast_model_benchmark.csv` va `_selection.csv`. Benchmark nay
chua co weather feature: weather theo gio da duoc tich hop o che do quan sat,
nhung chua co lich su forecast thoi tiet theo timestamp de backtest khong ro ri.

## Shadow integration

`core/sensor_future.py` now implements the selected sensor-first chain for
Hai Phong: direct XGBoost+time Temperature forecasts and timestamp-aware native
cadence XGBoost TSS forecasts at 15/30/60 minutes, persistence pH/NH4, NH3
derivation, then contextual DO/Salinity inference. TSS falls back to
persistence when its model bundle is absent or the last ten readings span more
than 30 minutes, so a telemetry gap is never bridged by the learned model.
It is attached to the pipeline as `sensor_future` in shadow mode and is never
used by alerts or suitability. Train/rebuild the three Temperature bundles with
`python experiments/train_sensor_future.py data/greenlab/greenlab_export.csv`.

## Lần triển khai 2026-07-25

- Đã tạo sáu bundle: Temperature XGBoost+time và TSS XGBoost native-cadence,
  mỗi loại tại 15/30/60 phút.
- Smoke test trên nguồn dữ liệu được cấu hình trả `ready`; khi MongoDB không
  truy cập được, `fetch_raw` đã chuyển sang `local_csv_fallback` và TSS tại cả
  ba horizon đều ghi nguồn `xgboost_lags`.
- `83 passed` cho toàn bộ `tests`. Kết quả này xác nhận tích hợp
  kỹ thuật, **không** phải bằng chứng đủ để đưa dự báo vào cảnh báo khẩn. Luồng
  vẫn là `shadow`, cần tiếp tục tích lũy forecast/outcome thực tế và đánh giá
  rolling-origin trước khi cân nhắc thay đổi chính sách cảnh báo.

## Backtest đầy đủ đến 2026-07-26

Dữ liệu Hải Phòng được ghép từ `data/greenlab/exports/all_data/` (29/05–04/07)
và API GreenLab (05/07–26/07 07:42). Dữ liệu API dạng long được gộp median
khi một sensor có nhiều record trong cùng phút. Chuỗi cuối cùng có 80.664
timestamp; đánh giá temporal holdout 20%, target được ghép theo timestamp thực
với tolerance +/-2 phút.

| Sensor | 15 phút (MAE / RMSE) | 30 phút (MAE / RMSE) | 60 phút (MAE / RMSE) | Quyết định |
|---|---:|---:|---:|---|
| Temperature persistence | 0.182 / 0.237 | 0.189 / 0.250 | 0.207 / 0.275 | — |
| Temperature XGBoost | **0.150 / 0.198** | **0.158 / 0.211** | **0.181 / 0.239** | XGBoost+time |
| TSS persistence | 17.464 / 45.785 | 19.873 / 48.875 | 22.412 / 49.681 | — |
| TSS XGBoost | **16.765 / 42.057** | **18.209 / 42.008** | **20.404 / 44.008** | XGBoost native cadence |
| pH | persistence thắng hoặc ổn định hơn ở 30/60 phút | | | Persistence |
| NH4 | persistence thắng cả ba horizon | | | Persistence |

Kết quả chi tiết: `artifacts/experiments/retrospective-2026-07-26/`
`hp_timestamp_aware_full_backtest.csv`. Sáu bundle runtime đã được train lại
từ toàn bộ chuỗi. Đây là bằng chứng retrospective; forecast vẫn chỉ dùng ở
`shadow`/advisory, không dùng để phát cảnh báo khẩn.
