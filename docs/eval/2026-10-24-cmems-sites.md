# Copernicus Marine (CMEMS) tại 14 trạm lồng: độ mặn, nhiệt độ, sóng, dòng chảy (2026-10-24)

Trạng thái: lý thuyết, shadow, `used_by_alerts: False`. Mã: `experiments/cmems_sites.py` (test `tests/test_cmems_sites.py`).
Kết quả hiện hành: `artifacts/experiments/cmems-sites-20261024c/` (`summary.json`, `manifest.json` có sha256 đầu vào).
**Đã thay thế, để nguyên:** `cmems-sites-20261024/` (chạy lỗi giữa chừng, không có manifest) và `cmems-sites-20261024b/` (thiếu so sánh độ mặn giữa hai mô hình).

## Sản phẩm (theo decisions #18, luôn ghi tên mô hình)

| Dùng cho | Product / dataset (phiên bản) | Mô hình | Thời gian |
| --- | --- | --- | --- |
| Lịch sử độ mặn, nhiệt độ | `GLOBAL_MULTIYEAR_PHY_001_030` / `cmems_mod_glo_phy_my_0.083deg_P1D-m` (202311) | **GLORYS12V1** tái phân tích, 1/12°, ngày | 1993-01-01 → 2026-09-22 |
| Gần thời gian thực | `GLOBAL_ANALYSISFORECAST_PHY_001_024` / `…phy-thetao_anfc…P1D-m`, `…phy-so_anfc…P1D-m`, `…phy_anfc_0.083deg_PT1H-m` (202406) | **Mercator GLO12** phân tích/dự báo (MOI GLO12) | 2022-06 → 2026-10-22 (giờ: từ 2024-01) |
| Sóng | `GLOBAL_ANALYSISFORECAST_WAV_001_027` / `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i` (202411) | **MFWAM** toàn cầu, 1/12°, 3 giờ: VHM0, VMDR, VTPK | 2024-01 → 2026-10-22 |

**Không có sản phẩm khu vực mịn hơn cho Vịnh Bắc Bộ.** Các MFC khu vực của CMEMS chỉ phủ ATL, ARC, BAL, BS, IBI, MED, NWS. Vịnh Bắc Bộ chỉ có sản phẩm toàn cầu 1/12° (khoảng 8–9 km).

Tải: hộp lon 106,80–107,35, lat 20,55–20,95 (cả 14 trạm), độ sâu 0–10,5 m (8 tầng, 0,49–9,57 m); thêm hộp Vân Đồn (107,30–107,75; 20,85–21,20; 18 ô biển). 8 file `.nc` + manifest, **tổng 35 MB**, ghi một lần vào `data/cmems/<product>/` (sha256, dataset id, phiên bản, biến, bbox, khoảng thời gian). Tải bằng `python experiments/cmems_sites.py --download` (cần `requirements-hazards.txt`; test lõi không cần).

Ô gần nhất: 14 trạm chỉ rơi vào **8 ô** khác nhau (NB1, NB2, NB25, NB27 chung một ô; NB16, NB19, NB6 chung một ô), cách trạm 0,8–5,5 km. Số mẫu độc lập thực tế là 8, không phải 14.

## 1. Nhiệt độ so với cảm biến lồng bè (06M26042804, NB1)

Cảm biến: trung bình ngày địa phương (≥1296 dòng/ngày), 2026-05-29 đến 10-21. bias = sản phẩm − cảm biến. 101 ngày chung (kết thúc 09-22 do GLORYS12 dừng), trong đó 28 ngày ≥ 31 °C. Số ngày nóng dùng ngưỡng thô 31 °C, không chỉnh.

| Sản phẩm | n | bias °C | MAE | MAE sau trừ bias (trong mẫu) | r | POD ≥31 | FAR ≥31 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GLORYS12 MY, 0,49 m | 101 | +0,39 | 0,65 | 0,54 | 0,72 | 0,86 | 0,40 |
| GLORYS12 MY, 5,1 m | 101 | +0,27 | 0,63 | 0,58 | 0,66 | 0,68 | 0,41 |
| GLO12 phân tích, ngày, 0,49 m | 101 | +1,00 | 1,05 | 0,47 | 0,78 | 1,00 | 0,58 |
| GLO12 phân tích, giờ → ngày địa phương, 0,49 m | 101 | +1,03 | 1,09 | 0,49 | 0,75 | 1,00 | 0,59 |
| OISST v2.1 | 101 | −0,08 | 0,80 | 0,79 | 0,37 | 0,00 | – |
| Open-Meteo marine (best_match) | 101 | +0,80 | 0,91 | 0,58 | 0,68 | 0,89 | 0,50 |

