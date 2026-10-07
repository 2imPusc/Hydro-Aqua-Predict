# Ket qua noi bat va noi doc sau

Tai lieu nay khong lap lai toan bo bang so lieu da co san. Muc tieu la tom tat ket qua noi bat, chi ra cai gi dang tot, cai gi con han che, va dieu huong den cac tai lieu chi tiet co san trong `experiments/` va `docs/4t7/`.

## 1. Local imputation / phase tai tram goc

Ket qua tong hop trong `docs/4t7/report_phase_comparison.md` cho thay:

- Khi co tap du lieu du lon, bo sung bien thoi tiet/exogenous co the cai thien ro mot so tham so.
- XGBoost cho local imputation nhin chung tot hon huong MICE tuyen tinh.
- Salinity va mot so bien hoa ly co kha nang hoc tot hon cac bien sinh hoc/kim loai nang.

**Nhan xet ngan**

| Mat | Danh gia |
| --- | --- |
| Dang tot | XGBoost local imputation co gia tri ro khi du lieu du day va co feature bo tro |
| Han che | Khong phai bien nao cung hoc tot; mot so chi so co R2 thap hoac am |

**Doc chi tiet**

- [docs/4t7/report_phase_comparison.md](../4t7/report_phase_comparison.md)
- [docs/4t7/report_exogenous_features.md](../4t7/report_exogenous_features.md)

## 2. Spatial extrapolation / tram ao

Ket qua theo phase cho thay spatial extrapolation co muc do thanh cong khac nhau giua cac tram dich:

- co tram dich on dinh va tuong quan tot hon
- co tram rat kho phat xa do khac biet boi canh/thuy dong luc
- them qua nhieu bien bo tro trong tap sieu nho co nguy co overfitting

**Nhan xet ngan**

| Mat | Danh gia |
| --- | --- |
| Dang tot | Co the tao duoc mang tram ao va cham diem lai tren dashboard |
| Han che | Chat luong suy dien khong dong deu giua cac tram; phu thuoc manh vao su tuong dong voi tram goc |

**Doc chi tiet**

- [docs/4t7/report_phase_comparison.md](../4t7/report_phase_comparison.md)

## 3. Forecasting va baseline

Trong `experiments/`, da co nhieu bang tong hop de so sanh forecasting:

- `all_stations_results.md`
- `rt_arws_results.md`
- `ms_arws_results.md`
- `all_stations_lstm_results.md`
- `multivariate_results.md`

Tu nhung bang nay co the thay:

- forecasting dang duoc danh gia tren nhieu baseline, khong chi mot mo hinh don.
- XGBoost co nhung truong hop canh tranh tot, nhung khong phai luc nao cung la lua chon tot nhat.
- Cac bien nhu pH thuong on dinh hon, trong khi NH4 va TSS kho du bao hon.

**Nhan xet ngan**

| Mat | Danh gia |
| --- | --- |
| Dang tot | Co bo benchmark tuong doi day de lap luan mo hinh du bao |
| Han che | NH4, TSS van la cac bien kho; mot so huong lai ghep chua on dinh hon baseline |

**Doc chi tiet**

- [experiments/all_stations_results.md](../../experiments/all_stations_results.md)
- [experiments/rt_arws_results.md](../../experiments/rt_arws_results.md)
- [experiments/ms_arws_results.md](../../experiments/ms_arws_results.md)
- [experiments/multivariate_results.md](../../experiments/multivariate_results.md)

## 4. Exogenous features va phan tich bo tro

Nhanh realtime khong chi co ket qua du bao/cuoi cung, ma con co cac thu nghiem de giai thich vi sao mo hinh co the tot hon hoac xau di:

- phan tich bien ngoai sinh
- tuong quan dia ly/khong gian
- do nhay theo mua vu va aggregation

**Nhan xet ngan**

| Mat | Danh gia |
| --- | --- |
| Dang tot | Co tai lieu de ly giai hanh vi mo hinh, khong chi co bang diem |
| Han che | Cac ket qua mang tinh nghien cuu, can doc kem ngu canh de tranh ket luan qua muc |

**Doc chi tiet**

- [experiments/correlation_results.md](../../experiments/correlation_results.md)
- [experiments/optuna_results.md](../../experiments/optuna_results.md)
- [docs/4t7/report_exogenous_features.md](../4t7/report_exogenous_features.md)

## 5. Ket luan tong hop

Co the nhin `lab-realtime/` nhu mot nhanh da co du 3 lop ket qua:

- **ket qua ky thuat**: pipeline co the chay tu nguon du lieu den dashboard
- **ket qua mo hinh**: da co benchmark, so sanh va nhung huong du bao/noi suy cu the
- **ket qua trinh bay**: da co slide, bao cao, hinh minh hoa phuc vu bao ve/de mo

Nhung cung can nhin ro 3 gioi han:

- chat luong spatial extrapolation phu thuoc vao tram dich
- mot so bien forecast van kho
- ket qua nghien cuu va ket qua demo khong nen dong nhat hoan toan

## 6. Goi y duong doc

Neu can doc nhanh theo muc dich:

- Muon xem thong diep hoc thuat tong quat: doc `docs/4t7/*.md`
- Muon xem bang ket qua thuc nghiem truc tiep: doc `experiments/*.md`
- Muon doi chieu voi giao dien demo: doc them `docs/guide/04-how-it-works.md`
