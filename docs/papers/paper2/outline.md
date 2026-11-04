# Bài báo 2 — dàn ý (bản 1, 04/11/2026)

Tài liệu nền cùng chủ đề nằm ở `docs/paper/` (`HANDOFF-paper2.md`, `2026-10-27-sota-and-plan.md`,
`2026-11-02-nh4-continuous-candidates.md`). File này chỉ là dàn ý; mọi con số lấy từ RL-76…RL-86 và RL-90,
không có kết quả mới ngoài lượt chạy lại NB1 (RL-90, mô tả).

**Quy ước trung thực (RL-80):** F1–F3 là **khám phá** (mã vào git sau khi có kết quả) → không gọi "pre-registered".
F4 là kiểm định xác nhận duy nhất trên NERRS ("đăng ký trước, kiểm chứng trong git cục bộ", chưa có mốc bên thứ ba).
F5 đăng ký trước (`b079f62`) + sửa đổi 1 trước khi chấm (`c3c54a9`). (d) là proxy bù sai số, **không phải** FSNet / TAFAS.

---

## 1. Tên bài (chọn một)

1. *No safe automatic fix: forecasting a coastal water-quality sensor through real instrument faults* (thẳng, nêu
   kết quả âm — khuyến nghị).
2. *When the probe changes, not the water: detection and mitigation of sensor faults for coastal aquaculture
   forecasting*.
3. *Masking, restarting or re-aligning? A fault-injection benchmark for forecasts from failing coastal sensors,
   calibrated on a Vietnamese cage-farm buoy*.

## 2. Luận điểm (một đoạn)

Cảm biến chất lượng nước ven biển giá rẻ hỏng theo những kiểu có thể đo được — đổi thang tức thì sau bảo dưỡng
(NH4 ÷20, ×6,7), kẹt ở 0 hoặc trần, trôi chậm — và dự báo ngắn hạn chạy trên chuỗi đó sẽ bám theo đầu dò chứ không
theo nước. Chúng tôi dựng một thư viện chèn sự cố hiệu chỉnh trên sự cố thật của một trạm nuôi lồng ở Cát Bà, chấm
bộ phát hiện nhân quả và năm họ cơ chế xử lý (bỏ qua, mặt nạ QC, khởi động lại / căn mức tại điểm đổi chế độ, căn
mức có giới hạn, thích nghi lúc chạy dạng proxy, ACI) trên hàng nghìn lần chèn vào NERRS (Mỹ) và NH4 giờ của ba trạm
MOF (Hàn Quốc), với cả ridge và mô hình nền tảng (Chronos-Bolt, Chronos-2). Kết quả chính là âm và nhất quán: căn mức
tại điểm đổi sửa được đổi thang (giảm MAE 0–24 h 43–94 %) nhưng mọi bản tự động — kể cả bản có giới hạn đăng ký trước
— gây hại trên dữ liệu không sự cố vượt ngân sách (thay đổi tự nhiên trông giống đổi thang); mặt nạ QC chỉ giúp khi
giá trị lỗi vượt dải; không cơ chế nào cứu được trôi chậm hay kẹt trong 24 h đầu; proxy thích nghi đơn giản tệ hơn
bỏ qua ở mọi loại sự cố có đổi giá trị. Khuyến nghị vận hành: phát hiện tự động + **căn mức chỉ sau xác nhận của người vận hành** (nhật ký bảo dưỡng),
và báo khoảng tin cậy không dựa trên phản hồi từ chính chuỗi lỗi.

## 3. Đóng góp (trung thực cả phần âm)

1. **Thư viện sự cố hiệu chỉnh trên sự cố thật** (F1, RL-76): 6 kiểu từ NB1, tái tạo 16/17 kiểm tra biên độ / thời
   gian; mã + test mở. Giới hạn: mỗi kiểu một quan sát, một trạm.
