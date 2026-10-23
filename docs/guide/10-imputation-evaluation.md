# Khung danh gia noi suy voi ground truth

Script `experiments/imputation_evaluation.py` danh gia ngoai mau mot candidate
noi suy; no khong thay doi `core/impute.py` hay alert runtime.

## Du lieu dau vao

Tao mot bang da ghep tu mau lab va snapshot sensor gan nhat. Template header:
`templates/imputation_evaluation_input.csv`.

- `actual` la gia tri mau lab/doc lap cua `target_metric`, sau khi da chuan hoa
  don vi. Khong la output cua imputer.
- `observed_at`, `station_serial` la bat buoc de chong leakage theo thoi gian va
  station. Cac cot weather de trong cho den khi co nguon thoi tiet da dong bo.
- Co the dung `nearest_sensor_context()` voi gioi han, vi du `15min`, de ghep
  mau lab voi sensor. Can bao cao ty le khong ghep duoc; khong tu doan gia tri.

## Chay baseline

Truoc do, tao `paired.csv` tu file mau lab da dien va raw sensor export. Cong
cu nay khong sua hai file nguon va se dung neu don vi target khong khop:

```powershell
python experiments/prepare_ground_truth_dataset.py `
  ground_truth_observations.csv data/greenlab/greenlab_export.csv `
  --metric DO --unit mg/L --tolerance 15min `
  --output paired_do.csv --report paired_do_report.json
```

Kiem tra `match_rate`, `unmatched_rows` trong report truoc khi danh gia. Khong
noi rong tolerance chi de co them dong; can ghi ro ly do neu thay doi cua so.

```powershell
python experiments/imputation_evaluation.py paired.csv `
  --target actual --split temporal --model median --risk-threshold 5 --risk-direction below
```

Sau do chay lai `--split station` va, chi khi du mau/feature, `--model xgboost`.
Bao cao phai so sanh voi median baseline, khong chi bao cao R2.

## Chi so bat buoc

- MAE, RMSE, bias, sai so tuyet doi p95, R2 va so mau out-of-sample.
- Voi nguong rui ro: TP/FN/FP/TN, recall, precision va false-alert rate. FN la
  diem quan trong nhat neu target duoc dung de canh bao som.
- Khi candidate co interval: coverage va do rong interval. Chua co interval thi
  khong duoc tuyen bo uncertainty da duoc calibrate.

## Quy tac doc ket qua

Temporal split la bang chung chinh cho van hanh tuong lai; station holdout chi
ra kha nang chuyen sang ao/tram khac. Khong duoc dung random split lam ket qua
chinh, va khong dua weather vao ket luan neu weather bi thieu, lech thoi gian
hoac khong cai thien ca hai split.

## Khi chua co ground truth moi

Co the chay `experiments/retrospective_imputation.py` tren dataset lich su da
co trong repo. Vi du DO o Hai Phong:

```powershell
$env:PYTHONPATH = "."
python experiments/retrospective_imputation.py `
  --region haiphong --target DO --risk-threshold 5 --risk-direction below
```

Runner so sanh median va XGBoost tren temporal holdout va station holdout. Ket
qua duoc gan scope `retrospective_historical_not_realtime_ground_truth`: no
chi dung de chon candidate va loai cac model yeu; khong duoc coi la bang chung
du de dua gia tri noi suy vao canh bao khan cap.

Chay batch toan bo target cua mot vung va luu inventory/metrics/verdict:

```powershell
python experiments/retrospective_imputation.py `
  --region haiphong --all-targets `
  --output-dir artifacts/experiments/retrospective-2026-07-25
```

Kiem tra ablation thoi gian cho cac target da duoc runtime cau hinh mua vu:

```powershell
python experiments/retrospective_imputation.py `
  --region haiphong --time-ablation `
  --output-dir artifacts/experiments/retrospective-2026-07-25
```
