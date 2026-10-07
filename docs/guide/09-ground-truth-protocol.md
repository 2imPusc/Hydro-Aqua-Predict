# Quy trinh thu thap ground truth va hop dong du lieu

## Muc dich

Mau lab/doc lap la chuan de kiem chung noi suy. Khong duoc dung gia tri noi suy
lam nhan de tu danh gia chinh no. Bieu mau nhap mau nam tai
`templates/ground_truth_observations.csv`; chi co header, khong chua du lieu gia.

## Contract quan sat

Moi quan sat chuan hoa co cac truong bat buoc: `observation_id`, `observed_at`
(UTC), `station_serial`, `metric`, `value`, `unit`, `source_type`, `qc_status`,
`ingested_at` (UTC) va `provenance`.

- Raw: append-only, `qc_status=UNCHECKED`, khong sua/loai bo gia tri.
- QC view: tham chieu `observation_id`, them `VALID/INVALID/SUSPECT` va ly do.
- Derived/imputed: phai co `provenance=derived` hoac `imputed`, model version,
  input observation IDs va uncertainty; khong thay the raw.
- Ground truth: `source_type=manual_lab`, bat buoc co method, lab/analyst va
  ma chain-of-custody neu co.

Module `core/observations.py` hien chuyen doi dataframe rong sang raw long-form
va tao QC range view rieng. Chua tu dong ghi xuong kho de tranh ghi de du lieu
trong giai doan xac nhan schema.

## Lay mau doi chieu

1. Dong bo dong ho, ghi `observed_at` UTC; lay mau gan sensor va ghi do sau.
2. Chup/ghi lai reading sensor truoc va sau luc lay mau; luu ma station, ao va
   su kien van hanh (cho an, thay nuoc, suc khi, mua).
3. Danh nhan `sample_id`, bao quan/van chuyen theo quy trinh lab va dien day du
   bieu mau. Khong dien gia tri uoc luong vao cot `value`.
4. Lay mau lap lai co chu dich trong ngay/dem, mua/khong mua, va cac dot stress;
   khong chi lay o dieu kien binh thuong.
5. Khi co ket qua lab, doi chieu theo metric, don vi, vi tri va cua so thoi gian
   da dinh nghia truoc; ghi nhan cac cap khong match thay vi ep ghep.

## Gate truoc khi dung cho nghien cuu noi suy

- NH4 la so do goc dung de suy ra NH3. Can xac nhan don vi va co so bao cao
  (`NH4+`, `NH4-N` hay TAN) cua sensor. Hien registry ghi `mg/L` trong khi cau
  hinh quy doi mac dinh la `x0.001`; can chot dieu nay truoc khi danh gia NH3.
- Tap ground truth tach theo thoi gian va station/ao voi tap phat trien.
- Bao cao ty le mau lab khop thanh cong, do tre, do sau, thieu du lieu va phan
  bo theo che do truoc khi bao cao bat ky metric model nao.