Toàn bộ khoảng của GLO12 (131 ngày đến 10-22): bias +0,77, MAE 0,97, r 0,69, POD 0,90, FAR 0,59 (bảng đầy đủ: `temperature_skill.csv`).

- Hai sản phẩm CMEMS có **r cao hơn OISST** (0,72–0,78 so với 0,37) và bắt được ngày nóng, nhưng hai mô hình khác nhau 0,6 °C: GLORYS12 gần cảm biến, GLO12 ấm hơn ~1 °C. Sau khi trừ bias, GLO12 có MAE 0,47 (tốt nhất bảng), nhưng độ lệch này phải được hiệu chỉnh.
- So với kết quả `heat-skill-20261023b`: GLORYS12 MY thô (POD 0,86, FAR 0,40, CSI 0,55) hơn Open-Meteo marine thô (CSI 0,47). Cỡ mẫu nhỏ, chưa có kiểm định ngoài mẫu như `heat_skill.py`; không kết luận hơn hiệu chỉnh + nhiệt độ không khí (CSI 0,44–0,46 ở LOMO).
- Độ sâu 5 m không gần cảm biến hơn 0,49 m. Cảm biến nằm ở độ sâu chưa rõ.

## 2. Độ mặn

GLORYS12 bề mặt, 8 ô, 1993–2025. Khí hậu theo tháng cho từng trạm: `salinity_climatology.csv` (mean, p05, p50, p95, min, max). Ví dụ NB1: trung bình 32,0–32,7 (tháng 1–8), 31,5–31,8 (tháng 10–11); p05 tháng 10 là 30,5.

- **Trong cả 1993–2026, độ mặn bề mặt tại 8 ô không bao giờ dưới 28,2 psu.** Không có sự kiện < 25 hay < 28; có 117 đợt < 30 (`salinity_low_events.csv`).
- Hai sự kiện nước ngọt nhìn thấy được: sau Yagi (tháng 9/2024, thấp nhất 29,0–29,8 vào 9-21..9-27, khoảng 2 tuần sau bão, trong khi trung bình tháng 8 là 31,3–32,1) và **mùa thu 2025: 2025-08-27 → 11-18, NB16/NB19/NB6 thấp nhất 28,3 (10-08)**, thấp nhất toàn chuỗi.
- **Vân Đồn 2025-10** (báo cáo 20 psu): hộp 18 ô, trung bình 29,55 trong tháng 10 (thấp nhất 28,33), lệch −2,6 psu so với khí hậu 1993–2024 (31,6–31,7) ở đỉnh (10-09..10-13). Trung bình tháng 10 thấp hơn mọi tháng 10 trước đó (thấp nhất trước đó 30,61). **GLORYS12 thấy tín hiệu đúng thời điểm và đúng hướng (kỷ lục thấp) nhưng chỉ ~2–3 psu, không phải 20 psu.** Độ mặn 20 là nước nông ven bờ gần cửa sông, ô 8 km không phân giải được.
- **Hai mô hình bất đồng:** GLO12 phân tích cao hơn GLORYS12 khoảng 0,8–1,0 psu (r 0,81–0,89, 1575 ngày chung) và **không bao giờ thấp hơn 30 psu** từ 2022 (Vân Đồn tháng 10/2025: thấp nhất 30,0 so với 28,3). Một số ngày < 30 của GLORYS12 sau 2024 không lặp lại ở GLO12 (`salinity_models_compare.csv`). Tín hiệu nước ngọt quanh ngày 2025-10 chỉ có ở GLORYS12.

## 3. Sóng (MFWAM) trong bão Yagi (2024-09-05..09)

CMEMS VHM0 lớn nhất: **2,35–3,14 m, trung bình 2,68 m**, cùng thời điểm 2024-09-07 09:00 UTC, Tp 6–11 s. Open-Meteo marine: 2,58–2,86 m (trung bình 2,78). Open-Meteo marine thường dựa trên MFWAM (chưa kiểm tra riêng), nên hai nguồn có thể không độc lập.