2. **Đánh giá bộ phát hiện nhân quả với báo động giả đã hiệu chỉnh** (F2, RL-77): đột ngột bắt chắc (vượt sham
   0,72–0,89, trễ ≤ 0,25 h với đổi thang), chậm bắt muộn (pH 13 h, bám bẩn 70 h, lên trần 37,5 h); mặt nạ từng mẫu
   chỉ che 57 % mẫu sau đổi thang, cần điểm đổi chế độ. Khám phá.
3. **Kết quả âm về cơ chế, lặp lại trên ba nguồn dữ liệu và ba mô hình** (F3 khám phá, F4 xác nhận, F5 đăng ký
   trước trên NH4 thật): không cơ chế nào đạt luật "có ích". Đây là đóng góp chính, không phải phần phụ.
4. **Lý do thất bại được định lượng**: căn mức F4 bật giả ở 13–17 % cửa sổ không sự cố, chủ yếu do Turb tự nhiên
   nhảy ×3 trong ≤ 2 mẫu và DO gần 0; tham chiếu nhiệt độ / độ mặn chỉ loại ~1/4 lần bật giả (RL-79). Trên NH4 MOF:
   (c′) hại +92…97 % ở Songdo, v2 hại 48 % ở Oido, v3 gần ngân sách nhất (+5 %) nhưng mất lợi ích 1–7 ngày (RL-86).
5. **Ca thật NB1** (mô tả, không có đáp án): căn mức đưa dự báo NH4 về mức trước bậc ở E1 / E3; bộ ba điều kiện F4
   bật đúng ở E1 / E3 NH4 trên dữ liệu phút nhưng bật nhầm ở E3 COD 0 → 21 (thoát kẹt) (RL-78, RL-79). Trên trung vị
   giờ (F5, có tham chiếu nhiệt độ) v2 bật E1 (dự báo 0,98 × mức trước bậc, trễ 1 h) nhưng bỏ sót E3 vì bậc giờ chỉ
   ×2,3 < ×3 (RL-90) → độ phân giải lấy mẫu quyết định cơ chế có thấy sự cố hay không.
6. **Khuyến nghị vận hành có cơ sở**: căn mức là *gợi ý* cho người vận hành, không tự động; loại riêng trường hợp
   thoát kẹt; không dùng ACI phản hồi từ chuỗi lỗi để báo độ tin cậy.

**Không được viết:** "(b) ít hại / gần như vô hại" (ridge +10,6 %, Bolt +14,8 % trên sham — RL-80); "thích nghi luôn
tệ hơn" mà không thêm "proxy" (RL-80); "8 loại sự cố độc lập" (E1 ≈ ÷20, E3 ≈ ×8,1 → thực chất 6 loại, RL-80);
"(b) có ích với ×8,1" mà không nói do dải cứng DO (RL-80).

## 4. Dàn ý từng mục và bằng chứng

