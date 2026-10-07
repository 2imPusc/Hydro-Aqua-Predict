# Ke hoach nghien cuu vung tin cay khong gian

> Trang thai: **ke hoach nghien cuu, chua duoc dua vao runtime/canh bao**.
> Pham vi dau tien: Ca gio, Hai Phong/Cat Ba; dung bo du lieu quan trac lich su
> da co. Khong phat thong bao va khong suy dien sang ao nuoi chua co kiem chung.

## 1. Muc tieu va cach goi dung

Muc tieu la tra loi: *tai mot thoi diem, ket qua cua trạm tham chieu co the
ap dung den dau quanh tram, va muc do tin cay cua tung o ban do la bao nhieu?*

Day la **do tin cay ap dung theo khong gian** (*spatial applicability*), khac
voi:

- **Khoang du bao theo thoi gian**: `estimate +/- interval` cho gia tri cua
  chinh tram tai 15/30/60 phut toi.
- **Noi suy tai tram**: uoc luong DO/do man tai vi tri sensor tu cac bien duoc
  do. DO van la bien suy luan, khong phai DO do truc tiep.
- **Vung tin cay khong gian**: do chac chan khi chuyen ket qua tu tram neo
  sang mot vi tri khac. No khong khang dinh ca vung co cung mot gia tri.

Ban do dau ra phai hien thi ca `nguon=spatially_extrapolated` va cap
`high/medium/low/not_applicable`; khong dung mot vong tron de bao ham “dung
chac” voi moi bien va moi dieu kien.

## 2. Phuong phap dang co trong `aqua-forecast`

File `D:\2impusc\aqua-forecast\utils\r_hsi.py` tao `R_cobia.csv` theo quy
trinh sau cho tung tram va tung quy:

1. Du bao cac bien moi truong tai cac tram, roi tinh HSI ca gio.
2. Tinh `sigma_HSI` cua toan bo tram trong quy va dat nguong `0.6 * sigma_HSI`.
3. Tinh khoang cach Euclid tren toa do VN-2000, chia cac tram lan can thanh
   vong 1 km, toi da 30 km.
4. Mo rong ban kinh den khi trung binh `|HSI_tram - HSI_lan_can|` vuot nguong,
   hoac co mot tram lan can doi nhan HSI (nguong 0.5/0.75/0.85).
5. Ep ket qua trong [0.5, 30] km va ve vong tron Folium tren ban do.

Tai san sinh ra hien co co 396 dong = 99 tram x 4 quy (2026). Ban kinh trung
vi la **0.5 km**, trung binh **2.33 km**, p95 **8 km**, va lon nhat **30 km**.
Vi du, NB1 co trung vi 0.5 km. Day la ket qua cua quy tac tren **HSI du bao**,
khong phai ket qua coverage da kiem dinh voi quan trac that.

Trong `experiments/archive/` da co cac spike “tram ao” NB1 ->
tram khac cho DO/do man. Chung dung XGBoost va random KFold 3 fold tren du
lieu quy; co gia tri tham khao de chon NB1, nhung chua duoc coi la bang chung
cho mot ban kinh van hanh.

## 3. Diem tot co the giu lai

- Dung toa do VN-2000 va khoang cach theo met/km, phu hop hon phep tru lat/lon.
- Ban kinh theo tung tram va tung mua/quy, khong ap mot con so toan vung.
- Ket hop su khac biet lien tuc (`delta HSI`) va su khac biet quyet dinh
  (doi nhan HSI), nen de giai thich voi nguoi van hanh.
- Da co 99 tram x 16 quy 2021--2024 trong Quang Ninh de lam tap lich su cho
  thuc nghiem spatial holdout; khong can san sinh du lieu.
- HSI gan voi muc tieu nuoi ca gio, do do la lop hien thi/rui ro huu ich sau
  khi cac bien ben duoi duoc kiem chung.

## 4. Han che can sua truoc khi goi la “tin cay”

