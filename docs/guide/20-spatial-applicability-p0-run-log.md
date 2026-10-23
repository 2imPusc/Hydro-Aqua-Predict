# Nhat ky P0 - vung tin cay khong gian Hai Phong

**Ngay chay:** 2026-07-26  
**Script:** `experiments/spatial_applicability.py`  
**Lenh:**

```powershell
cd D:\2impusc\Hydro-Aqua-Predict
..\.venv\Scripts\python.exe experiments\spatial_applicability.py `
  --region haiphong --targets DO Salinity `
  --output-dir experiments\output\spatial-applicability-p0-haiphong
```

## Pham vi va cach doc dung

Day la benchmark historical theo quy/tram, khong phai du lieu sensor 1 phut,
khong phai ground truth realtime, va khong duoc dung de mo ban do hay canh bao.
Baseline `anchor_copy_observed_value` xem gia tri tai mot tram neo la du bao
cho tram dich cung thoi diem. No do sai so dai dien theo khoang cach, chua co
model hoc may.

## Audit dau vao

| Chi so | Ket qua |
| --- | ---: |
| Ban ghi hop le | 216 |
| Tram | 14 |
| Moc thoi gian quy | 22 |
| Tram co toa do khong nhat quan | 0 |

Chi tiet catalog, cap anchor-target va metric nam o
`artifacts/experiments/spatial-applicability-p0-haiphong/` (ignored runtime
output, co the tao lai bang lenh tren).

## Baseline anchor-copy

| Bien | Khoang cach | So cap | MAE | RMSE | p95 absolute error |
| --- | --- | ---: | ---: | ---: | ---: |
| DO | 0.5--1 km | 36 | 0.214 | 0.298 | 0.659 |
| DO | 2--5 km | 156 | 0.184 | 0.270 | 0.598 |
| DO | 10--20 km | 1,276 | 0.199 | 0.295 | 0.607 |
| DO | >20 km | 84 | 0.219 | 0.356 | 0.790 |
| Salinity | 0.5--1 km | 36 | 0.000 | 0.000 | 0.000 |
| Salinity | 2--5 km | 156 | 0.036 | 0.075 | 0.177 |
| Salinity | 10--20 km | 1,276 | 0.257 | 0.339 | 0.696 |
| Salinity | >20 km | 84 | 0.469 | 0.513 | 0.775 |

Dong Salinity 0.5--1 km bang 0 can la mot dau hieu can kiem tra them ve cach
tong hop/lam tron du lieu, khong duoc coi la bang chung mo rong vung tin cay.
Khong co ca DO <=3 mg/L nao trong cac cap benchmark, vi vay recall/false
negative cua canh bao DO nguy hiem **khong xac dinh duoc**.

## Tai tao ban kinh HSI cu

Script tai tao dung cau truc rule cu (`alpha=0.6`, bin 1 km, min 0.5 km,
max 30 km) tren HSI tinh tu quan trac cung thoi diem. Ket qua: 216 radius row,
141 cap duoc chap nhan, median R = 0.5 km, ty le cung nhan HSI = 100%.

Con so 100% nay khong phai thanh cong cua model: rule da doc HSI cua tram dich
cung thoi diem de quyet dinh ban kinh. Output duoc gan
`diagnostic_only_observed_hsi_leakage` va bi cam dung trong runtime.

## Ket luan P0 va buoc tiep theo

1. Toa do va pairing historical HP du de tiep tuc nghien cuu spatial.
2. Khong co bang chung nao de gan ban kinh van hanh quanh NB1 hay noi suy sang
   vung nuoi Hai Phong.
3. Pha tiep theo la tao outer split theo tram/thoi gian va fit error-bound
   khong gian tren training fold; calibration va danh gia chi tren held-out.
4. Can bo sung mau/label stress (nhat la DO thap) truoc khi danh gia policy
   canh bao spatial.

## Kiem tra portability tren Quang Ninh

Cung script da chay tren 1,584 dong = 99 tram x 16 quy cua Quang Ninh. Toa do
cua 99 tram deu nhat quan; diagnostic radius co median 0.5 km (1,584 radius
row, 2,337 cap duoc chap nhan). Nhu Hai Phong, ty le cung nhan HSI 100% la
leakage diagnostic, khong phai coverage.

