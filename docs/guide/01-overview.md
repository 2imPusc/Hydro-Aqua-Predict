# Tong quan nhanh `lab-realtime`

## Muc tieu

`lab-realtime/` tap trung vao bai toan xu ly du lieu quan trac nuoc gan-thoi-gian-thuc cho he thong GreenLab. Muc tieu khong chi la doc va hien thi du lieu sensor, ma con bo sung cac buoc suy luan de bien du lieu thieu hoac du lieu khong day du thanh thong tin co the dung cho danh gia va canh bao.

Cu the, nhanh nay giai quyet 5 bai toan chinh:

- thu nhan du lieu quan trac tu nguon realtime
- kiem tra va chuan hoa chat luong du lieu
- noi suy tham so de danh gia tram goc
- suy dien gia tri cho tram ao trong cung khu vuc
- du bao ngan han de phuc vu dashboard demo

## Pham vi hien tai

Pham vi cua nhanh `lab-realtime/` hien tap trung vao:

- demo realtime qua Streamlit
- danh gia chat luong/doi tuong nuoi dua tren bo tham so da duoc day du hoa
- local imputation tai tram goc
- spatial extrapolation sang tram ao
- forecasting ngan han theo minute, hour, day
- thuc nghiem so sanh nhieu bien the mo hinh trong thu muc `experiments/`

Nhanh nay uu tien gia tri trinh dien va nghien cuu nhanh. No chua phai entrypoint van hanh chinh cua toan repo, nhung la noi tap trung logic cho bai toan realtime.

## Cac thanh phan chinh

### `core/`

Noi chua luong xu ly chinh:

- `fetch.py`: doc raw snapshot tu MongoDB hoac CSV fallback, tao daily aggregate
- `quality.py`, `monitor.py`, `chemistry.py`: QC, rule kiem tra, suy ra NH3
- `impute.py`, `classify.py`: noi suy tham so va cham diem phu hop
- `spatial_impute.py`: suy dien tram ao
- `forecast.py`, `forecast_train.py`: du bao ngan han va tai huan luyen model
- `pipeline.py`: ghep cac thanh phan thanh luong chay cho demo
- `report.py`: giao dien dong lenh de xem bao cao nhanh

### `app/`

Chua app Streamlit demo, trong do `demo_app.py` la diem vao chinh de hien thi:

- thong tin tram goc
- ban do tram ao
- bieu do lich su va du bao
- backtest nhanh tren giao dien

### `models/` va `core/models/`

Chua cac tai nguyen model da huan luyen san:

- model imputation `.pkl`
- `feat_cols.json`
- `regional_medians.json`
- forecast bundles theo vung va theo granularity

### `experiments/`

Chua script thu nghiem va cac tep tong hop ket qua:

- so sanh mo hinh du bao
- ket qua ablation/co tuong quan
- thu nghiem ARWS, MS-ARWS, multivariate

### `docs/`

Bao gom:

- bao cao/slides hoc thuat
- hinh minh hoa
- guide dieu huong moi cho nguoi tiep quan

### `tests/`

Chua cac test cho nhung module cot loi nhu fetch, quality, impute, classify, forecast.

## Khi nao nen doc nhanh nay?

Nen bat dau bang `lab-realtime/` khi can:

- hieu luong xu ly realtime cua de tai
- chay demo tu nguon sensor/Fallback CSV
- doi chieu ket qua nghien cuu voi phan app demo
- tiep quan nhanh mot nhanh thu nghiem tach biet khoi `webapp/`
