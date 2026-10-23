# Backlog nang cap he thong canh bao nuoi trong

> Trang thai: **ke hoach goc**. Cap nhat checklist nay khi hoan thanh tung hang muc;
> khong coi ket qua noi suy la du lieu do truc tiep cho canh bao khan cap.

## Muc tieu va nguyen tac chap nhan

Xay dung he thong realtime phan biet ro ba lop: chat luong sensor, nguy co tu
gia tri do truc tiep, va nguy co du bao/ noi suy. Canh bao khan cap ve DO chi
duoc phat khi DO do truc tiep hop le; gia tri noi suy chi dung de uu tien lay
mau, kiem tra, hoac canh bao tham khao.

- [x] Dat data contract version 1.0 va adapter raw long-form/QC view; chua ghi
  xuong persistent store trong khi cho xac nhan schema.
- [ ] Chot nguon, don vi, tan suat va chu so huu cho tung bien.
- [ ] Xac nhan don vi va co so bao cao NH4 (`NH4+`, `NH4-N` hay TAN), sau do
  hieu chinh he so quy doi NH4 -> NH3 truoc khi dung vao
  bat ky quy tac canh bao nao.
- [ ] Dinh nghia cap do, nguoi nhan, SLA, hanh dong va quy tac ket thuc/suy giam
  cua moi canh bao.
- [ ] Lap so dang ky cac gia dinh, nguong va phien ban policy/model.

## Giai doan 1 — Nen du lieu va ground truth

**Muc dich:** biet ro sensor dang do gi, noi suy cai gi, va co nhan doc lap de
kiem chung noi suy.

- [x] Tao data contract: timestamp UTC, station/ao nuoi, don vi, loai nguon
  (`sensor`, `manual_lab`, `derived`, `weather`), trang thai QC, do tre.
- [x] Co raw/QC views tach biet trong code; persistent append-only store la
  hang muc integration sau khi chot backend.
- [x] Thiet ke chuong trinh lay mau doi chieu: cung thoi diem, cung vi tri, co
  ca dieu kien binh thuong va stress; uu tien DO, NH3/NH4, do man, pH, nhiet do.
- [x] Co cong cu ghep mau lab–sensor co tolerance va kiem tra don vi de tao
  paired evaluation dataset; dang cho mau lab thuc te.
- [ ] Ghi nhan su kien van hanh (cho an, thay nuoc, quat/suc khi, mua lon,
  chet ca) lam nhan de danh gia canh bao.
- [ ] Kiem tra dong bo thoi gian sensor–thoi tiet–mau lab va xu ly missing/late
  data minh bach.

**Xong khi:** co dataset versioned va co tap ground truth tach rieng theo thoi
gian va ao/station.

## Giai doan 2 — Nghien cuu va kiem chung noi suy

**Muc dich:** chi dua vao van hanh cac bien co do chinh xac va do khong chac
chan duoc chung minh trong boi canh thuc te.

- [x] Co evaluator temporal/station holdout, baseline median va metric
  regression/risk; chua co ket qua vi chua co ground truth.
- [x] Co runner danh gia hoi cuu tren dataset HP/QN cu; ket qua duoc danh dau
  ro la historical, khong phai realtime ground truth.
- [x] Co ke hoach benchmark per-target/per-region, model ladder va promotion
  gate tai `docs/guide/11-per-target-imputation-benchmark-plan.md`.
- [x] Da luu log benchmark DO HP/QN, verdict va han che tai
  `docs/guide/12-retrospective-run-log.md`.
- [x] Da chay batch per-target HP/QN, luu inventory/metrics/verdict va chot
  candidate hoi cuu; chua promote bat ky model nao vao runtime.
- [x] Da chay ablation feature thoi gian: month duoc giu cho HP/Salinity;
  khong co bang chung on dinh de promote time feature cho HP/PO4 hay
  QN/Transparency.
- [x] Da dong goi HP/DO va HP/Salinity ExtraTrees v1 trong shadow mode, co
  NH4/unit, feature-range va OOD gate; khong anh huong alert/suitability.
- [x] Da backtest forecast sensor HP 15/30/60 phut so voi persistence; chi
  Temperature co XGBoost candidate on dinh. Chua dung forecast DO cho alert.
- [x] Da benchmark them Ridge, ExtraTrees va XGBoost co/khong co calendar time
  tren sensor HP. Temperature XGBoost + time vuot persistence o ca 15/30/60
  phut; pH, NH4, TSS giu persistence theo promotion gate MAE+RMSE.