| Mục | Nội dung | Bằng chứng (RL / artifact) |
| --- | --- | --- |
| 1. Mở đầu | Cảm biến ven biển giá rẻ, sự cố thiết bị; dự báo shadow cho nuôi lồng; câu hỏi (a)–(e) | RL-72 (bậc NH4 / TSS do thiết bị), `docs/paper/HANDOFF-paper2.md` (câu hỏi đặt 28/10, trước F1) |
| 2. Liên quan | QC cảm biến (range / stuck / step), phát hiện điểm đổi trực tuyến, test-time adaptation (FSNet, TAFAS), ACI / conformal dưới dịch chuyển, mô hình nền tảng chuỗi thời gian | `docs/paper/2026-10-27-sota-and-plan.md` §2–3 |
| 3. Dữ liệu | NB1 06M26042804 (ISE 1–3 phút, 29/05 → 14/10/2026); NERRS NCEI 33 trạm 2007–11 (đã QC) + CDMO 2021–25; MOF Hàn Quốc 3 trạm NH4 giờ, không cờ QC | RL-76, RL-77, RL-79, RL-84 (`paper2-f5step0-20261102/`) |
| 4.1 Thư viện sự cố | 6 kiểu NB1 → nguyên hàm; ánh xạ sang biến NERRS / NH4 MOF; nhiễu sau đổi thang là cộng | RL-76, `paper2-f1-20261028/` (`nb1_fault_catalog.json`, `reproduction.csv`) |
| 4.2 Bộ phát hiện | range / stuck / step 1 h / drift 24 h / cross / gap; ngưỡng ≤ 1 đợt / 30 d trên dữ liệu sạch; chỉ số = vượt sham | RL-77, `paper2-f2-20261028/` |
| 4.3 Cơ chế | (a), (b), (c), (c′), F4 v1–v3 (+ v2c ở F5), (d) proxy, (e) ACI có trễ; mô hình ridge (B4D / RL-68), Chronos-Bolt, Chronos-2 | RL-78, RL-79, RL-86 |
| 4.4 Giao thức | chấm theo giá trị sạch; MAE 0–24 h / 1–7 d, h = 1 h; sham ghép cặp; luật có ích từng bước; trạng thái đăng ký từng bước | RL-80 (bảng mốc thời gian), `preregistration.json` của F4 / F5 |
| 5.1 Phát hiện | trễ vs báo giả theo loại; NB1 ngưỡng NERRS: E1 9 phút, ngoài cửa sổ 19 đợt / 30 d | RL-77; Hình 2 |
| 5.2 NERRS (F3) | không cơ chế đạt; (c′) ÷20 −43 / −74 %, hại sham ×2,9–×6,3; (b) chỉ đạt cặp vượt dải; (d) tệ hơn | RL-78, RL-80, `paper2-f3-20261029/verdict.csv`; Hình 3 |
| 5.3 Căn mức có giới hạn (F4, xác nhận) | G1 đạt rộng, G2 trượt cả 3 mô hình; nguồn bật giả | RL-79, `paper2-f4-20261030/verdict.csv`, `triggers_nerrs.csv`; Hình 3, Bảng 3 |
| 5.4 NH4 thật (F5) | 0 / 3 trạm; Songdo đạt hai loại đổi thang nhưng hại sham; trôi / kẹt không cứu được; PI80 chỉ đạt ở gap | RL-86, `paper2-f5-20261102/verdict.csv`, `pi_secondary.csv`; Hình 3 |
| 5.5 Ca NB1 | E1 / E3 theo cơ chế; F4 bật nhầm COD thoát kẹt; F5 giờ: v2 bắt E1, bỏ sót E3 (độ lớn) | RL-78, RL-79, RL-90 (`paper2-f5nb1-20261104/`); Hình 4 |
| 6. Thảo luận | vì sao tự động thất bại (thay đổi tự nhiên giống đổi thang; tham chiếu yếu); con người trong vòng lặp; khoảng tin cậy | RL-79 (phân tích bật giả), RL-86 |
| 7. Hạn chế | xem §7 dưới | RL-76…86 mục "Hạn chế" |
| 8. Kết luận + khuyến nghị vận hành | phát hiện tự động, căn mức sau xác nhận, không ACI phản hồi từ chuỗi lỗi | RL-79, RL-86 |

## 5. Hình và bảng

Hình dựng bằng `experiments/paper2_figures.py` → `artifacts/experiments/paper2-figures-20261104b/` (PNG + PDF + CSV
số liệu từng hình, chỉ đọc artifact có sẵn).