Baseline anchor-copy cho thay do man khong on dinh theo khong gian: MAE 0.475
o 0.5--1 km, 1.139 o 5--10 km, 2.021 o 10--20 km va 3.342 o >20 km. Recall
rui ro do man thap giam tu 0.815 o 5--10 km xuong 0.056 o 10--20 km va 0.015
o >20 km (co 369 va 5,142 false negative tuong ung). Day la bang chung de
P1 phai tao confidence theo bien/khoang cach/zone, thay vi dat mot ban kinh
chung cho toan vung.

## P1 - error-bound spatial baseline, Hai Phong

P1 duoc them trong `experiments/spatial_applicability.py`. Thay vi dua ra mot
ban kinh ``dung/khong dung``, baseline tinh quantile p90 cua absolute error
theo distance bin tren train set, sau do them split-conformal correction tren
calibration set. Hai protocol outer deu duoc chay:

- `forward_temporal`: 60% moc som train, 20% calibration, 20% moc muon test;
  khong duoc dung du lieu tuong lai de tao bound.
- `leave_target_station_out`: giu toan bo cap co tram dich ngoai train va
  calibration, sau do pool metric giua cac tram dich.

| Protocol | Bien | So cap test | Coverage bound 90% | Mean bound | MAE |
| --- | --- | ---: | ---: | ---: | ---: |
| forward temporal | DO | 910 | 98.9% | 0.760 | 0.194 |
| forward temporal | Salinity | 910 | 90.5% | 0.558 | 0.237 |
| leave target station out | DO | 2,088 | 90.0% | 0.482 | 0.203 |
| leave target station out | Salinity | 2,088 | 93.7% | 0.562 | 0.212 |

Ket qua theo bin can duoc giu kem khi xet gate. Vi du, Salinity temporal o
`>20 km` chi cover 65.7%, va DO station-holdout o bin 1--2 km co 12 cap chi
cover 83.3%. Vi vay **chua promote** bat ky tier `high/medium/low` nao vao
map hay pipeline realtime. P1 hien chi cung cap output shadow research:
`error_bound_predictions.csv` va `error_bound_metrics.csv`.

### Promotion gate 80/90/95

Script nay da chay them bound 80%, 90% va 95%, tinh Wilson lower bound 95% cho
coverage cua moi bin va doi hoi ca hai protocol outer phai dat. Bin co it hon
30 cap, thieu protocol, lower bound khong dat, hoac xa hon research cap 10 km
deu nhan `not_applicable`. Research cap la safety gate tam thoi, khong phai
ban kinh van hanh.

Trong tap HP hien tai, trong 36 combination (2 bien x 3 coverage x 6 bin),
chi Salinity 5--10 km la `shadow_candidate` o coverage 80% va 90%; 34
combination con lai la `not_applicable`, va khong co combination nao 95% dat.
`shadow_candidate` chi la ket qua nghien cuu co dieu kien, **khong** la quyen
to mau map/du doan ao/canh bao. Output `spatial_gate_summary.csv` la hop dong
bat buoc cho P2 sau nay.

## Research map overlay

Dashboard da co overlay geodesic band quanh NB1, cat bang OSM coastline water
polygons local (`map/water-polygons-split-4326`, snapshot 2026-02-04). Vi vay
phan geometry nam tren dat lien khong duoc render. Config versioned hien chi
co Salinity 5--10 km, coverage target 90%, va ghi ro
`research_shadow_only`, `used_by_alerts=false`, `used_by_emergency=false`.

Day khong phai mot vung gia tri du bao lien tuc: phan 0--5 km, >10 km va moi
chi so khac van khong du evidence nen khong to mau. Truoc khi dung map cho
van hanh, can polygon vung nuoi, water-body/zone va ground truth Hai Phong.

## Hai che do de demo

Dashboard co selector cho hai lop rieng biet:

1. `Demo HSI legacy (tat ca tram)`: tai tao rule R cua `aqua-forecast` tren
   snapshot HP 2024-11-01 (14 tram day du), ve vong cho tung tram va cat theo
   water mask. Tooltip hien HSI, nhan, R va chu `not validated`.
2. `Validated shadow (gate moi)`: chi hien evidence P1 da qua gate, hien tai
   la band Salinity 5--10 km quanh NB1.

Ca hai lop deu khong kich hoat alert. Che do 1 phuc vu minh hoa voi giang vien;
che do 2 phan biet ro nhung gi da duoc kiem dinh.