| Han che | He qua | Cach xu ly trong nghien cuu moi |
| --- | --- | --- |
| R duoc tinh tu HSI **du bao** o ca tram neo va tram lan can | Model cung sai co the tao HSI giong nhau; khong do sai so so voi thuc te | Dung quan trac held-out lam nhan danh gia; chi dung forecast sau khi da calibrate residual |
| `alpha=0.6`, bin 1 km, min 0.5 km, max 30 km la tham so dat tay | Ban kinh nhay manh theo tham so | Grid/sensitivity analysis va chon bang validation, khong chon theo hinh ban do |
| Trung binh trong bin che khuất tram bat thuong | Bo sot o nguy co cao | Dung quantile p90/p95 cua sai so va muc coverage, khong chi mean |
| Nhan HSI co nguong cung | Gia tri gan nguong de doi nhan, ban kinh khong on dinh | Bao cao khoang cach toi nguong va xac suat doi nhan; dung soft/threshold-risk score |
| Chi dung khoang cach phang | Luong nuoc, cua song, do sau, vinh/dao co the tach che do | Them water-body/zone, depth, distance-to-coast/estuary, mua; cam noi suy qua ranh gioi thuy van |
| Random KFold o spike tram ao | Ro ri thoi gian, diem qua lac quan | Blocked temporal split + leave-location-out; tuyet doi khong dung random CV lam ket qua chinh |
| Chi mot sensor realtime tai Hai Phong | Khong co ground truth dong thoi de xac minh “vung quanh NB1” | Ban do HP luc dau chi `research/not_applicable`; can mau/tram doi chieu truoc khi bat `low` tro len |
| HSI trung binh nhieu bien, trong do co DO suy luan | Co the che mat bien nguy hiem hoac khuếch dai sai so DO | Danh gia rieng tung bien, tung rule rui ro, HSI; luu provenance va uncertainty propagation |

## 5. Cau hoi, gia thuyet va tieu chi thanh cong

### Cau hoi

1. Sai so khi dung tram neo de dai dien cho vi tri khac tang theo khoang cach
   den muc nao, theo bien (nhiet do, pH, TSS, NH4/NH3, DO, do man) va theo mua?
2. Khoang cach co du hay phai them che do thuy van/depth/zone moi giai thich
   duoc sai so?
3. Vung `high/medium/low` co duoc calibrate khong: vi du o `high`, ty le diem
   nam trong gioi han sai so da cam ket co dat muc muc tieu khong?
4. Khi du bao 15/30/60 phut duoc dua vao, bat dinh thoi gian va bat dinh
   khong gian ket hop nhu the nao?

### Gate de goi la vung tin cay (dat truoc khi chay)

- Danh gia o tram va thoi gian **chua tung duoc dung de fit/calibrate**.
- Cho tung bien, bao cao MAE/RMSE/bias/p95 absolute error theo distance bin,
  season va zone; luon so voi baseline “khong suy dien/chi tram neo”.
- Vung high/medium/low phai co empirical coverage va sai so p95 rieng. Muc
  khoi dau de xem xet: high >=90%, medium >=80%, low >=60% trong error budget
  do chuyen gia chot theo bien. Cac so nay la **muc tieu thuc nghiem**, khong
  phai ket qua da dat.
- Risk/HSI: bao cao balanced accuracy, recall cho nhan nguy co, false-positive
  rate va ty le doi nhan. Khong duoc chi bao cao R2.
- Neu khong dat gate cho DO/Salinity, ban do khong hien thi gia tri do chi
  dung `not_applicable` hoac research overlay.

## 6. Thiet ke thuc nghiem de xuat

### Pha A - data contract va audit (P0)

- [x] Implement catalog x/y VN-2000, so ban ghi, so moc thoi gian va co
  coordinate-consistency audit trong `experiments/spatial_applicability.py`;
  da chay HP, xem `docs/guide/20-spatial-applicability-p0-run-log.md`. Van
  con thieu zone/water body, depth va WGS84 provenance.