| # | Nội dung | Nguồn |
| --- | --- | --- |
| Hình 1 | Sự cố thật NB1: NH4 E1 ÷20, NH4 E3 ×6,7, COD trần / kẹt 0, pH tụt 19/09 | lịch sử cảm biến + F1 catalog |
| Hình 2 | Trễ phát hiện trung vị vs tỉ lệ báo trên sham, theo loại (F2 NERRS, F5 MOF) | F2 `detection_summary.csv`, F5 `detection.csv` |
| Hình 3 | Lợi ích (÷20, 0–24 h, h = 1 h) vs hại trên sham, một ô mỗi thí nghiệm; vùng có ích trống | F3 / F4 / F5 `summary.csv` + `verdict.csv` (ridge) |
| Hình 4 | Ca NB1 E1 / E3: quan trắc + dự báo 1 h Chronos-2 dưới (a), (c′), v2 | F4 `nb1_trajectories.csv`; số F5-NB1 trong CSV đi kèm |
| Hình phụ | Tái tạo sự cố F1 (thật vs chèn) | `paper2-f1-20261028/fig_reproduction.png` (đã có) |
| Bảng 1 | Danh mục sự cố NB1 → tham số chèn → biến chấm | RL-76, `nb1_fault_catalog.json` |
| Bảng 2 | Bộ phát hiện: ngưỡng, báo giả sạch / 30 d, vượt sham, trễ | RL-77 `thresholds.json`, `clean_fa_summary.csv` |
| Bảng 3 | Phán quyết theo cơ chế × thí nghiệm × mô hình (đạt / trượt, hại sham) | `verdict.csv` F3 / F4 / F5 |
| Bảng 4 | Trạng thái đăng ký từng bước (khám phá / xác nhận, commit, mốc) | RL-80, RL-86 |
| Bảng phụ | PI80 sau sự cố (ACI) theo cơ chế | F3 `summary.csv`, F4 `summary.csv`, F5 `pi_secondary.csv` |

## 6. Hai phương án: có / không TAFAS và FSNet

| | **A. Không TAFAS / FSNet** (khuyến nghị) | **B. Thêm TAFAS + FSNet làm mốc** |
| --- | --- | --- |
| Cơ chế (d) | proxy bù sai số trượt mũ, gọi đúng tên; FSNet / TAFAS chỉ ở mục liên quan + hạn chế | (d1) proxy, (d2) FSNet (học trực tuyến), (d3) TAFAS (thích nghi lúc kiểm tra trên Chronos / backbone) |
| Câu được viết | "proxy thích nghi đơn giản tệ hơn bỏ qua ở mọi loại sự cố có đổi giá trị; chưa kiểm phương pháp TTA hiện đại" | "thích nghi lúc chạy (kể cả SOTA) có / không cứu được …" — kết luận mạnh hơn |
| Việc thêm | 0 | cài + kiểm tái lập 2 phương pháp; chạy lại F3 (NERRS) + F5 (MOF) với (d2) / (d3); đăng ký trước mới; ≥ 1 job torch một lúc, 2 luồng CPU |
| Chi phí ước tính | — | ~2–4 tuần làm + tính toán (FSNet cần huấn luyện trực tuyến mỗi lần chèn; TAFAS cần backbone huấn luyện riêng), rủi ro lỗi cài đặt cao |
| Nơi nộp | tạp chí môi trường / cảm biến (§8) chấp nhận kết quả âm + proxy | mở thêm khả năng hội nghị / tạp chí ML ứng dụng |
| Rủi ro phản biện | "(d) quá yếu, sao không chạy TAFAS?" → trả lời bằng phạm vi + hạn chế | ít hơn ở điểm này; thêm câu hỏi cài đặt / siêu tham số |

**Khuyến nghị: A.** Lý do: (1) luận điểm chính (căn mức tự động hại trên dữ liệu không sự cố; mặt nạ không cứu sự cố
chậm) không phụ thuộc (d); (2) cơ chế thất bại của (d) là học theo đầu dò hỏng khi phản hồi lấy từ chính chuỗi lỗi —
TAFAS / FSNet cũng chỉ thấy chuỗi lỗi, nên khó đổi hướng kết luận, nhưng chưa chạy thì không được khẳng định;
(3) chi phí 2–4 tuần lớn hơn phần còn thiếu khác (ví dụ thêm trạm NH4). **Giá phải trả:** mất cửa nộp ML (reviewer sẽ
đòi), câu về thích nghi phải hẹp ("proxy"), và mục hạn chế phải nói thẳng. Nếu chọn B: làm TAFAS trước (gắn được
lên Chronos đang dùng), FSNet sau, chỉ trên F5 Songdo + F3 ridge để giới hạn chi phí. **Chủ dự án quyết.**

## 7. Đe dọa tính hợp lệ