- [x] Da thu nghiem weather-lag theo gio tai NB1: mưa/gio tich luy 1--24h va
  weather cua gio truoc. NH4 co tin hieu cai thien, TSS cai thien khong on
  dinh, Temperature/pH xau di. Day la observed-weather relationship study,
  khong phai backtest forecast-weather va khong duoc promote.
- [ ] Dung baseline: persistence, median theo mua/station, linear/robust
  regression truoc khi thu XGBoost hay mo hinh phuc tap.
- [ ] Danh gia bang temporal split, leave-one-station/pond-out va event split;
  khong dung random split lam ket qua chinh.
- [ ] Bao cao MAE, RMSE, bias, R2, sai so p95; kem baseline va so mau cua moi
  tap danh gia.
- [ ] Danh gia theo che do: mua/khong mua, ngay/dem, nhiet do cao, DO thap,
  station/ao, va thoi ky sensor loi.
- [ ] Them chi so do tin cay: prediction interval coverage, interval width,
  calibration, ty le OOD/reject.
- [ ] Them chi so quyet dinh: false-negative trong vung nguy co, false-positive
  trong vung an toan, lead time va alert burden.
- [ ] Thu nghiem feature weather: nhiet do/luong mua/gio/ap suat, lag va rolling
  windows; chi dung du lieu co timestamp va nguon ro rang.
- [ ] So sanh ablation `sensor-only` voi `sensor + weather`; giu weather chi
  khi cai thien tren test temporal va station holdout.
- [ ] Thu quantile/conformal prediction, OOD gate, feature-dropout va missing
  weather test.
- [ ] Xac lap gia tri noi suy hop le theo rang buoc vat ly/hoa hoc, khong chi
  clip ve 0.

**Quyet dinh gate:** mot target chi duoc dua vao policy khi vuot baseline,
on dinh qua split, duoc calibrate, co OOD/reject, va chuyen gia chap nhan pham
vi su dung. Neu khong, chi hien thi la experimental/contextual.

## Giai doan 2.5 — Forecast sensor-first Hai Phong

**Muc dich:** du bao cac sensor lap dat truoc, sau do moi noi suy cac chi so
khong lap dat tai tung horizon. Tuyet doi khong forecast DO noi suy nhu mot
chuoi doc lap de nang cap alert.

- [x] Chot baseline/model selection ban dau 15/30/60 phut va luu artifact
  benchmark tai `docs/guide/15-hp-sensor-forecast-backtest.md`.
- [x] Dong bo NB1 lam diem tham chieu weather cho sensor Hai Phong; weather
  runtime chi o che do observation, cache 60 phut.
- [ ] Chay rolling-origin walk-forward (nhieu cut theo thoi gian), thay cho
  mot holdout 80/20 duy nhat; bao cao mean/variance theo horizon.
- [x] Train ba bundle runtime Temperature XGBoost+time 15/30/60 phut;
  shadow runtime dung persistence pH/NH4/TSS va co fallback unavailable khi
  thieu bundle/lich su. Chua co uncertainty interval.
- [x] Pipeline da gan `sensor_future`: `sensor forecast -> NH3 derive ->
  contextual DO/Salinity` tai 15/30/60 phut. Toan bo output shadow/advisory,
  `used_by_alerts=false`; contextual output van bi khoa neu NH4 confirmation
  chua duoc nap vao process.
- [x] Co append-only shadow ledger: luu forecast, weather provenance as-issued,
  matcher actual sensor +/-4 phut va MAE/RMSE/bias theo horizon/model. Chi cham
  diem sensor do truc tiep; DO/Salinity cho ground truth doc lap.
- [x] Co lightweight shadow runner tach legacy pipeline, poll 60 giay phu hop
  cadence MongoDB; chay thu `--once` da phat hanh 3 forecast moi.
- [ ] Luu snapshot weather forecast tai moi lan quet (run time, model/source,
  valid time) de tao backtest as-issued. Khong dung observed weather tuong lai
  de chon model weather-aware.
- [ ] Khi co du snapshot, so sanh sensor-only voi sensor+weather forecast,
  voi lag/rolling weather da duoc chung minh va missing-weather fallback.
- [ ] Them prediction interval/conformal uncertainty, OOD, stale-gap gates va
  metric event: lead time, false alarm, recall nguy co.

