# Ke hoach danh gia noi suy theo tung chi so

## Pham vi va ket luan duoc phep dua ra

Moi cap `(vung, target)` la mot bai toan rieng: Hai Phong va Quang Ninh khong
gop chung; DO, Salinity, PO4, Transparency... khong dung chung mot score. Data
hien co la du lieu lich su theo quy/tram, vi vay ket qua chi la **bang chung
hoi cuu** de loai model yeu va chon candidate. No khong chung minh duoc do
dung tren sensor realtime hay muc do an toan cho canh bao khan cap.

Ket qua cu cua `cv_r2.json` la LOO theo tram. Benchmark nay thay the vai tro
quyet dinh cua no bang temporal validation va station holdout, nhung chua sua
`core/impute.py` cho den khi co gate chap nhan.

## 1. Tao inventory truoc khi train

Cho moi `(region, target)` trong `IMPUTATION_TARGETS`:

- [ ] Bao cao so dong hop le, ty le missing, so tram, so quy/thoi diem va phan
  bo target (min/median/max, quantile 5/95, so gia tri duy nhat).
- [ ] Kiem tra target co constant, gan deterministic voi cot khac, hoac co gap
  bat thuong theo tram/quy. Danh dau `artifact_suspect`; khong cho phep model
  duoc chap nhan chi vi R2 cao.
- [ ] Kiem tra feature thuc su: HP hien khong co COD nen tag `5feat` phai duoc
  hien thi la 4 feature thuc te, khong goi sai la 5 feature.
- [ ] Chot don vi va meaning cua target; doi chieu rang buoc vat ly/hoa hoc.

**Output:** `target_inventory.csv` va danh sach target `eligible / insufficient /
artifact_suspect` cho tung vung.

## 2. Protocol chia du lieu chong leakage

Moi model/target deu dung cung mot split, seed va sample set.

1. **Temporal rolling-origin (primary):** nhieu fold theo thu tu quy; train chi
   dung qua khu, test la block tuong lai. Bao cao median va worst-fold metric,
   khong chi mot split 80/20.
2. **Leave-one-station-out (secondary):** giu nguyen mot tram lam test, lap lai
   cho tung tram. Day la kiem tra kha nang chuyen doi khong gian.
3. **Stress strata:** bao cao rieng theo mua/quy, station va phan vi target
   thap/cao. Khong random split lam ket qua chinh.
4. Mọi transform (imputation feature, scale, encoding, tuning, conformal) phai
   fit trong training fold; test fold khong duoc tham gia bat ky buoc nao.

## 3. Model benchmark theo thu tu

Khong bo sung nhieu model cung luc. Chay theo bac thang, dung lai neu khong co
cai thien on dinh.

| Tang | Model | Muc dich | Trang thai |
|---|---|---|---|
| A | Global median | San dung, luon phai co | Bat buoc |
| A | Seasonal/station median | Kiem tra gia tri cua mua va tram | Bat buoc neu du mau |
| B | Ridge/ElasticNet | Quan he don gian, de giai thich | Bat buoc |
| B | ExtraTrees | Nonlinear baseline cua scikit-learn | Thu nghiem |
| C | XGBoost | Candidate nonlinear hien co | Thu nghiem |
| D | Quantile + conformal wrapper | Prediction interval va reject | Chi cho candidate qua gate |

Khong them LSTM/Transformer, CatBoost hay ensemble phuc tap trong dot nay: data
theo quy va so luong tram hien tai qua nho de bien do phuc tap thanh bang chung.
Neu Ridge, ExtraTrees va XGBoost deu khong vuot baseline, ket luan dung la
`median/no model`, khong phai tiep tuc them model.

## 4. Metric bat buoc cho moi target va split

- Regression: `n`, MAE, RMSE, bias, p95 absolute error, R2, median/worst-fold.
- So sanh: chenh lech voi seasonal median; bootstrap CI cho MAE/RMSE neu `n`
  du lon.
- Robustness: metric theo station, quy/mua va low/high quantile.
- Safety decision (chi target co nguong nghiep vu): TP, FN, FP, TN, recall,
  precision, false-alert rate. Bao cao `n_risk`; `n_risk=0` nghia la **khong
  danh gia duoc**, khong phai recall=100%.
- Uncertainty (sau gate): coverage, mean interval width va coverage rieng trong
  vung risk.

## 5. Gate ra quyet dinh theo target

| Ket qua | Dieu kien toi thieu | Cach dung |
|---|---|---|
| Reject / median | Thua baseline, metric khong on dinh, artifact, hoac thieu mau | Khong train model |
| Contextual | Vuot baseline o temporal; khong co bang chung risk du | Hien thi tham khao |
| Early-warning candidate | Vuot baseline o temporal **va** station, on dinh qua fold, co OOD/reject | Shadow alert, khong Emergency |
| Operational candidate | Co ground truth realtime, interval calibrated va du event risk | Chi sau pilot/gate chuyen gia |

Quy tac khong thay doi: gia tri noi suy khong the la bang chung duy nhat de phat
Emergency. DO critical can DO sensor truc tiep hop le.

## 6. OOD, uncertainty va weather

Chi ap dung cho target dat `contextual` tro len:

- [ ] OOD gate: feature missing, nam ngoai quantile/range training, hoac distance
  cao so voi training -> tra `rejected`, khong prediction im lang.
- [ ] Conformal residual interval theo temporal fold; bao cao coverage 90% va
  width. Khong tuyen bo confidence neu chua calibrate.
- [ ] Weather experiment tach rieng: align timestamp, forecast-vs-observed
  weather, lag/rolling (mua, gio, ap suat, nhiet do khong khi).
- [ ] Ablation bat buoc: `sensor-only` vs `sensor + weather`, cung split va
  gate. Giu weather chi khi cai thien on dinh o ca temporal va station holdout.

## 7. Trinh tu trien khai

1. **Benchmark scaffold:** batch runner, inventory, rolling-origin split,
   seasonal median, Ridge va ExtraTrees; test deterministic.
2. **Chay tat ca target hien co:** tao bang `region x target x model x split`;
   cap nhat registry `reject/contextual/candidate`.
3. **Review khoa hoc:** dieu tra outlier/fold xau va artifact truoc khi tune.
4. **Chi voi candidate:** nested tuning nhe, conformal/OOD, feature dropout.
5. **Weather ablation:** sau khi sensor-only co candidate; khong dung weather de
   cuu mot target von khong duoc sensor-only support.
6. **Cap nhat runtime:** chi promote target qua gate, kem model card, version,
   scope va rollback. Tat ca target con lai fallback median/khong hien thi.

## Deliverables va definition of done

- [ ] `benchmark_imputation.py` tao report JSON/CSV reproducible, khong ghi de
  data/model dang dung.
- [ ] `target_inventory.csv` va bang tong hop per-target/per-region.
- [ ] Model card cho tung candidate: data period, feature, split, metric, OOD,
  limitation, risk decision va version.
- [ ] Test baseline/split/metric/leakage; regression test cho target reject.
- [ ] Review gate voi chuyen gia nuoi truoc khi doi `core/impute.py`.

**Definition of done dot danh gia cu:** moi target da co mot verdict ro rang
`reject`, `median`, `contextual` hoac `early-warning candidate`; khong target
nao duoc giu model chi dua tren mot R2 LOO cao.
