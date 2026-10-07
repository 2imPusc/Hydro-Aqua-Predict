
## Pilot D? b?o & C?nh b?o ?i?u ki?n nu?i (Station 06M26042804)

### Thu th?p d? li?u li?n t?c (Weather Snapshot Collector)
L?ch ch?y ?? xu?t: **M?i 1 gi?** (00:00, 01:00, 02:00... UTC). Ch?t 1 l?n m?i gi? cho pilot ?? d? ?o coverage.
L?nh:
`ash
powershell.exe -ExecutionPolicy Bypass -File experiments/run_weather_snapshot.ps1 -Station 06M26042804
`
- **Healthcheck**: 
  `ash
  python experiments/weather_snapshot_health.py --station 06M26042804
  `
  Healthcheck s? ??c file jsonl c?, b?o timestamp capture cu?i, ?? tr? v? c?c kho?ng gap. Ng??ng healthy l? tr? kh?ng qu? 2 gi?.

### Shadow Runner (??nh gi? gi? l?p)
Ch?y daemon li?n t?c m?i 60 gi?y.
`ash
python core/shadow_runner.py --station 06M26042804 --interval-seconds 60
`