**Gate tich hop:** co the thí diem sensor forecast khong weather cho
Temperature ngay khi co runtime bundle. Forecast weather-aware va forecast DO
chi duoc shadow sau walk-forward + as-issued weather; chua du bang chung cho
canh bao critical.

## Giai doan 3 — Dong goi model da duoc chap nhan

- [ ] Version hoa model bundle: feature contract, don vi, training period,
  metric, calibration, pham vi ap dung va nguong OOD.
- [ ] Output bat buoc: estimate, lower/upper interval, confidence, reason,
  input provenance va model version.
- [ ] Tu choi ket qua khi thieu feature quan trong, OOD, do tre qua han, hoac
  sensor input suspect/invalid.
- [ ] Tao regression test bang cac ca on dinh, stress, missing va OOD.
- [ ] Theo doi drift input, ty le reject, prediction error khi co mau lab moi.

## Giai doan 4 — Chat luong sensor va phat hien bat thuong

- [ ] Hoan thien missing, gap, plausible range, flatline, Hampel spike va CUSUM
  theo tung sensor; hieu chinh tham so bang data thuc.
- [ ] Tach `sensor fault/anomaly` khoi `environmental event`; DO thap keo dai
  co the la che do nguy hiem, khong phai outlier de bo qua.
- [ ] Danh gia precision/recall va time-to-detect tren su kien QC da gan nhan.
- [ ] Hien thi ro trang thai sensor, do tuoi du lieu va khuyen nghi kiem tra
  thiet bi.

## Giai doan 5 — Thiet ke policy canh bao

- [ ] Tach ba loai alert: (1) sensor/QC, (2) nguy co tuc thoi tu sensor truc
  tiep, (3) du bao/noi suy de canh bao som.
- [ ] Dung threshold + persistence + rate-of-change + compound stress +
  forecast; profile rieng cho ca gio va co phien ban.
- [ ] Dung confidence va evidence gate: khong nang cap Emergency neu khong co
  bang chung sensor truc tiep hop le.
- [ ] Thiet ke debounce, deduplication, escalation, acknowledgement,
  resolution va suppression co audit log.
- [ ] Danh gia offline: event recall, precision, median lead time, false alerts
  per pond-week, thoi gian phan hoi va ty le alert co hanh dong.
- [ ] Shadow mode truoc: ghi va danh gia alert ma chua gui thong bao that.

## Giai doan 6 — Tich hop realtime va van hanh

- [ ] Tach ingestion, QC, feature/imputation, risk engine va notification
  thanh cac thanh phan co schema dau vao/ra ro rang.
- [ ] Luu event/alert store bat bien: observation IDs, policy/model version,
  evidence, state transition, acknowledgement va outcome.
- [ ] Co retry/idempotency, monitoring latency, dead-letter cho ban tin loi va
  dashboard van hanh.
- [ ] Tich hop notification theo ma tran severity; chua tu dong dieu khien thiet
  bi trong giai doan dau.
- [ ] Viet runbook cho mat ket noi, sensor loi, alert hang loat va override.

## Giai doan 7 — Pilot, danh gia va mo rong

- [ ] Chay shadow 4–8 tuan, review hang tuan voi nguoi nuoi/chuyen gia.
- [ ] Chot acceptance gate truoc khi bat thong bao that cho tung cap severity.
- [ ] Pilot gioi han theo ao/station; co rollback policy/model trong vai phut.
- [ ] Tong ket outcome, update profile theo mua/ao va lap lich retraining co
  governance.

## Thu tu thuc hien de xuat

1. **Bat dau ngay:** Giai doan 1 va scaffold danh gia cua Giai doan 2.
2. **Chi sau khi co ground truth:** thuc nghiem weather, uncertainty va OOD.
3. **Chi sau gate model:** tinh chinh policy canh bao som tu bien noi suy.
4. **Cuoi cung:** event store, notification va pilot shadow.

## Trang thai hien tai

- [x] Prototype alert co nguong, toc do thay doi, stress ket hop va safety gate
  cho DO do truc tiep.
- [x] Prototype sensor health: missing/range/gap/flatline/spike/level-shift.
- [ ] Chua co ground truth dong thoi cho cac bien noi suy.
- [x] Co adapter Open-Meteo theo station/NB1 trong runtime payload; chua co
  weather forecast snapshot store hay weather feature duoc promote vao model.
- [ ] Chua co uncertainty/OOD gate, alert persistence hay notification store.
- [ ] Chua duoc test end-to-end do moi truong hien tai chua co Python.