- **Đăng ký:** F1–F3 khám phá; F4 duy nhất xác nhận trên NERRS, giả thuyết sinh từ F3 trên cùng vị trí chèn NCEI
  (phần dữ liệu mới là sham CDMO 2021–25); mốc thời gian chỉ là git cục bộ; F4 điều kiện (i) sửa sau chạy thử 1 trạm
  trước commit (RL-79, RL-80).
- **Sự cố chèn lý tưởng hóa:** mỗi kiểu một quan sát thật, một trạm; nhiễu sau đổi thang thật là cộng, chèn là nhân
  (RL-76); trôi xuống ở F5 là tổng hợp (mượn từ bám bẩn TSS).
- **Biến lẫn với loại sự cố:** NERRS mỗi loại gắn một biến (đổi thang → DO, kẹt / bám bẩn / trần → Turb, pH → pH),
  không tách được "cơ chế kém với bám bẩn" và "kém với Turb" (RL-80).
- **Tính đôi:** E1 ≈ ÷20, E3 ≈ ×8,1 trên cùng DO → luật 6/8 F3 thực chất 6 loại (RL-80).
- **Dải cứng:** (b) giảm 97–99 % ở ×8,1 / E3 chỉ nhờ DO ~50 mg/L vượt (0; 25), không chuyển sang NB1 (RL-80).
- **Dữ liệu sạch không thật sạch:** NERRS đã QC (nền dễ hơn thực tế); MOF không có cờ QC, nền là luật lọc (RL-84,
  RL-86).
- **Cỡ mẫu:** Bolt 20 / loại ở F3; F4 FM ~14–15 vị trí giữ lại / loại; F5 Oido n = 10, Busan n = 16; sham event
  gần như không có ở F5.
- **(d) là proxy**, không phải FSNet / TAFAS (phương án A).
- **Khác thiết bị:** MOF analyzer 1 h vs NB1 ISE 1–3 phút; ba trạm cửa sông ôn đới vs nhiệt đới; NERRS Mỹ.
- **NB1 không có đáp án:** ca thật chỉ mô tả; nhiều sự cố chưa nhãn; NB1 không có độ mặn (F4 / F5 chỉ dùng nhiệt
  độ làm tham chiếu); đơn vị NH4 chờ nhà cung cấp xác nhận (RL-70).
- **Tác giả = người làm thí nghiệm**, ngưỡng có giới hạn chọn sau khi xem F3; mã và artifact có sha256 để tái lập.

## 8. Nơi nộp (2–3)

IF / Q / APC chưa kiểm (xem `docs/paper/2026-10-27-sota-and-plan.md` §4); kiểm lại trước khi nộp.

1. **Environmental Modelling & Software** (Elsevier) — đánh giá phương pháp, tái lập, mã mở; chấp nhận kết quả âm
   nếu giao thức chặt. Hợp nhất với phương án A.
2. **Sensors** (MDPI) hoặc **Water** (MDPI) — chủ đề QC / sự cố cảm biến đúng trọng tâm, nhanh; uy tín thấp hơn, phí
   mở. Phương án an toàn.
3. **Aquacultural Engineering** (Elsevier) — góc vận hành nuôi lồng, khuyến nghị người-trong-vòng-lặp; phải nhấn
   ca NB1 và hệ quả cho cảnh báo nhiều hơn phần NERRS.

(Phương án B mở thêm hướng hội nghị / workshop ML ứng dụng, ví dụ track dữ liệu thật của KDD / time-series workshop —
chỉ khi có TAFAS / FSNet.)

## 9. Việc còn thiếu trước khi viết

- Chủ dự án quyết A / B.
- Chuẩn hóa định nghĩa "hại" giữa F3 (sham xấu nhất), F4 (G2 max ba tập) và F5 (sham ngẫu nhiên) trong Bảng 3.
- Kiểm IF / APC nơi nộp; kiểm giấy phép MOF (đã ghi "không giới hạn") và NERRS cho bài.
- Đơn vị NH4 NB1 (RL-70) — chỉ ảnh hưởng mô tả ca NB1, không ảnh hưởng chấm.