| Nguồn Hs tại trạm | Trung bình m | Chênh (SPM − CMEMS) | Pearson / Spearman với CMEMS (14 trạm, 8 ô) |
| --- | --- | --- | --- |
| SPM, gió best-track + bán kính | 2,18 | −0,50 | 0,35 / 0,37 |
| SPM, Rankine thuần | 2,59 | −0,09 | 0,23 / 0,27 |
| SPM, gió ERA5 một điểm | 1,05 | −1,63 | 0,37 / 0,33 |

Ô CMEMS gần như đồng đều (2,4–3,1 m) vì không phân giải đảo che chắn; SPM có độ phân hóa lớn (0,3–5,2 m: NB15 vịnh kín 0,3–0,4 m, NB4 đến 5,2 m). Tương quan chéo thấp, và CMEMS phân bố hẹp hơn nhiều. CMEMS là **kiểm tra biên ngoài khơi**: SPM với gió ERA5 một điểm (18,9 m/s) thấp hơn CMEMS 1,6 m về trung bình, còn SPM với gió best-track gần mức CMEMS (lệch trung bình −0,5 và −0,1 m). p99 VHM0 cả giai đoạn 2024–2026 chỉ 0,7–1,25 m.

## 4. Dòng chảy (GLO12, mặt, giờ, 2024-01 → 2026-10-22)

p95 tốc độ: CMEMS 0,09–0,15 m/s (trung bình 0,114), SMOC của Open-Meteo 0,11–0,47 (trung bình 0,313). CMEMS bằng **0,42 lần** SMOC, tương quan giữa trạm 0,81 (Spearman 0,78, nhưng chỉ 8 ô). Cực đại trong Yagi 0,37–0,74 m/s (CMEMS) so với 0,47–0,89 (SMOC). GLO12 giờ có thể bỏ sót phần lớn dòng triều ven bờ; không dùng làm ngưỡng tuyệt đối cho lồng.

## Khuyến nghị

1. **Hệ số độ mặn của `disease_env`:** dùng độ lệch (anomaly) của GLORYS12 so với khí hậu tháng theo ô (ví dụ dưới p05 tháng ≥ 7 ngày), **không dùng ngưỡng tuyệt đối 25 psu** vì sản phẩm này không bao giờ xuống dưới 28. Nhãn là "dấu hiệu nước ngọt vùng rộng", không thay cảm biến độ mặn tại lồng. Không đủ cơ sở dùng GLO12 phân tích cho việc này (không thấy sự kiện 2025).
2. **Nhiệt:** nếu thêm SST, ưu tiên GLORYS12 MY (hồi cứu, bias +0,4 °C), hoặc GLO12 phân tích kèm trừ bias ~1 °C cho gần thời gian thực. Chỉ dùng ở mức "theo dõi ≥ 31 °C" như `heat-skill`; vẫn cần nhiệt độ không khí. Cảm biến hôm qua vẫn là mức sàn tốt nhất ở lead 1.
3. **Sóng/dòng:** CMEMS chỉ nên là biên ngoài khơi để đối chiếu SPM, không thay SPM theo trạm và không đặt ngưỡng. Chưa có dữ liệu sóng đo để kiểm.
4. Giữ `used_by_alerts: False`.

## Hạn chế

- Ô 1/12° (~8–9 km), 14 trạm chỉ có 8 ô, cách trạm tới 5,5 km; ô ven bờ có mặt nạ đất và trộn nước ngọt kém. Độ mặn ven bờ cửa sông (Vân Đồn 20 psu) không được phân giải.
- Chưa kiểm tra tính đồng nhất của GLORYS12 giữa phần tái phân tích và phần cuối chuỗi (2025–2026); mức "kỷ lục thấp" 2025 có thể bị ảnh hưởng. Chưa có độ mặn đo tại hiện trường để đối chiếu, chỉ có một báo cáo (độ mặn 20) cho Vân Đồn; tọa độ điểm lồng Vân Đồn không có, nên dùng hộp 18 ô.
- Nhiệt độ so với một cảm biến, một mùa (101–131 ngày); ngày địa phương của cảm biến so với ngày UTC của sản phẩm ngày. Độ sâu cảm biến chưa rõ.
- Sóng và dòng chảy chưa có ground truth, chỉ so các ước lượng với nhau. SPM và CMEMS có hạn chế khác nhau.
- Số liệu trong tài liệu lấy từ `summary.json` và các CSV của run `20261024c`; manifest liệt kê sha256 của file đầu vào.
