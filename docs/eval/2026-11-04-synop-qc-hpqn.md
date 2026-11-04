# QC SYNOP 4TA tại 11 trạm HP/QN (task 1.5)

- Run: `artifacts/experiments/synop-qc-hpqn-20261104c/` (`experiments/synop_qc.py`); `-20261104` và `-b` bị thay thế (quy tắc tháng chuyển 8 lần/ngày sai).
- Tóm tắt có theo dõi git: `experiments/synop_qc_hpqn.json` (quy tắc QC gió, danh sách trạm dùng được). Phiên `wx-bias` đọc file này.
- Nguồn: `data/vn_synop/derived/synop_3h_v2.parquet` (decisions #30). Giấy phép chưa rõ: chỉ dùng trong hệ thống, **không đưa số SYNOP vào bài báo**.

## Quy tắc QC gió (chỉ gắn cờ, không sửa dữ liệu)

1. `wspd_ms > 60` → không hợp lệ (decisions #30): 72 dòng ở 11 trạm.
2. **Gai:** `wspd_ms ≥ 20` và gió lớn nhất của các lần đo hợp lệ cùng trạm trong ±6 h < một nửa giá trị (không có lần đo lân cận = 0), trừ khi có tâm bão IBTrACS trong 300 km trong ±12 h → không hợp lệ: 68 dòng (20–60 m/s, rải đều 12 tháng). Ví dụ: Bạch Long Vĩ 60 m/s tháng 3–4/2017, Bãi Cháy 60 m/s 12/02/2021, Móng Cái 60 m/s 12/07/2011 (dòng hỏng, T2m = −59), Văn Lý 53 m/s 01/05/2011.
3. Giá trị lớn trong bão (miễn trừ gai) giữ nguyên: Yagi 2024 Bãi Cháy 45, Cô Tô 34, Uông Bí 30, Phù Liễn 26 m/s; Bạch Long Vĩ 40 (Conson 2010), Hòn Dấu 33 (Sơn Tinh 2012). Gai trong bão vì vậy không bị loại.

## Giá trị 61–98 có giải mã lại được không?

Không. File 4TA đã là văn bản giải mã sẵn (tên hướng + ff m/s), không có nhóm dddff gốc (`decode_check.json` có 8 dòng gốc). Chữ số hàng chục / đơn vị không tương quan với gió lân cận (r = −0,05 / 0,01; gió lân cận trung vị 2,5 m/s). Hướng NNE (39 %) và WSW (19 %) xuất hiện nhiều bất thường so với toàn bộ (3,6 % / 0,3 %) → lỗi có hệ thống ở khâu mã hóa, nhưng không đủ để khôi phục. Hướng gió trống khi `wspd ≤ 2` m/s là quy ước (lặng / gió nhẹ), không phải thiếu.

## Lịch quan trắc

| Trạm | Nhóm | Gió hợp lệ / 8 kỳ | Giai đoạn 8 lần/ngày | TB m/s | p99 | max | Gai | >60 | Bão ≤ 300 km (≤ 100) | Có đo lúc gần nhất |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 48839 Bạch Long Vĩ | biển hở | 0,99 | cả kỳ (trừ 09/2024) | 5,8 | 16 | 40 | 17 | 13 | 99 (36) | 98 |
| 48834 Cô Tô | biển hở | 0,61 | 06/2020 → | 3,6 | 10 | 34 | 5 | 4 | 91 (33) | 90 |
| 48828 Hòn Dấu | biển hở | 0,54 | 03/2023–12/2024, 10/2025 → | 2,8 | 9 | 33 | 5 | 11 | 83 (31) | 82 |
| 48829 Văn Lý | ven bờ | 0,54 | như Hòn Dấu | 3,4 | 9 | 33 | 6 | 3 | 85 (30) | 84 |
| 48836 Cửa Ông | ven bờ | 0,61 | 06/2020 → | 2,9 | 8 | 21 | 5 | 6 | 88 (32) | 87 |
| 48838 Móng Cái | ven bờ | 0,99 | cả kỳ | 1,5 | 6 | 25 | 10 | 7 | 93 (34) | 92 |
| 48833 Bãi Cháy | kín | 1,00 | cả kỳ | 2,2 | 8 | 45 | 5 | 9 | 86 (31) | 85 |
| 48837 Tiên Yên | kín | 0,99 | cả kỳ | 1,2 | 5 | 16 | 3 | 7 | 86 (31) | 85 |
| 48/50 Quảng Hà | kín | 0,48 | không (từ 04/2001, 4 lần/ngày) | 1,3 | 5 | 22 | 5 | 5 | 88 (35) | 86 |
| 48826 Phù Liễn | kín | 1,00 | cả kỳ | 2,1 | 6 | 26 | 4 | 5 | 82 (29) | 81 |
| 48/60 Uông Bí | kín | 0,34 | không (từ 05/2008, 4 lần/ngày) | 1,6 | 5 | 30 | 3 | 2 | 80 (31) | 58 |

Trạm 4 lần/ngày chỉ có 00/06/12/18 UTC (07/13/19/01 giờ địa phương), không phải thiếu ngẫu nhiên. Mưa 6 h chỉ có ở 4 kỳ chính.

## Ghi chú phơi nhiễm

Biển hở: Bạch Long Vĩ (giữa vịnh, gió TB gấp 2–5 trạm khác), Cô Tô, Hòn Dấu. Ven bờ: Văn Lý (Nam Định, không thuộc HP/QN), Cửa Ông, Móng Cái. Kín / trong đất liền: Bãi Cháy (trong vịnh Hạ Long nhưng đo 45 m/s trong Yagi — vị trí trạm cao, không đại diện mặt nước kín), Tiên Yên, Quảng Hà, Phù Liễn, Uông Bí (gió TB 1,2–2,2 m/s, lặng 9–40 %).

## Trạm dùng được

- **Hiệu chỉnh gió bão:** mọi giai đoạn (mô hình được tính đúng tại các kỳ có đo, nên lịch 4 / 8 lần/ngày không gây lệch); chỉ số chính chỉ dùng nhóm biển hở (48839, 48834, 48828).
- **Sai số Open-Meteo 2024-01-01 → 2025-12-04:** dùng được 9 trạm (gió và T2m ≥ 80 % trên 8 kỳ): 48839, 48834, 48836, 48838, 48833, 48837, 48826, 48828 (0,82: 4 lần/ngày từ 01–09/2025), 48829 (như Hòn Dấu). Không dùng: 48/50, 48/60 (4 lần/ngày, Uông Bí thiếu ẩm / áp 80 %).
