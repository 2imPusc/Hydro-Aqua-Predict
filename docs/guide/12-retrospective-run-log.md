# Nhat ky ket qua da chay — danh gia hoi cuu noi suy

**Ngay chay:** 2026-07-24
**Moi truong:** Python 3.11.9, `.venv`, pytest 9.0.2
**Pham vi:** du lieu lich su theo quy/tram cua `lab-realtime`; khong co mau lab
realtime moi va khong co DO sensor truc tiep trong tap danh gia.

## Lenh da chay

```powershell
$env:PYTHONPATH = "."
python experiments/retrospective_imputation.py `
  --region haiphong --target DO --risk-threshold 5 --risk-direction below

python experiments/retrospective_imputation.py `
  --region quangninh --target DO --risk-threshold 5 --risk-direction below

python -m pytest tests
```

Runner: `experiments/retrospective_imputation.py`. Cac model duoc so sanh tren
cung target la median baseline va XGBoost; split gom temporal holdout va
leave-one-station-out. Ket qua mang scope
`retrospective_historical_not_realtime_ground_truth`.

## Ket qua DO

| Region | Split | Model | n | MAE | RMSE | Bias | p95 abs. error | R2 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Hai Phong | Temporal | Median | 44 | 0.307 | 0.417 | -0.146 | 0.777 | -0.139 |
| Hai Phong | Temporal | XGBoost | 44 | 0.233 | 0.297 | -0.098 | 0.513 | 0.421 |
| Hai Phong | Station holdout | Median | 216 | 0.286 | 0.404 | -0.121 | 0.864 | -0.109 |
| Hai Phong | Station holdout | XGBoost | 216 | 0.188 | 0.261 | 0.006 | 0.551 | 0.535 |
| Quang Ninh | Temporal | Median | 311 | 0.165 | 0.222 | 0.128 | 0.455 | -0.502 |
| Quang Ninh | Temporal | XGBoost | 311 | 0.421 | 2.491 | 0.381 | 0.513 | -188.323 |
| Quang Ninh | Station holdout | Median | 1552 | 0.277 | 1.428 | -0.099 | 0.760 | -0.005 |
| Quang Ninh | Station holdout | XGBoost | 1552 | 0.321 | 1.805 | 0.047 | 0.681 | -0.606 |

## Doi chieu vung nguy co DO

Nguong kiem tra la `DO <= 5 mg/L`. Ca bon test partition deu co `n_risk = 0`:
TP/FN/FP deu bang 0; recall va precision khong xac dinh. Day la thieu bang
chung, **khong** phai bang chung model khong bo sot su kien nguy hiem.

## Benchmark model ladder bo sung — Hai Phong / DO

Lich chay bo sung cung ngay 2026-07-24 da so sanh global median, seasonal
median, Ridge, ElasticNet, ExtraTrees va XGBoost. ExtraTrees la model tot nhat
trong dot hoi cuu nay:

| Split | Model | MAE | RMSE | R2 |
|---|---|---:|---:|---:|
| Temporal | ExtraTrees | 0.194 | 0.253 | 0.581 |
| Temporal | XGBoost | 0.233 | 0.297 | 0.421 |
| Station holdout | ExtraTrees | 0.170 | 0.236 | 0.619 |
| Station holdout | XGBoost | 0.188 | 0.261 | 0.535 |

Seasonal median, Ridge va ElasticNet deu thua ExtraTrees trong ca hai split.
Day la candidate cho **contextual retrospective**, khong phai model operational:
`n_risk=0`, khong co uncertainty/OOD gate va khong co ground truth realtime.

## Verdict hien tai

- **Hai Phong / DO:** `contextual (retrospective only)`. XGBoost vuot median o
  ca hai split, nhung chua co event risk va chua co ground truth realtime.
- **Quang Ninh / DO:** `reject XGBoost; retain median/no model`. XGBoost thua
  median va co RMSE temporal rat lon; khong promote vao runtime.
- **Cac target khac:** chua chay benchmark moi; khong duoc suy dien verdict tu
  ket qua DO. Se duoc chay theo plan `11-per-target-imputation-benchmark-plan.md`.

## Batch per-target — 2026-07-25

Da chay model ladder tren toan bo target co trong data lich su. Artifact output
co the tai lai o `artifacts/experiments/retrospective-2026-07-25/` (inventory,
metrics va verdict theo tung vung).

Gate `contextual retrospective` phai dong thoi: giam RMSE so voi global median
va R2 duong o ca temporal/station holdout. Ket qua:

| Region | Target | Verdict | Model neu contextual |
|---|---|---|---|
| Hai Phong | DO | contextual retrospective | ExtraTrees |
| Hai Phong | Salinity | contextual retrospective | ExtraTrees + month |
| Hai Phong | PO4 | median | — |
| Quang Ninh | DO | median | — |
| Quang Ninh | Salinity | contextual retrospective | Ridge |
| Quang Ninh | Transparency | contextual retrospective | ExtraTrees |
| Quang Ninh | PO4 | median | — |
| Quang Ninh | BOD5 | reject | known artifact |
| Quang Ninh | Alkalinity | reject | known artifact |

`contextual retrospective` khong phai phep promote vao runtime: chua co
ground-truth realtime, uncertainty/OOD gate, va du event o vung risk.

## Ablation feature thoi gian — 2026-07-25

File chi tiet: `artifacts/experiments/retrospective-2026-07-25/`
`haiphong_time_ablation.csv` va `quangninh_time_ablation.csv`. So sanh dung
cung split/model, chi khac feature `sensor-only` voi `sensor + calendar`.

| Region / target | Calendar feature | Ket qua | Quyet dinh hoi cuu |
|---|---|---|---|
| Hai Phong / Salinity | `month` | ExtraTrees: temporal RMSE 0.646 -> 0.437, R2 -0.182 -> 0.458; station RMSE 0.387 -> 0.238, R2 0.685 -> 0.881 | Giu month; doi verdict thanh contextual retrospective |
| Hai Phong / PO4 | `month_sin`, `month_cos` | Co cai thien o station holdout, nhung R2 temporal van am voi tat ca model | Khong dung thoi gian de promote; giu median |
| Quang Ninh / Transparency | `month` | ExtraTrees station cai thien nhe (R2 0.269 -> 0.281), nhung temporal giam (R2 0.171 -> 0.162) | Khong co bang chung cai thien on dinh; giu sensor-only lam reference benchmark |

Can luu y: runtime cu dang them `month` cho QN/Transparency. Ket qua nay la
ly do de khong promote/cap nhat model moi voi feature do cho den khi co review
va train lai co version; chua tu dong sua runtime trong dot danh gia.

## Kiem thu phan mem

`pytest tests`: **61 passed**. Bao gom alert, sensor-health,
chemistry, imputation, evaluator, forecast va pipeline helpers.

## Han che va buoc ke tiep

1. Data lich su khong giong cadence/phan phoi cua sensor realtime; khong promote
   ket qua nay thanh bang chung van hanh.
2. Chay batch per-target theo guide 11, bat dau bang inventory va seasonal
   median/Ridge/ExtraTrees truoc khi tune XGBoost.
3. Khi co mau lab doi chieu, lap lai bang `paired.csv` va cap nhat nhat ky nay
   bang ket qua ground-truth doc lap.
