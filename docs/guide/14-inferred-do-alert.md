# Canh bao DO noi suy — Hai Phong

`core/model_alerts.py` danh gia DO tu shadow model va tao payload
`inferred_do_alert`, tach biet voi `aquaculture_alert` tu sensor truc tiep.

- Model/OOD/QC bi chan: `BLOCKED`, khong phat alert.
- DO noi suy <=5: `WATCH`.
- DO <=4: `WARNING` sau hai chu ky lien tiep, hoac som hon neu NH3/nhiet do
  stress hay DO giam nhanh so voi prediction truoc.
- DO <=3: `HIGH_RISK` theo cung quy tac bang chung model.

Tat ca cap tren la **model-based**, khong phai DO do truc tiep va khong duoc
doi thanh Emergency sensor. Dashboard hien gia tri, cap do va disclaimer.