- [ ] Tao bang long-form versioned: `station_id, observed_at, parameter,
  value, unit, qc_status, source_dataset`; quy doi don vi va tuyen bo cach tinh
  NH3 truoc khi gop.
- [ ] Kiem tra duplicate, toa do dao X/Y, missing, sampling co thoi, phan bo
  pair distance va so mau trong moi `anchor-target-time`.
- [ ] Dong bo theo quy cho bo lich su (chi de nghien cuu), giu timestamp goc
  cho realtime; tuyet doi khong noi suy dong 1 phut tu bo quy.

**Dau ra:** data inventory, map coverage va ma bam dataset. Dung neu ban ghi
hoac toa do khong du de danh gia mot bin.

### Pha B - benchmark “ban kinh cu” bang ground truth (P0)

- [x] Implement benchmark `anchor_copy_observed_value` theo cap
  `(anchor,target,time)` va metric theo distance bin; da chay HP. Day la
  historical evidence, chua phai ground truth realtime.
- [x] Tai tao rule R cu voi tham so goc 0.6/1 km/0.5--30 km trong che do
  `diagnostic_only_observed_hsi_leakage`; da cam su dung runtime. Chua quet
  sensitivity grid, vi can protocol held-out prediction o pha tiep theo.
- [ ] Danh gia ban kinh da du doan bao phu bao nhieu target co error nam trong
  error budget va cung risk label; bao cao theo station, quy va bien.
- [ ] So sanh ba baseline: (a) no-transfer, (b) vong tron co dinh, (c) R cu.

**Quyet dinh:** neu R cu khong hon vong tron co dinh tren held-out thi loai bo
rule, khong tinh chinh no theo cam tinh.

### Pha C - mo hinh spatial applicability co calibration (P1)

Tao dataset theo cap `(anchor, target, time, parameter)`. Target cua model la
`absolute_error = |value_target - estimate_from_anchor|`, va target phu la
`same_risk_label`.

- [x] Implement baseline distance-bin quantile + split-conformal calibration
  cho HP/DO va Salinity, co `forward_temporal` va
  `leave_target_station_out`; ket qua luu tai
  `docs/guide/20-spatial-applicability-p0-run-log.md`. Day la moc ma model
  phuc tap bat buoc phai vuot, khong phai model runtime.
- [ ] Model ung vien: GAM/quantile gradient boosting hoac ExtraTrees tren
  distance, season, zone, depth difference, feature difference tai anchor,
  weather regime (chi neu co timestamp phu hop). Giữ monotonic constraint voi
  distance neu thu vien ho tro; neu khong, kiem tra curve sau fit.
- [x] Calibrate split-conformal cho `spatial_error_bound_90` trong experiment.
  Chua co 80/95, OOD/zone gate hay runtime payload.
- [x] Implement experiment-level `not_applicable` gate cho bin thieu mau,
  thieu protocol, coverage khong calibrate va vuot research cap 10 km; output
  `spatial_gate_summary.csv`. Zone/convex hull/OOD feature cho cell map van
  chua the implement khi chua co polygon/zone metadata.

### Pha D - protocol danh gia dung (P1)

- [ ] **Outer test:** leave-one-station-out hoac leave-cluster-out (toan bo
  tram dich bi an), kem forward-chaining temporal folds; khong share cung
  station/time giua train va test.
- [ ] **Inner calibration:** tach mot khoang thoi gian/station rieng de chon
  tham so va calibrate; test chi dung mot lan de bao cao cuoi.
- [ ] Luu bootstrap confidence interval cho metric va ket qua theo bin, khong
  ket luan khi so cap qua it.
- [ ] Ablation: distance; +season; +zone/depth; +sensor/weather. Chi giu
  feature khi cai thien nhat quan tren outer folds.
- [ ] Stress test: mua lon, nhiet do cao, gia tri gan nguong HSI, missing
  parameter, target xa/tram isolated va data shift theo nam.

