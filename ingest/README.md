# realtime-data - Tang du lieu GreenLab

Thu muc nay la data landing zone cho du lieu quan trac thoi gian thuc GreenLab. No chua script lay du lieu, registry tram, va mot file CSV fallback nho de team co the chay lai demo `lab-realtime/` khi khong co MongoDB.

## Cac file nen biet

| File | Vai tro |
| --- | --- |
| `.env.example` | Mau bien moi truong, khong chua credential |
| `.env` | Credential MongoDB/API local, luon bi gitignore |
| `fetch_greenlab.js` | Script Node probe snapshot moi nhat tu MongoDB |
| `fetch_api.js` | CLI lay du lieu tu GreenLab API |
| `package.json` | Khai bao dependency Node |
| `greenlab_export.csv` | CSV fallback nho de chay demo offline |
| `stations.yaml` | Registry 4 tram theo serial/region |
| `thongtin tram.png` | Anh thong tin tram goc |

## Pipeline phan tich nam o dau?

Toan bo xu ly QC sensor, quy doi NH3, noi suy, phan loai, spatial extrapolation, forecast va dashboard nam o:

```text
lab-realtime/
```

## Cache raw cho realtime

`lab-realtime` uu tien GreenLab API `latest` khi lay du lieu live. Moi snapshot
duoc chuan hoa va append vao `exports/live-cache/<serial>/YYYYMMDD.jsonl`;
file nay la cache raw local, khong ghi de va khong commit. Khi khoi dong, cache
duoc ket hop voi cac export lich su trong `all_data/` va `intervals/` de du
lich su cho forecast lag features.

Thu tu fallback la: GreenLab API live -> MongoDB -> API cache stale -> CSV demo.
Runner shadow khong bao gio phat hanh forecast neu chi con cache stale hoac CSV
demo, tranh gan nham du lieu lich su thanh du lieu live.

Nhanh `lab-realtime/` import du lieu tu thu muc nay, chu yeu la `.env`, `stations.yaml`, va `greenlab_export.csv`.

Xuat CSV moi tu MongoDB:

```bash
cd realtime-data
npm install
node fetch_greenlab.js
```

## Cau hinh credential local

Tao file `.env` tu mau:

```bash
copy .env.example .env
```

Sau do dien gia tri that:

```env
MONGODB_URI=
MONGODB_DB_NAME=data
MONGODB_COLLECTION_NAME=quan_trac
TK_DHTB=
MK_DHTB=
```

Khong commit `.env`. Neu can chia se credential, hay gui qua kenh rieng cua team.

## Cach su dung CLI Fetch API

Cong cu `fetch_api.js` cho phep lay du lieu truc tiep tu cac endpoint API cua GreenLab bang Node.js.

### Yeu cau

Cai dat thu vien:

```bash
npm install
```

### Cac lenh pho bien

**1. Xem danh sach thiet bi duoc cap quyen**

```bash
node fetch_api.js devices
```

**2. Du lieu moi nhat**

```bash
node fetch_api.js latest
node fetch_api.js latest -s 06M26042802
```

**3. Du lieu lich su gan nhat**

Tham so `-p` ho tro: `1h`, `24h`, `7d`, `30d`.

```bash
node fetch_api.js history -s 06M26042802 -t COD -p 24h
```

**4. Thu thap toan bo du lieu tu dau**

Du lieu thuong rat lon, nen luu vao `exports/`. Thu muc `exports/` bi gitignore.

```bash
node fetch_api.js all -s 06M26042804 -o alldata.json
```

**5. Du lieu theo khoang ngay**

```bash
node fetch_api.js by-date -s 06M26042802 --start 2026-07-01 --end 2026-07-04
node fetch_api.js by-date -s 06M26042802 --start 2026-07-01 --end 2026-07-04 --csv
```

**6. Thong ke theo ngay**

```bash
node fetch_api.js stats -s 06M26042802 --start 2026-07-01 --end 2026-07-04
node fetch_api.js stats -s 06M26042802 --start 2026-07-01 --end 2026-07-04 --by-sensor
```

Them co `-o filename` vao cuoi bat ky lenh nao de xuat ket qua ra file thay vi in ra man hinh.

## Giao dien Streamlit crawler

```bash
streamlit run app_crawler.py
```

Yeu cau Python co `streamlit`, `pandas`, `pyyaml`.

## Chinh sach dua len Git

Duoc track:

- script fetch/crawler
- README, `.env.example`, `stations.yaml`
- `greenlab_export.csv` de demo offline
- file anh thong tin tram

Khong track:

- `.env`
- `node_modules/`
- `exports/`
- cache Python
- tai lieu van phong noi bo nhu `.docx`
