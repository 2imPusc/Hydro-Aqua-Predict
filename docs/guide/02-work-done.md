# Cong viec da thuc hien trong `lab-realtime`

Tai lieu nay tom tat cong viec theo tung mang chuc nang, khong liet ke theo file don le. Muc tieu la giup nguoi doc hieu nhanh "da xay duoc gi" va "moi phan tao ra dau ra nao".

## 1. Thu thap va chuan hoa du lieu realtime

**Muc dich**

Lay du lieu sensor tu nguon van hanh thuc te, nhung van giu kha nang demo khi khong ket noi duoc MongoDB.

**Da thuc hien**

- Doc snapshot tu MongoDB theo `station_serial`.
- Bo sung che do fallback sang `data/greenlab/greenlab_export.csv`.
- Chuan hoa cot thoi gian `fetchedAt`.
- Dong bo ten bien sensor, vi du `Temp` thanh `Temperature`.

**Dau ra tao ra**

- Bang du lieu raw da tidy de dua vao pipeline.
- Metadata cho biet du lieu den tu MongoDB hay CSV fallback.

**Vi tri lien quan**

- `core/fetch.py`
- `core/config.py`

## 2. QC va bien doi NH4 -> NH3

**Muc dich**

Loai bot doc sai sensor va tao tham so NH3 can thiet cho danh gia phu hop.

**Da thuc hien**

- Loc cac gia tri ngoai dai vat ly hop ly.
- Kiem tra trang thai COD theo tung ngay.
- Tong hop du lieu theo ngay bang median de giam anh huong outlier.
- Tinh NH3 tu NH4, pH, Temperature bang cong thuc hoa hoc.

**Dau ra tao ra**

- Daily aggregate da loc range.
- Cot NH3 phuc vu classify va forecast.
- Co so de in bao cao monitor theo quy chuan.

**Vi tri lien quan**

- `core/quality.py`
- `core/monitor.py`
- `core/chemistry.py`
- `core/fetch.py`

## 3. Local imputation tai tram goc

**Muc dich**

Hoan thien bo tham so tai tram goc ngay ca khi mot so bien khong do truc tiep duoc.

**Da thuc hien**

- Xac dinh bo feature 4-bien/5-bien tuy theo tinh trang COD.
- Noi suy tham so thieu bang model da train san.
- Gan confidence va CV R2 cho cac bien duoc noi suy.
- Day du hoa bo tham so de dua vao ham cham diem phu hop.

**Dau ra tao ra**

- `measured`, `imputed`, `defaulted`
- diem WQI/suitability, nhan danh gia va canh bao kem theo

**Vi tri lien quan**

- `core/impute.py`
- `core/classify.py`
- `models/`
- `core/models/`

## 4. Spatial extrapolation sang tram ao

**Muc dich**

Tu mot tram goc co du lieu song, suy dien sang cac tram khac de tao "mang cam bien ao".

**Da thuc hien**

- Dung bo tham so da noi suy o tram goc lam vector dau vao.
- Nap cac model khong gian da huan luyen.
- Du doan mot phan bien cho tung tram dich.
- Dung median lich su theo tram lam fallback cho cac bien khong duoc mo hinh ghi de.

**Dau ra tao ra**

- bo gia tri `values` cho tung tram ao
- thong tin `imputed_by` de biet bien nao do mo hinh sinh ra, bien nao do median bo sung

**Vi tri lien quan**

- `core/spatial_impute.py`
- `core/train_spatial.py`
- du lieu lich su trong `data/haiphong/`

## 5. Forecast theo minute/hour/day

**Muc dich**

Du bao ngan han de dashboard co the hien thi xu huong tuong lai va sinh canh bao som.

**Da thuc hien**

- Chuan hoa du lieu lich su thanh frame phuc vu forecast.
- Ho tro nhieu granularity: minute, hour, day.
- Nap cac bundle forecast pretrained theo vung va bien.
- Du bao de quy cho `Temperature`, `pH`, `NH4`, `TSS`, `DO`.
- Quy doi bo du bao thanh WQI/label tren moi moc thoi gian tuong lai.

**Dau ra tao ra**

- `timeline` forecast
- `early_warnings`
- thong tin cuc tri nhu `min_do`, `max_temp`

**Vi tri lien quan**

- `core/forecast.py`
- `core/forecast_train.py`
- `core/models/forecast/`

## 6. Demo app va backtest

**Muc dich**

Trinh bay nhanh toan bo pipeline duoi dang dashboard co the tuong tac.

**Da thuc hien**

- Tao tab dashboard cho tram goc, tram ao va bieu do thoi gian.
- Hien thi ban do tram ao bang Folium.
- Cho phep doi granularity/horizon forecast ngay tren giao dien.
- Bo sung tab backtest de doi chieu du bao voi ground truth gan nhat.

**Dau ra tao ra**

- giao dien demo co the trinh bay cho hoi dong/nguoi xem
- hinh dung truc quan ve su khac nhau giua thuc te va du bao

**Vi tri lien quan**

- `app/demo_app.py`
- `app/plot_figures.py`
- `core/pipeline.py`

## 7. Thuc nghiem so sanh mo hinh

**Muc dich**

Danh gia nhieu bien the mo hinh va ghi lai ket qua de ho tro lap luan hoc thuat.

**Da thuc hien**

- tong hop ket qua all stations
- so sanh RT-ARWS, MS-ARWS, XGBoost, SNaive, Sine
- nghien cuu bien ngoai sinh/thoi tiet
- thu nghiem multivariate, selective multivariate, hyperparameter tuning

**Dau ra tao ra**

- cac bang tong hop ket qua `.md`
- hinh scatter, heatmap, PCA, sensitivity
- bao cao theo phase va slide minh hoa

**Vi tri lien quan**

- `experiments/*.md`
- `experiments/*.py`
- `docs/4t7/*.md`
- `docs/figures/`

## Tom tat nhanh

`lab-realtime/` hien da co du mot chuoi cong viec khap kin cho demo:

- nhan du lieu
- loc va bo sung tham so
- cham diem tai tram goc
- suy dien tram ao
- du bao ngan han
- trinh bay ket qua va doi chieu bang thuc nghiem

No la mot nhanh nghien cuu/demo co tinh trinh bay ro rang, khong chi la tap hop script roi rac.
