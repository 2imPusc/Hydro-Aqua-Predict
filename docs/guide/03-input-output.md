# Dau vao va dau ra cua he thong `lab-realtime`

Tai lieu nay mo ta he thong dang nhan gi, phu thuoc vao dau, va tra ra nhung dang ket qua nao. Phan tach ro giua runtime input va offline/training input de nguoi tiep quan khong bi nham.

## 1. Dau vao runtime

Day la cac dau vao can cho luong chay demo, report, va pipeline hang ngay.

### Nguon du lieu sensor

- MongoDB snapshot thong qua `MONGODB_URI`, `MONGODB_DB_NAME`, `MONGODB_COLLECTION_NAME`
- CSV fallback: `data/greenlab/greenlab_export.csv`

**Muc dich**

- cung cap lich su reading cho `fetch_raw()`
- la nguon du lieu de tong hop theo ngay, classify va forecast

### Cau hinh tram

- `ingest/stations.yaml`

**Muc dich**

- anh xa `station_serial` -> region, ten tram, nhom tram lien quan nuoi trong
- phuc vu chon region cho imputation/forecast

### Bien moi truong va env

- `USE_LOCAL_CSV`
- `NH4_UNIT_SCALE`
- `NH4_UNIT_NOTE`
- `MONGODB_*`

**Muc dich**

- dieu khien cach nap du lieu
- ghi chu gia dinh don vi NH4

## 2. Dau vao offline/training

Day la nhom dau vao de tao model, fallback, va tai nguyen cho runtime.

### Du lieu lich su huan luyen

- `data/haiphong/clean_data.csv`
- `data/quangninh/clean_data.csv`

**Muc dich**

- train model imputation theo vung
- tinh median theo vung/tram
- train va kiem chung mo hinh forecast/spatial

### Tai nguyen model da huan luyen

- `core/models/*.pkl`
- `core/models/feat_cols.json`
- `core/models/regional_medians.json`
- `core/models/*.pkl`
- `core/models/forecast/*.pkl`
- `core/models/cv_r2.json`

**Muc dich**

- duoc nap lai khi classify, impute, forecast
- tranh phai train lai trong moi lan demo

## 3. Dau ra runtime

### Payload cho app demo

Ham `run_pipeline()` trong `core/pipeline.py` tra ve mot payload tong hop co dang khai niem nhu sau:

- `status`
- `station`, `region`, `timestamp`
- `data_source`, `warning`
- `measured_params`
- `anchor_classification`
- `virtual_stations`
- `forecast`
- `history`

**Y nghia**

- day la dau ra tong hop de `app/demo_app.py` render dashboard
- no ket hop ket qua classify, tram ao va du bao trong cung mot lan quet

### Bao cao CLI

`core/report.py` in ra:

- thong tin tram/ngay
- ket qua monitoring theo QCVN
- ket qua classification
- canh bao lien quan toi imputation va confidence

**Y nghia**

- phu hop cho kiem tra nhanh tren terminal
- tien cho demo khong can giao dien

### Timeline du bao

`core/forecast.py` tra ve:

- `granularity`
- `horizon`
- `timeline`
- `early_warnings`
- `extremes`

**Y nghia**

- cung cap chuoi du bao phuc vu bieu do
- tao canh bao som ve DO va nhiet do

## 4. Dau ra offline/nghien cuu

### Ket qua thuc nghiem

Nam trong:

- `experiments/*.md`
- `artifacts/experiments/*`
- `docs/4t7/*.md`
- `docs/figures/*`
- `figures/*`

**Y nghia**

- dung de tong hop ket qua so sanh mo hinh
- ho tro viet bao cao, slide, va lap luan hoc thuat

### Hinh minh hoa va tai lieu trinh bay

- tep `.png` trong `figures/` va `docs/figures/`
- slide/bao cao trong `docs/4t7/`, `docs/report/`, `docs/slide/`

**Y nghia**

- phuc vu communication va bao ve de tai

## 5. Bang tom tat nhanh

| Nhom | Dau vao/Dau ra | Vi du |
| --- | --- | --- |
| Runtime input | Nguon du lieu va cau hinh can cho pipeline dang chay | MongoDB, `greenlab_export.csv`, `stations.yaml` |
| Offline input | Du lieu/train artifact de tao model va fallback | `clean_data.csv`, `.pkl`, `regional_medians.json` |
| Runtime output | Ket qua phuc vu report va app demo | payload pipeline, CLI report, forecast timeline |
| Research output | Ket qua tong hop de viet bao cao va so sanh mo hinh | `experiments/*.md`, figures, slides |

## 6. Dieu can nho khi tiep quan

- Runtime co the chay bang CSV fallback, nen demo khong phu thuoc tuyet doi vao MongoDB.
- Forecast va imputation phu thuoc vao model da huan luyen san; neu thieu file `.pkl`, pipeline se khong day du.
- Thu muc `experiments/` la noi tong hop ket qua nghien cuu; no khong dong vai tro input bat buoc cho dashboard, nhung la dau ra quan trong cho lap luan khoa hoc.