### Pha E - dich sang ban do vung nuoi (P2, chi sau gate)

- [x] Them research overlay vong/band quanh NB1, cat theo OSM coastline water
  polygons local; geometry tren dat lien khong duoc dua vao Folium. Overlay
  chi doc config `shadow_candidate`, khong co gia tri noi suy hay alert.
  Chua co polygon/mesh ao nuoi hay ranh gioi thuy van chi tiet.
- [ ] Voi moi cell, tim anchor hop le; tinh `distance`, `applicability_score`,
  error bound, OOD/zone gate va `data_age`.
- [ ] Hien thi 4 lop tach biet: gia tri/HSI du bao, risk class, confidence
  spatial, provenance. Tooltip bat buoc co tram neo, distance, horizon, model
  version, bound va ly do reject.
- [ ] Khi forecast temporal da co interval: hop bat dinh theo scenario
  `total_bound = temporal_bound + spatial_bound` (conservative) trong ban dau;
  chi dung convolution/ensemble sau khi co bang chung ve phu thuoc.
- [ ] Risk map uu tien worst credible case; khong nang cap Emergency chi tu
  spatially extrapolated inferred DO.

### Pha F - pilot Hai Phong (P3)

- [ ] Thu mau/lap diem doi chieu tai cac khoang cach va huong khac nhau quanh
  NB1, gom ca mua/nuoc lon/rong va su kien stress. DO co the la kit/mau lab
  dinh ky; khong can lap sensor DO lien tuc.
- [ ] Shadow map 4--8 tuan, doi chieu cac mau va log van hanh; review theo
  tuan voi chuyen gia/nguoi nuoi.
- [ ] Chi mo cap high/medium/low theo bien da dat gate local. Vung con lai
  luon la `not_applicable`, khong suy dien tu Quang Ninh sang Hai Phong.

## 7. Schema dau ra can tich hop sau nay

```json
{
  "anchor_station": "NB1",
  "target_cell_id": "hp-grid-...",
  "valid_at": "2026-...Z",
  "parameter": "salinity",
  "estimate": 29.1,
  "temporal_interval_90": [28.4, 30.0],
  "spatial_error_bound_90": 1.8,
  "confidence_tier": "medium",
  "coverage_target": 0.90,
  "distance_km": 1.3,
  "zone_gate": "pass",
  "applicability": "spatially_extrapolated",
  "model_version": "spatial-applicability-v1",
  "reason_codes": []
}
```

`estimate` chi co khi parameter da qua gate. Neu chi co rui ro tu DO noi suy,
payload phai ghi `parameter_source=inferred_contextual` va `used_by_emergency=false`.

## 8. Thu tu thuc hien va deliverable

1. **P0 (2 deliverable):** inventory/toa do + benchmark/tai tao R cu voi
   held-out historical truth. Day la buoc tiep theo, chua sua pipeline runtime.
2. **P1:** error-bound model, calibration va report leave-location-out. Chot
   xem co bien nao dat gate; nhiet do/pH/do man thu truoc, DO tach rieng.
3. **P2:** prototype grid/map chi doc, co mask/provenance/reject state. Khong
   lien ket notification.
4. **P3:** ground truth Hai Phong va shadow pilot. Chi khi dat gate local moi
   mo rong tu NB1 ra vung nuoi.

## 9. Tieu chi dung va an toan

- Khong co du mau trong bin/zone -> `not_applicable`, khong noi suy bang con
  so mac dinh.
- Khong duoc tai su dung R cua Quang Ninh nhu ban kinh Hai Phong.
- Khong duoc goi day la “do tin cay 90%” neu chua co calibration/test out-of-fold.
- Khong dung HSI trung binh de che mat DO/NH3 critical; policy canh bao van
  doc evidence theo bien, persistence va uncertainty.
- Ket qua, split, tham so, ma bam dataset va model version phai duoc luu cung
  report de co the tai lap.
