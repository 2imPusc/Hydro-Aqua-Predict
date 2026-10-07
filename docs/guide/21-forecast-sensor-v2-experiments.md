# Forecast Sensor v2 — thí nghiệm độc lập

Các script dưới `experiments/forecast_sensor_v2.py` không đọc model runtime và
không thay đổi pipeline, alert hay dashboard. Chúng benchmark bốn sensor đo trực
tiếp ở +15/+30/+60 phút bằng direct forecasting, rolling-origin và lockbox 14
ngày cuối.

```powershell
python experiments/forecast_sensor_v2.py data/greenlab/greenlab_export.csv `
  --station 06M26042804 --output artifacts/experiments/forecast-v2/run-001
```

Artifact gồm `manifest.json`, `metrics_per_fold.csv`, `metrics_strata.csv`,
`predictions.csv` và `research_gate.csv`. `data-gen` và `data-v3` bị từ chối có
chủ ý vì là dữ liệu classification tổng hợp, không phải chuỗi sensor theo thời
gian.

Để tích lũy weather forecast as-issued mà không đụng runtime:

```powershell
python experiments/forecast_snapshot_store.py --station 06M26042804 `
  --output artifacts/experiments/forecast-v2/weather-snapshots.jsonl
```

Sau khi đã có snapshot thật đủ thời gian, chạy ablation B5:

```powershell
python experiments/forecast_sensor_v2.py data/greenlab/greenlab_export.csv `
  --station 06M26042804 --snapshots artifacts/experiments/forecast-v2/weather-snapshots.jsonl `
  --output artifacts/experiments/forecast-v2/run-weather
```

Copernicus snapshot phải tuân cùng JSONL contract (`issued_at`, `valid_at`,
`retrieved_at`, `features`, `provider`, `product`). CHIRPS/GLORYS historical
chỉ được ghi nhận là retrospective exploratory context, không đưa vào B5
as-issued. Đánh giá độ bền downstream WQI từ residual thực nghiệm:

Với CHIRPS v3 đã tải về CSV, tạo antecedent rainfall có delay hai ngày mặc
định; file được đánh dấu `exploratory_only` và không thể là input B5:

```powershell
python experiments/forecast_retrospective_context.py chirps-v3.csv `
  --output artifacts/experiments/forecast-v2/chirps-antecedent.csv
```

```powershell
python experiments/downstream_forecast_robustness.py `
  artifacts/experiments/forecast-v2/run-001/predictions.csv `
  --output artifacts/experiments/forecast-v2/run-001/downstream_wqi.csv
```
