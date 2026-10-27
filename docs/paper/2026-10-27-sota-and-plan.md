# Khảo sát SOTA và kế hoạch bài báo ISI/Scopus — 2026-10-27

**Mục đích:** chọn một hướng bài báo khoa học (tạp chí ISI/Scopus) dựa trên một phương pháp SOTA, có thể làm tốt hơn trên dữ liệu của dự án, và lập kế hoạch thực hiện.
**Phạm vi:** chỉ đọc repo + tìm web. Không chạy mô hình, không ghi vào `data/`, `artifacts/`, `runtime/`.

**Quy ước kiểm chứng** (giống `docs/eval/2026-10-25-transfer-datasets.md`):

- **V1** = đã mở trang arXiv / API arXiv / Crossref / Europe PMC hôm nay và thấy tiêu đề, tác giả, năm (và tóm tắt nếu ghi "đọc tóm tắt").
- **V2** = chỉ thấy tiêu đề + DOI qua Crossref, **chưa đọc tóm tắt**.
- **V3** = chỉ thấy qua kết quả tìm kiếm / trang bên thứ ba. **Chưa kiểm chứng.**

Các con số chỉ số ảnh hưởng (IF), hạng Q, phí APC trong mục 4 đều lấy từ trang tổng hợp bên thứ ba hoặc đoạn trích tìm kiếm (trang nhà xuất bản chặn truy cập tự động, lỗi 403). **Phải kiểm lại trên Clarivate JCR / trang tạp chí trước khi chọn nơi nộp.**

---

## 0. Trả lời ngắn

**Đề xuất:** viết bài về **dự báo nhiệt độ nước ngắn hạn (15 phút – 12 giờ) tại lồng nuôi bằng mô hình nền chuỗi thời gian có biến ngoại sinh (Chronos-2), dùng bản tin thời tiết đúng như lúc phát hành, có khoảng tin cậy conformal chịu được thay đổi chế độ**. So với một baseline mạnh mà dự án đã có (ridge + khối ngày–đêm B4D/B5D), không chỉ so với persistence.

Lý do chọn:

1. Chuỗi kết quả RL-62 → RL-66 đã cho thấy điều mà nhiều bài báo ứng dụng bỏ qua: mô hình nền zero-shot thắng ridge thường (−44…−57 % MAE ở 3–12 h), nhưng **khi ridge có thêm khối ngày–đêm nhiều ngày thì mô hình nền không còn đạt gate**. Đây là một phát hiện "baseline mạnh" có giá trị, và đặt ra câu hỏi chưa ai trả lời trên dữ liệu chất lượng nước: **mô hình nền thế hệ mới có biến ngoại sinh (Chronos-2, 10/2025) + thời tiết dự báo thật có vượt được baseline mạnh này không?**
2. Dự án có một tài sản hiếm: **chuỗi bản tin thời tiết thu đúng lúc phát hành** (H2.1, `captured_live`) song song với bản dựng lại (`reconstructed_run`, Open-Meteo Previous Runs), quan trắc thật (oracle) và bản giả (pseudo). Bài heat-load mới nhất với Chronos-2 chỉ so "thời tiết hoàn hảo" với "dự báo hồi cứu" ([Spoek và cs., arXiv:2608.20024](https://arxiv.org/abs/2608.20024), V1). Một **thang nguồn gốc bản tin** đầy đủ (không có → giả → dựng lại → thu trực tiếp → oracle) cho chất lượng nước là điểm mới rõ ràng.
3. Có giao thức đánh giá chặt (fold trượt + lockbox 14 ngày + gate #16 + DM-HLN) và sổ shadow chấm điểm thật từ 24/10 — đúng thứ reviewer đòi.
4. Chạy được trên CPU: Chronos-Bolt 0,2–0,84 s/mốc (RL-62); Chronos-2 có bản 28M tham số (`chronos-2-small`).

**Rủi ro lớn nhất:** biên độ ngày–đêm của đầu dò nhiệt tăng ~5 lần từ giữa tháng 8 (RL-57) — có thể là hiện tượng đầu dò (nắng / vị trí / bám bẩn), không phải nhiệt độ nước. Vì vậy kế hoạch đặt **NERRS nhiều trạm (công khai) làm benchmark chính**, NB1 là nghiên cứu tình huống nuôi lồng, và có bước kiểm tra chéo nhiệt độ NB1 với SST mô hình/vệ tinh.

---

## 1. Dự án đang có gì (tóm tắt từ repo)

| Tài sản | Nội dung | Nguồn trong repo |
| --- | --- | --- |
| Sensor lồng NB1 (Cát Bà, `06M26042804`) | Temp, pH, NH4, TSS, COD; 1–3 phút; 29/05 → nay (~5 tháng, 204.861 dòng tới 24/10) | `sensor-history-20261024`, RL-02, RL-54 |
| Vấn đề QC đã ghi | pH trôi từ 19/09 (RL-13, RL-54); NH4/TSS bậc thiết bị 31/07 (RL-72) và 16/09; COD hỏng; biên độ nhiệt ngày–đêm ×5 từ giữa 08 (RL-57); 16 ngày thiếu một phần | AGENTS.md, RL-57, RL-72 |
| Benchmark | fold trượt 5 × 7 ngày + lockbox 14 ngày; gate #16 (≥ 4/5 fold thắng + DM-HLN lockbox p < 0,05); chống rò rỉ thời gian bằng assert | `forecast_sensor_v2.py`, `forecast_gate16_report.py`, decisions #16 |
| Kết quả nhiệt độ | MAE lockbox 12 h: ridge B4 1,453 → B4D 0,579 °C; Chronos-Bolt base 0,630; TimesFM 2.5 0,630; persistence ~2,4 | RL-62, RL-66 |
| Thời tiết | B5 (bản dựng lại) giảm thêm 6,5–11,5 % MAE ở 3–12 h so với B4 (RL-54); trên nền B4D chỉ còn −8,7 % ở 6 h (RL-66). Thu bản tin trực tiếp mỗi giờ (2 nguồn), đủ 90 % sớm nhất ~09/12/2026 (RL-59) | RL-08, RL-54, RL-59, RL-66 |
| Học chuyển giao | NERRS 33 trạm: chỉ giúp khi lệch mùa, ngang Chronos zero-shot (RL-68); nội suy chéo chỉ số: 0/5 đích có lợi (RL-67) | RL-67, RL-68 |
| Khoảng tin cậy | split / ACI / ACI-scaled / aci_amp (chuẩn hóa theo biên độ 24 h): aci_amp đạt PI80 18/18 cấu hình (gần in-sample) | RL-09, RL-19 |
| Shadow | dự báo phát mỗi phút từ 24/10, chấm điểm tự động; gate 28 ngày ~21/11 | RL-55 |
| Dữ liệu nước ngoài trên đĩa | NERRS 8 khu (2007–2011, 15 phút), Chesapeake (cấm phân phối lại dữ liệu thô), Texas TWDB, USGS SF Bay, IRLON, HK EPD (tháng) | `data/foreign/`, RL-20…RL-28 |
| Sự kiện / ground truth | nhật ký sự kiện (0 sự kiện tại 24/10); DO < 5 chưa từng thấy trong dữ liệu VN | RL-56, RL-67 |

**Hệ quả cho việc chọn đề tài:**

- Chỉ **nhiệt độ** là tín hiệu đủ tin để làm kết quả chính. pH, NH4, TSS hiện là "tín hiệu đầu dò" (RL-54, RL-72) — chỉ dùng làm phụ lục hoặc làm ví dụ cho bài toán thay đổi chế độ.
- **Nội suy DO/độ mặn** khó làm bài chính: transfer âm (RL-67), không có sự kiện DO thấp, độ mặn HP là GLORYS.

---

## 2. Khảo sát SOTA 2023–2026

### 2.1 (a) Dự báo chuỗi thời gian ngắn hạn

**Mô hình nền (foundation models, zero-shot):**

| Mô hình | Bài báo | Năm / nơi | Biến ngoại sinh | Dùng CPU được? | Giấy phép trọng số | Kiểm chứng |
| --- | --- | --- | --- | --- | --- | --- |
| Chronos / Chronos-Bolt | [Ansari và cs., arXiv:2403.07815](https://arxiv.org/abs/2403.07815) "Chronos: Learning the Language of Time Series" | 2024 (TMLR theo repo chính thức; V3) | không | có (RL-62: 0,2–0,84 s/mốc) | Apache-2.0 (V3) | V1 |
| **Chronos-2** | [Ansari và cs., arXiv:2510.15821](https://arxiv.org/abs/2510.15821) "Chronos-2: From Univariate to Universal Forecasting" | 10/2025 | **có**: covariate quá khứ và covariate biết trước tương lai (qua mặt nạ), group attention; 21 phân vị (0,01–0,99); ngữ cảnh tới 8.192; 120M tham số, bản small 28M | có (README: CPU hoặc GPU; tốc độ CPU **chưa đo**) | Apache-2.0 ([HF README](https://huggingface.co/autogluon/chronos-2/blob/main/README.md), V1) | V1 (đọc HTML) |
| ChronosX | [Pineda Arango và cs., arXiv:2503.12107](https://arxiv.org/abs/2503.12107) — khối mô-đun tiêm covariate vào mô hình đã học trước | AISTATS 2025 | có (cần huấn luyện adapter) | có | — | V1 |
| TimesFM | [Das và cs., arXiv:2310.10688](https://arxiv.org/abs/2310.10688) | ICML 2024 (V3) | 2.5: covariate qua XReg (10/2025); 3.0 (08/2026): covariate gốc | có (RL-62: 1,65 s/mốc) | mã Apache-2.0; **trọng số 3.0 chỉ phi thương mại** ([GitHub](https://github.com/google-research/timesfm), V1) | V1 |
| Moirai / Moirai 2.0 | [Woo và cs., arXiv:2402.02592](https://arxiv.org/abs/2402.02592); [Liu và cs., arXiv:2511.11698](https://arxiv.org/abs/2511.11698) | 2024; 11/2025 | Moirai 1: có; 2.0: decoder-only, phân vị | có (2.0 nhỏ hơn 30×) | chưa kiểm | V1 |
| TiRex (xLSTM) | [Auer và cs., arXiv:2505.23719](https://arxiv.org/abs/2505.23719) | NeurIPS 2025 | không | có (35M tham số) | chưa kiểm | V1 |
| Toto / Toto 2.0 | [Cohen và cs., arXiv:2407.07874](https://arxiv.org/abs/2407.07874), [arXiv:2505.14766](https://arxiv.org/abs/2505.14766); Toto 2.0 [arXiv:2605.20119](https://arxiv.org/abs/2605.20119) | 2024–2026 | — | chưa rõ | chưa kiểm | V1 (chỉ tiêu đề) |
| Sundial | [Liu và cs., arXiv:2502.00816](https://arxiv.org/abs/2502.00816) | 2025 | không | chưa rõ | chưa kiểm | V1 (chỉ tiêu đề) |
| TabPFN-TS | [Hoo và cs., arXiv:2501.02945](https://arxiv.org/abs/2501.02945) — TabPFN v2 ([Hollmann và cs., Nature 2025, doi:10.1038/s41586-024-08328-6](https://doi.org/10.1038/s41586-024-08328-6)) cho chuỗi thời gian | 2025 | có (đặc trưng dạng bảng) | có (chậm hơn) | chưa kiểm | V1 |

**Bộ benchmark chung:** [GIFT-Eval, arXiv:2410.10393](https://arxiv.org/abs/2410.10393) và [fev-bench, arXiv:2509.26468](https://arxiv.org/abs/2509.26468) (V1). Theo bài Chronos-2, trên 42 tác vụ có covariate của fev-bench, tỷ lệ thắng trung bình: Chronos-2 90,7 %, TiRex 80,8 %, TimesFM-2.5 75,9 %, Toto-1.0 66,6 % (số của chính tác giả Chronos-2; V1, đọc HTML).

**Mô hình học sâu có huấn luyện:** PatchTST ([arXiv:2211.14730](https://arxiv.org/abs/2211.14730)), iTransformer ([arXiv:2310.06625](https://arxiv.org/abs/2310.06625)), TimeMixer ([arXiv:2405.14616](https://arxiv.org/abs/2405.14616)), TSMixer ([arXiv:2303.06053](https://arxiv.org/abs/2303.06053)), xLSTMTime ([arXiv:2407.10240](https://arxiv.org/abs/2407.10240)), KAN cho chuỗi thời gian (ví dụ [arXiv:2406.02486](https://arxiv.org/abs/2406.02486), [arXiv:2510.16940](https://arxiv.org/abs/2510.16940)) — tất cả V1 (tiêu đề). Với 5 tháng dữ liệu một trạm, các mô hình này dễ quá khớp; dự án đã thấy MLP ~20k tham số không hơn ridge B4D (RL-68). Chỉ nên đưa một đại diện (PatchTST hoặc TSMixer) làm baseline phụ.

**Ứng dụng nước / thủy văn / nuôi trồng (gần nhất với ta):**

| Bài | Nội dung chính | Kiểm chứng |
| --- | --- | --- |
| [Rangaraj và cs., arXiv:2505.01415](https://arxiv.org/abs/2505.01415) — mực nước Everglades | 12 mô hình chuyên biệt + 5 mô hình nền; Chronos vượt trội, các mô hình nền khác yếu | V1 (tóm tắt) |
| [Rangaraj và cs., arXiv:2508.04888](https://arxiv.org/abs/2508.04888) — retrieval-augmented FM, Everglades | ghép đoạn lịch sử tương tự vào ngữ cảnh → lợi lớn hơn ở sự kiện cực đoan | V1 (tóm tắt) |
| [Zheng và cs., Water Research X 2026, doi:10.1016/j.wroa.2025.100469](https://doi.org/10.1016/j.wroa.2025.100469) — Chronos cho dự báo nitơ khi thiếu dữ liệu | chỉ thấy tiêu đề / DOI | **V2** (chưa đọc tóm tắt) |
| [Hoz và cs., Water Research 2026, doi:10.1016/j.watres.2025.124931](https://doi.org/10.1016/j.watres.2025.124931) — DO ao xử lý nước thải nông thôn | mô hình nền transformer tinh chỉnh theo mùa, 24 h; SMAPE < 7 % so với 16–25 % (LSTM, TFT) và 38–46 % (SVR, XGBoost); SHAP | V1 (tóm tắt Europe PMC) |
| [Neog và cs., arXiv:2606.11268](https://arxiv.org/abs/2606.11268) — LakeFM (KDD 2026) | mô hình nền cho hồ, chuỗi nhiều độ sâu không đều; cạnh tranh / hơn Chronos, MOMENT | V1 (tóm tắt) |
| [Spoek và cs., arXiv:2608.20024](https://arxiv.org/abs/2608.20024) — Chronos-2 vs TabPFN-TS, tải nhiệt sưởi khu vực | benchmark chính giả định **thời tiết hoàn hảo**; phân tích độ nhạy với dự báo hồi cứu; Chronos-2 tốt nhất (CVRMSE 12,48 % so với 13,07 %) | V1 (tóm tắt) |
| [Dabrowski và cs., PAKDD 2022, doi:10.1007/978-3-031-05981-0_3](https://doi.org/10.1007/978-3-031-05981-0_3) ([arXiv:2205.06359](https://arxiv.org/abs/2205.06359)) — trại tôm | Transformer/Attention đưa **bản tin thời tiết vào decoder**; DO 24 h MAPE 12 %; chạy thật 2 năm | V1 (tóm tắt) |
| [Zwart và cs., JAWRA 2023, doi:10.1111/1752-1688.13093](https://doi.org/10.1111/1752-1688.13093) — nhiệt độ sông Delaware | học sâu có hướng dẫn quá trình + đồng hóa dữ liệu, dự báo 7 ngày xác suất, chạy thời gian thực 2021, dùng dự báo khí tượng; RMSE 1,1–1,4 °C (1 ngày) | V1 (Crossref) + nội dung từ trang USGS (V3) |
| [Read và cs., Water Resources Research 2019, doi:10.1029/2019WR024922](https://doi.org/10.1029/2019WR024922) — process-guided deep learning nhiệt độ hồ | gốc của hướng "lai vật lý–ML" cho nhiệt độ nước | V2 |
| [Nearing và cs., Nature 2024, doi:10.1038/s41586-024-07145-1](https://doi.org/10.1038/s41586-024-07145-1) — lũ toàn cầu | LSTM dùng dự báo khí tượng làm đầu vào ở quy mô vận hành | V2 |
| Hu và cs., Sensors 2019 — LSTM cho pH và nhiệt độ nuôi biển lồng ([PMC6470961](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6470961/)) | ví dụ điển hình bài "LSTM + tương quan" ở nuôi biển; báo "độ chính xác 98,97 %" (thước đo yếu) | V3 |

**Nhận xét khoảng trống (a):**

1. Bài ứng dụng nuôi trồng phần lớn so với LSTM/GRU/SVR và persistence, **hiếm khi có baseline mạnh hay kiểm định thống kê** (DM). Một bài có gate rõ và baseline mạnh là khác biệt.
2. Chưa thấy bài nào dùng **Chronos-2 với covariate thời tiết** cho chất lượng nước ven biển / lồng nuôi (tìm kiếm 27/10; V3 — "không thấy" không có nghĩa là "không có").
3. Gần như mọi bài dùng **thời tiết quan trắc (oracle) hoặc reanalysis** làm "dự báo". Open-Meteo Historical Forecast API cũng là chuỗi **ghép giờ đầu của các lượt chạy** — gần như quan trắc, không phải bản tin đúng lúc phát hành ([tài liệu Open-Meteo](https://open-meteo.com/en/docs/historical-forecast-api), V1). Bản tin theo độ trễ (Previous Runs API) chỉ có từ 01/2024.

### 2.2 (b) Nội suy / cảm biến mềm (soft sensing)

| Phương pháp | Bài | Ghi chú | Kiểm chứng |
| --- | --- | --- | --- |
| BRITS | [Cao và cs., arXiv:1805.10572](https://arxiv.org/abs/1805.10572) | RNN hai chiều, nội suy chuỗi | V1 |
| SAITS | [Du và cs., arXiv:2202.08516](https://arxiv.org/abs/2202.08516) | self-attention, nội suy | V1 |
| CSDI | [Tashiro và cs., arXiv:2107.03502](https://arxiv.org/abs/2107.03502) | diffusion có điều kiện, nội suy xác suất | V1 |
| ImputeFormer | [Nie và cs., arXiv:2312.01728](https://arxiv.org/abs/2312.01728) | transformer hạng thấp, không–thời gian | V1 |
| TabPFN v2 | [Hollmann và cs., Nature 2025](https://doi.org/10.1038/s41586-024-08328-6) | mô hình nền dạng bảng, mạnh khi ít mẫu (≤ 10k) | V1 (Crossref) |
| HopCPT / dữ liệu cho bất định | [Auer và cs., HESS 2024, doi:10.5194/hess-28-4099-2024](https://doi.org/10.5194/hess-28-4099-2024) | xem 2.3 | V1 |
| Soft sensor DO từ T, pH, độ mặn | ví dụ GPR tốt nhất ở Koh Yor (Thái Lan) — [semarakilmu](https://semarakilmu.com.my/journals/index.php/applied_sciences_eng_tech/article/view/10550) | chất lượng tạp chí thấp, chỉ minh họa | V3 |

**Nhận xét (b):** các mô hình BRITS/SAITS/CSDI giả định **chuỗi đều, nhiều biến cùng đo liên tục** — ta không có (đích DO/độ mặn chỉ có ở mẫu tháng của tỉnh). Bài toán của ta thực chất là **hồi quy bảng ít mẫu, lệch miền** (cảm biến liên tục → mẫu tháng), nơi TabPFN v2 là SOTA hợp lý. Nhưng RL-67 cho thấy nút thắt là **thông tin của 4 đầu vào**, không phải mô hình; không có DO < 5. Đề tài (b) chỉ khả thi dạng "kết quả âm có kiểm soát" (xem ứng viên 3).

### 2.3 (c) Khoảng tin cậy conformal cho chuỗi thời gian

| Phương pháp | Bài | Ý chính | Kiểm chứng |
| --- | --- | --- | --- |
| ACI | [Gibbs & Candès, arXiv:2106.00170](https://arxiv.org/abs/2106.00170) | cập nhật α trực tuyến khi phân phối trôi | V1 |
| AgACI | [Zaffran và cs., arXiv:2202.07282](https://arxiv.org/abs/2202.07282) (ICML 2022) | gộp nhiều γ, bỏ chọn γ thủ công | V1 |
| EnbPI | [Xu & Xie, arXiv:2010.09107](https://arxiv.org/abs/2010.09107) | bootstrap ensemble, không cần trao đổi được | V1 |
| SPCI | [Xu & Xie, arXiv:2212.03463](https://arxiv.org/abs/2212.03463) | hồi quy phân vị trên phần dư tuần tự | V1 |
| Conformal PID | [Angelopoulos và cs., arXiv:2307.16895](https://arxiv.org/abs/2307.16895) | điều khiển P-I-D + "scorecaster" | V1 |
| Bellman CI | [Yang và cs., arXiv:2402.05203](https://arxiv.org/abs/2402.05203) | tối ưu nhiều bước của độ rộng | V1 (tiêu đề) |
| HopCPT | [Auer và cs., NeurIPS 2023, doi:10.52202/075280-2444](https://doi.org/10.52202/075280-2444); ứng dụng thủy văn [HESS 2024](https://doi.org/10.5194/hess-28-4099-2024) | tìm các bước quá khứ cùng "chế độ sai số"; cập nhật dữ liệu mới giảm ~50 % hụt độ phủ | V1 (tóm tắt HESS) |
| FM + conformal | [Achour và cs., arXiv:2507.08858](https://arxiv.org/abs/2507.08858) | khi ít dữ liệu, khoảng conformal từ mô hình nền ổn định hơn (dành nhiều dữ liệu cho hiệu chỉnh) | V1 (tóm tắt) |

**Khoảng trống (c) gắn với ta:** chân trời h phút có **phản hồi trễ h phút** — ACI γ cố định suy biến từ 60 phút (RL-09). Dự án đã có lời giải riêng (aci_amp, chuẩn hóa theo biên độ 24 h; RL-19). So sánh: (i) phân vị gốc của Chronos-2, (ii) Chronos-2 + conformal hóa (CQR kiểu ACI/AgACI/PID có trễ), (iii) ridge + aci_amp, dưới thay đổi chế độ biên độ — là đóng góp thứ ba có giá trị cho bài.

### 2.4 Dự báo khi cảm biến trôi / đổi chế độ

| Phương pháp | Bài | Kiểm chứng |
| --- | --- | --- |
| FSNet (học trực tuyến nhanh–chậm) | [Pham và cs., arXiv:2202.11672](https://arxiv.org/abs/2202.11672) | V1 |
| TAFAS (test-time adaptation) | [Kim và cs., arXiv:2501.04970](https://arxiv.org/abs/2501.04970) | V1 (tiêu đề) |
| PETSA (TTA tiết kiệm tham số) | [Medeiros và cs., arXiv:2506.23424](https://arxiv.org/abs/2506.23424) | V1 (tiêu đề) |
| Bám bẩn/trôi đầu dò: phát hiện bằng VAE trên BGC-Argo | [EGUsphere 2026-4153](https://egusphere.copernicus.org/preprints/2026/egusphere-2026-4153/) | V3 |

Hầu hết TTA được đánh giá trên ETT/Weather/ECL với trôi phân phối "tự nhiên". **Lỗi thiết bị có thật và được ghi nhận** (bậc ×1/20, trôi pH chậm, kẹt về 0) hầu như không có trong benchmark — NB1 có cả ba (RL-13, RL-72, AGENTS.md).

---

## 3. Ba ứng viên đề tài

| | **Ứng viên 1 (đề xuất)** | Ứng viên 2 | Ứng viên 3 |
| --- | --- | --- | --- |
| Tên (nháp) | *Do covariate-aware time-series foundation models beat a strong diurnal baseline? Short-term water-temperature forecasting at an aquaculture cage with as-issued weather forecasts and regime-robust conformal intervals* | *Forecasting through instrument faults: QC-aware context masking for foundation and online forecasters on coastal water-quality sensors* | *Can cheap sensors predict DO and salinity? A pre-registered transfer and tabular-foundation-model study for coastal cage aquaculture* |
| Câu hỏi nghiên cứu | (Q1) Chronos-2 + thời tiết có vượt B5D (ridge + ngày–đêm + cùng thời tiết) ở 3–12 h không? (Q2) Lợi ích của thời tiết thay đổi thế nào theo nguồn gốc bản tin (không → giả → dựng lại → trực tiếp → oracle)? (Q3) Khoảng nào giữ độ phủ danh định qua thay đổi chế độ biên độ? | Khi có bậc / trôi / kẹt đầu dò, chiến lược nào (không làm gì, mặt nạ QC, cắt ngữ cảnh tại điểm đổi, TTA, ACI) phục hồi sai số và độ phủ nhanh nhất? | Với 4 đầu vào cảm biến (T, pH, TAN, TSS), nội suy DO/độ mặn có thắng khí hậu tháng không, và học trước HK EPD / Đài Loan OCA có giúp không? |
| SOTA baseline | Chronos-2, Chronos-Bolt, TimesFM 2.5 (XReg), TiRex, Moirai 2.0, TabPFN-TS; ACI/AgACI/conformal PID | Chronos-Bolt/2, TiRex; FSNet, TAFAS; ACI, conformal PID | TabPFN v2, XGBoost, GP; (BRITS/SAITS không hợp với dữ liệu tháng) |
| Nâng cấp đề xuất | (1) Chronos-2 nhận thời tiết dạng covariate biết trước + triều thiên văn; (2) **dự báo phần dị thường ngày–đêm**: trừ biên dạng 7 ngày trước khi đưa vào mô hình, cộng lại sau (kết hợp phát hiện RL-62/RL-66 với FM); (3) conformal hóa phân vị FM bằng điểm chuẩn hóa biên độ (aci_amp) + ACI có trễ | Mặt nạ QC (đánh dấu thiếu thay vì giá trị lỗi) + đặt lại ngữ cảnh tại điểm đổi chế độ cho FM; ACI có trễ để phục hồi độ phủ; **benchmark tiêm lỗi thực tế** (dạng lỗi lấy từ NB1) vào NERRS | Đầu vào TAN đúng cơ sở (RL-69), chia bỏ trạm/mùa, TabPFN v2 |
| Lợi ích kỳ vọng (giả thuyết, chưa đo) | ≥ 5 % MAE so với B5D ở 6–12 h; PI80 trong [0,75; 0,85] ở cả hai chế độ biên độ. Nếu không đạt: vẫn là kết quả "baseline mạnh đủ dùng" có giá trị thực hành | giảm sai số sau sự kiện lỗi ≥ 30 % so với "không làm gì"; thời gian phục hồi độ phủ < 24 h | khả năng thấp; RL-67 đã âm |
| Cách chứng minh | gate #16 + DM-HLN trên NB1; trên NERRS: gộp theo trạm (tỷ lệ trạm thắng + kiểm định dấu Wilcoxon + DM từng trạm có hiệu chỉnh Holm); ablation từng thành phần; CRPS, độ phủ, Winkler | tiêm lỗi có kiểm soát (biết thời điểm, độ lớn) → đo chính xác; NB1 là ví dụ thực | luật đặt trước như RL-67 |
| Dữ liệu công khai cho tái lập | NERRS (NOAA, công khai) 33 trạm 2007–2011; tùy chọn NERRS 2024–2025 (CDMO, đăng ký miễn phí) để có Previous Runs | NERRS / IRLON công khai | HK EPD, Đài Loan OCA (mở) |
| Rủi ro | một đầu dò lồng; biên độ ngày–đêm có thể do đầu dò (RL-57); bản tin trực tiếp ngắn; mùa đông chưa có | nhãn lỗi trên NB1 chưa được GreenLab xác nhận; nhiều chiến lược → nguy cơ "dò lockbox" | DO < 5 không có; độ mặn HP là GLORYS; kết quả đã âm |
| Giảm rủi ro | NERRS làm benchmark chính; kiểm tra chéo NB1 với SST mô hình; tách kết quả theo chế độ biên độ; chạy lại khi có mùa đông | dùng tiêm lỗi làm chính; đăng ký trước | viết thành bài kết quả âm |
| Tạp chí hợp | Environmental Modelling & Software; Ecological Informatics; Aquacultural Engineering; Computers and Electronics in Agriculture | Sensors; Water; Environmental Modelling & Software | Ecological Informatics; Water; Aquaculture Reports |
| Độ mới | **cao** (covariate FM + thang nguồn gốc bản tin + conformal dưới đổi chế độ, trên nuôi lồng) | trung bình–cao | thấp–trung bình |
| Khả thi với CPU, 3–4 tháng | **cao** (đa số mã đã có) | trung bình | cao |

**Xếp hạng:** 1 > 2 > 3. Ứng viên 2 có thể thành bài thứ hai (dùng lại hạ tầng của bài 1).

---

## 4. Tạp chí mục tiêu

Mọi số liệu IF / Q / APC dưới đây **chưa kiểm chứng với Clarivate hoặc nhà xuất bản** (lấy từ đoạn trích tìm kiếm / trang tổng hợp bên thứ ba như journalmetrics.org; một số trang ghi "IF 2025" và "IF 2026" lẫn lộn). "Lai (hybrid)" = có thể đăng miễn phí theo hình thức thường, trả APC nếu muốn mở.

| Tạp chí | NXB | IF / Q (chưa kiểm) | Hình thức, APC (chưa kiểm) | Độ dài thường gặp | Phù hợp ứng viên 1 | Phù hợp sinh viên lần đầu |
| --- | --- | --- | --- | --- | --- | --- |
| **Environmental Modelling & Software** | Elsevier | ~4,6; Q1 (V3) | lai; APC mở ~3.400 USD (V3) | 8.000–12.000 từ | **rất hợp** (đánh giá mô hình, tái lập, mã mở) | trung bình — khắt khe về tái lập, nhưng giao thức của ta mạnh |
| **Ecological Informatics** | Elsevier | ~8,5; Q1 (V3, nghi ngờ cao) | **cần kiểm tra** có còn lai hay đã chuyển mở hoàn toàn | 8.000–10.000 | hợp | trung bình |
| **Aquacultural Engineering** | Elsevier | chưa có số; Q1–Q2 theo SJR (V3) | lai | 6.000–9.000 | hợp (nuôi trồng + kỹ thuật) | **tốt** — chủ đề trúng, phạm vi hẹp |
| **Computers and Electronics in Agriculture** | Elsevier | ~8,9; Q1 (V3) | lai | 8.000–10.000 | hợp | khó — tỷ lệ từ chối cao |
| Smart Agricultural Technology | Elsevier | ~5,7; Q1 (V3) | mở hoàn toàn, APC chưa rõ | 6.000–8.000 | hợp | tốt |
| Aquaculture Reports | Elsevier | ~3,7; Q1 (V3) | mở hoàn toàn, ~1.800 USD (V3) | 5.000–8.000 | hợp (phần nuôi trồng) | tốt |
| Water | MDPI | ~3 (V3, số trong trích dẫn không nhất quán) | mở, 2.600 CHF (V3) | 6.000–10.000 | hợp | tốt, nhanh; uy tín thấp hơn |
| Sensors | MDPI | ~4,0 (V3) | mở, 2.600 CHF (V3) | 6.000–10.000 | hợp hơn với ứng viên 2 | tốt, nhanh |

**Khuyến nghị nơi nộp cho ứng viên 1:** thứ tự thử **Environmental Modelling & Software → Aquacultural Engineering → Ecological Informatics**; phương án an toàn (nhanh, phí) là Water / Sensors. Cần kiểm lại IF/APC và chính sách của trường (một số trường VN chỉ tính SCIE Q1–Q2 hoặc danh mục HĐGSNN) trước khi nộp.

---

## 5. Kế hoạch chi tiết cho đề tài đề xuất (ứng viên 1)

### 5.1 Câu hỏi và giả thuyết (đăng ký trước)

- **H1 (độ chính xác):** Chronos-2 + thời tiết dựng lại (`reconstructed_run`) + triều có MAE thấp hơn B5D_nopH ở 3, 6, 12 h trên NB1 (gate #16 so với B5D_nopH).
- **H2 (thời tiết):** trong Chronos-2, thời tiết làm giảm MAE so với chính Chronos-2 không thời tiết ở 6–12 h (DM-HLN p < 0,05). Thang nguồn gốc: lợi ích phải xếp **oracle ≥ dựng lại ≈ trực tiếp > giả ≈ không** — nếu "giả" ≈ "dựng lại" thì lợi ích thực chất là thông tin quan trắc gần, không phải kỹ năng dự báo.
- **H3 (khoảng tin cậy):** PI80 của Chronos-2 conformal hóa (điểm chuẩn hóa biên độ + ACI có trễ) nằm trong [0,75; 0,85] ở cả giai đoạn biên độ nhỏ (trước 15/08) và lớn (sau 20/08), với Winkler không kém hơn ridge + aci_amp quá 5 %.
- **H4 (tổng quát hóa):** trên NERRS (33 trạm), phần "không thời tiết" của H1 và H3 lặp lại ở ≥ 60 % số trạm (kiểm định dấu Wilcoxon p < 0,05 trên MAE theo trạm).

Mọi ngưỡng, fold, lockbox, danh sách mô hình và cấu hình (độ dài ngữ cảnh, bước mốc) ghi trong `preregistration.json` và commit **trước khi chạy** (như RL-66, RL-57).

### 5.2 Giai đoạn (bắt đầu 27/10/2026)

| Giai đoạn | Tuần | Thời gian | Việc | Sản phẩm |
| --- | --- | --- | --- | --- |
| P0 Chuẩn bị | 1–2 | 27/10 – 09/11 | đăng ký trước; thêm adapter Chronos-2 (+ small) vào `foundation_zero_shot.py` (venv `.venv-fm`); đo tốc độ CPU/mốc; kiểm tra chéo nhiệt độ NB1 với SST Open-Meteo marine / CMEMS (biên độ ngày–đêm, độ lệch) ; gửi câu hỏi đầu dò nhiệt cho GreenLab (RL-57) | `preregistration.json`; ghi chú tốc độ; mục RL mới về đầu dò nhiệt |
| P1 Benchmark NERRS | 3–5 | 10/11 – 30/11 | 33 trạm NERRS 2007–2011 (không thời tiết): persistence, diurnal-anomaly-7d, ridge B4/B4D, PatchTST hoặc TSMixer (1 đại diện), Chronos-Bolt, Chronos-2, TiRex, TimesFM 2.5, Moirai 2.0; cùng mốc, cùng chân trời; khoảng: phân vị gốc, conformal hóa, aci_amp | bảng NERRS; artifact `paper-nerrs-bench-*` |
| P2 NB1 + thời tiết | 5–7 | 24/11 – 14/12 | NB1: Chronos-2 ± thời tiết (Previous Runs) ± triều; thang nguồn gốc (không / giả / dựng lại / oracle); ablation dị thường ngày–đêm; khoảng tin cậy theo chế độ biên độ | bảng NB1; `paper-nb1-weather-*` |
| P3 Bản tin trực tiếp + mùa lạnh | 8–11 | 15/12 – 11/01/2027 | khi độ phủ `captured_live` ≥ 90 % (sớm nhất ~09/12): chạy lại H2 với bản tin trực tiếp; phép thử lệch mùa với tháng 11–12 (mùa lạnh đầu tiên); so sánh với sổ shadow (nếu chủ dự án cho chạy Chronos ở shadow) | bảng bậc "trực tiếp"; bảng lệch mùa |
| P4 Viết | 11–15 | 12/01 – 15/02/2027 | hình, bảng, bản thảo, kiểm tra tái lập từ tag repo; thầy hướng dẫn đọc | bản thảo + gói dữ liệu/mã |
| P5 Nộp | 16 | ~cuối 02/2027 | nộp EMS hoặc Aquacultural Engineering | — |

Không hứa kết quả bản tin trực tiếp trước P3. Nếu đến 11/01 độ phủ vẫn < 90 %, bài dùng bậc "dựng lại" làm chính và báo bậc "trực tiếp" như kết quả sơ bộ với số mốc thực có.

### 5.3 Quy tắc đánh giá (giữ phong cách gate của dự án)

- **NB1:** 5 fold × 7 ngày + lockbox 14 ngày (giữ nguyên lockbox 10–24/10 cho P2 để so trực tiếp với RL-62/RL-66; P3 dùng lockbox mới cuối 12/2026, chọn trước). Gate #16: ≥ 4/5 fold thắng + DM-HLN lockbox p < 0,05. Hiệu chỉnh Holm cho số chân trời × số so sánh chính.
- **NERRS:** mỗi trạm chia theo thời gian (huấn luyện ridge trên năm đầu, kiểm tra năm sau; FM chỉ dùng ngữ cảnh trước mốc). Kết quả gộp: tỷ lệ trạm thắng, trung vị skill, Wilcoxon theo trạm; DM từng trạm làm phụ lục.
- **Chống rò rỉ:** ngữ cảnh kết thúc tại `issued_at − 1 phút` (assert, như RL-62); covariate thời tiết chỉ dùng bản tin có `retrieved_at ≤ issued_at` (roadmap nguyên tắc 3); oracle chỉ là cận trên, ghi nhãn rõ.
- **Thước đo:** MAE, RMSE, skill so với persistence; CRPS / weighted quantile loss; độ phủ PI80/PI90, độ rộng, Winkler; độ phủ theo ngày (ngày tệ nhất).
- **Chỉ một lần mở lockbox** cho mỗi giả thuyết; mọi thử nghiệm cấu hình làm trên fold.

### 5.4 Hình và bảng dự kiến

| # | Hình / bảng | Nội dung |
| --- | --- | --- |
| F1 | Bản đồ + ảnh lồng | NB1 Cát Bà, các khu NERRS |
| F2 | Chuỗi nhiệt độ NB1 | 29/05 → 12/2026, đánh dấu giai đoạn biên độ nhỏ/lớn, can thiệp thiết bị (31/07, 12/08, 16/09), lockbox |
| F3 | Sơ đồ phương pháp | dị thường ngày–đêm → Chronos-2 (+ thời tiết, triều) → cộng lại → conformal hóa |
| F4 | Thang nguồn gốc bản tin | MAE theo chân trời cho 5 bậc thời tiết |
| F5 | MAE theo chân trời | các mô hình trên NB1 (có CI bootstrap khối) |
| F6 | NERRS | phân bố skill theo trạm (violin), tỷ lệ trạm thắng |
| F7 | Độ phủ PI80 theo ngày | các phương pháp khoảng, qua thay đổi chế độ |
| F8 | Ví dụ dự báo | 2–3 ngày (trước / sau đổi chế độ; ngày mưa) |
| T1 | Dữ liệu | NB1 + NERRS: thời kỳ, tần suất, % thiếu, QC |
| T2 | Mô hình | tham số, ngữ cảnh, covariate, tốc độ CPU |
| T3 | Gate #16 NB1 | MAE, skill, fold thắng, DM p |
| T4 | Ablation | − thời tiết, − triều, − dị thường ngày–đêm, − conformal |
| T5 | Khoảng tin cậy | độ phủ / độ rộng / Winkler theo chế độ |
| T6 | Chi phí | s/mốc, RAM, khả năng chạy thời gian thực |

### 5.5 Dàn ý bài (IMRaD)

1. **Introduction**
   - Nuôi lồng biển cần cảnh báo sớm nhiệt độ (sốc nhiệt, mùa lạnh); IoT rẻ nhưng nhiễu.
   - Mô hình nền chuỗi thời gian (Chronos, TimesFM, Moirai, TiRex) và thế hệ có covariate (Chronos-2).
   - Khoảng trống: bài ứng dụng thiếu baseline mạnh và kiểm định; dùng thời tiết oracle; khoảng tin cậy không được kiểm qua thay đổi chế độ.
   - Đóng góp: (i) benchmark có đăng ký trước, (ii) thang nguồn gốc bản tin, (iii) dị thường ngày–đêm + FM, (iv) conformal dưới đổi chế độ, (v) dữ liệu + mã mở.
2. **Study site and data** — NB1 (sensor, QC, các can thiệp thiết bị, kiểm tra chéo SST); NERRS; thời tiết (5 bậc nguồn gốc); triều.
3. **Methods** — bài toán và chân trời; baseline (persistence, diurnal-naive, ridge B4/B4D/B5D, một mô hình học sâu); mô hình nền; đề xuất (dị thường + covariate + conformal); giao thức đánh giá (fold, lockbox, gate, DM-HLN, Holm, chống rò rỉ); đăng ký trước.
4. **Results** — NERRS; NB1 độ chính xác; thời tiết theo nguồn gốc; khoảng tin cậy; ablation; chi phí.
5. **Discussion** — khi nào FM đáng dùng so với ridge có đặc trưng tốt; giá trị thật của bản tin thời tiết; ý nghĩa cho cảnh báo nuôi trồng (shadow mode); hạn chế: một lồng, ngắn, đầu dò nhiệt, chưa đủ mùa đông; hướng tiếp (nhiều lồng, DO).
6. **Conclusions**
7. **Data and code availability** — xem 5.7.

### 5.6 Đã có / phải làm

| Thành phần | Đã có | Phải làm |
| --- | --- | --- |
| Harness benchmark, fold, lockbox, gate #16, DM-HLN | `forecast_sensor_v2.py`, `forecast_gate16_report.py`, `forecast_dm_test.py` | thêm Holm; gộp theo trạm cho NERRS |
| Ridge B4/B4D/B5D, diurnal-naive | `forecast_h1_diurnal.py`, `foundation_zero_shot.py` | — |
| Chronos-Bolt, TimesFM 2.5 zero-shot | `foundation_zero_shot.py`, venv `.venv-fm` | thêm Chronos-2 (covariate qua `predict_df` + `future_df`), TiRex, Moirai 2.0 |
| Thời tiết dựng lại, giả, oracle | `reconstruct_external_context.py` (Previous Runs), `forecast_pseudo_as_issued_weather.py`, `forecast_oracle_weather_upper_bound.py` | ghép thành covariate tương lai cho Chronos-2 theo đúng `retrieved_at` |
| Bản tin trực tiếp | task + worker, `core/b5_coverage.py` | chờ độ phủ; script trích bản tin cho từng mốc |
| Triều | B6 (mực nước mô hình) trong `forecast_sensor_v2.py` | kiểm tra dùng được làm covariate tương lai (triều thiên văn biết trước) |
| Conformal (ACI, aci_scaled, aci_amp) | `forecast_conformal.py`, `core/forecast_intervals.py` | conformal hóa phân vị FM (CQR); AgACI hoặc conformal PID có trễ |
| NERRS 33 trạm 2007–2011 | `data/foreign/nerrs_ncei/`, `nerrs_load.py`, `transfer_forecast.py` | chuẩn hóa đầu vào cho harness; (tùy chọn) xin NERRS 2024–2025 qua CDMO để có Previous Runs |
| Kiểm tra đầu dò nhiệt | RL-57, RL-60 (SST mô hình) | so biên độ ngày–đêm NB1 với SST mô hình; hỏi GreenLab |
| Sổ shadow | `shadow_scorecard.py` | (nếu chủ dự án đồng ý torch trong runtime) chạy Chronos ở shadow để có bằng chứng ngoài mẫu thật |
| Gói dữ liệu công bố | — | CSV NB1 nhiệt độ + cờ QC (cần chủ dự án và GreenLab đồng ý), Zenodo DOI, tag repo |

### 5.7 Tuyên bố dữ liệu và mã (nháp)

- NERRS: công khai (NOAA NCEI 0052765 / CDMO), trích dẫn theo yêu cầu CDMO.
- NB1: chuỗi nhiệt độ đã QC + cờ, tần suất 15 phút, đăng trên Zenodo **nếu GreenLab / đơn vị vận hành đồng ý** (phải hỏi trước; không công bố thông tin đăng nhập, không công bố `data/greenlab/handover/`).
- Bản tin thời tiết: Open-Meteo (CC BY 4.0 theo trang Open-Meteo — **chưa kiểm lại**), kèm sổ bản tin trực tiếp đã thu.
- Mã: repo này (hoặc bản rút gọn) với tag phiên bản + `preregistration.json` + manifest hash của từng artifact.

### 5.8 Rủi ro và cách xử lý

| Rủi ro | Ảnh hưởng | Cách xử lý |
| --- | --- | --- |
| Biên độ ngày–đêm là hiện tượng đầu dò (RL-57) | kết luận NB1 chỉ đúng cho "tín hiệu đầu dò" | NERRS là kết quả chính; kiểm tra chéo SST; báo kết quả tách theo chế độ; nói thẳng trong Hạn chế |
| Chronos-2 không thắng B5D | H1 thất bại | vẫn công bố: "baseline mạnh đủ dùng, FM rẻ công thiết kế đặc trưng" — có giá trị cho người làm nuôi trồng; nhấn H2/H3 |
| Bản tin trực tiếp chưa đủ trước 01/2027 | H2 bậc "trực tiếp" yếu | dựng lại (Previous Runs) làm chính; trực tiếp là kiểm chứng phụ |
| CPU chậm với Chronos-2 120M | không kịp chạy NERRS | bước mốc 60 phút, lấy mẫu mốc, dùng `chronos-2-small` (28M) |
| Một trạm, 5–7 tháng | reviewer chê "một trạm" | NERRS 33 trạm; bootstrap khối; lockbox mới ở P3 |
| Dò lockbox do thử nhiều cấu hình | kết quả lạc quan | đăng ký trước, chỉ mở lockbox một lần, ghi mọi lần chạy vào `RESULTS.md` |
| Giấy phép trọng số (TimesFM 3.0 phi thương mại) | hạn chế dùng thương mại | bài nghiên cứu dùng được; ghi rõ; runtime chỉ dùng mô hình Apache-2.0 |

---

## 6. Mười tài liệu tham khảo quan trọng nhất

1. Ansari và cs. (2025). *Chronos-2: From Univariate to Universal Forecasting.* [arXiv:2510.15821](https://arxiv.org/abs/2510.15821) (V1)
2. Ansari và cs. (2024). *Chronos: Learning the Language of Time Series.* [arXiv:2403.07815](https://arxiv.org/abs/2403.07815) (V1)
3. Das và cs. (2024). *A decoder-only foundation model for time-series forecasting* (TimesFM). [arXiv:2310.10688](https://arxiv.org/abs/2310.10688) (V1)
4. Auer và cs. (2025). *TiRex: Zero-Shot Forecasting Across Long and Short Horizons with Enhanced In-Context Learning.* NeurIPS 2025. [arXiv:2505.23719](https://arxiv.org/abs/2505.23719) (V1)
5. Shchur và cs. (2025). *fev-bench: A Realistic Benchmark for Time Series Forecasting.* [arXiv:2509.26468](https://arxiv.org/abs/2509.26468) (V1)
6. Gibbs & Candès (2021). *Adaptive Conformal Inference Under Distribution Shift.* [arXiv:2106.00170](https://arxiv.org/abs/2106.00170) (V1)
7. Angelopoulos và cs. (2023). *Conformal PID Control for Time Series Prediction.* [arXiv:2307.16895](https://arxiv.org/abs/2307.16895) (V1)
8. Auer và cs. (2024). *A data-centric perspective on the information needed for hydrological uncertainty predictions.* HESS 28, 4099. [doi:10.5194/hess-28-4099-2024](https://doi.org/10.5194/hess-28-4099-2024) (V1)
9. Zwart và cs. (2023). *Near-term forecasts of stream temperature using deep learning and data assimilation in support of management decisions.* JAWRA. [doi:10.1111/1752-1688.13093](https://doi.org/10.1111/1752-1688.13093) (V1 Crossref)
10. Dabrowski và cs. (2022). *Deep Learning for Prawn Farming: Forecasting and Anomaly Detection.* PAKDD 2022. [doi:10.1007/978-3-031-05981-0_3](https://doi.org/10.1007/978-3-031-05981-0_3) (V1)

Tham khảo phụ quan trọng: Spoek và cs. 2026 ([arXiv:2608.20024](https://arxiv.org/abs/2608.20024)), Achour và cs. 2025 ([arXiv:2507.08858](https://arxiv.org/abs/2507.08858)), Zaffran và cs. 2022 ([arXiv:2202.07282](https://arxiv.org/abs/2202.07282)), Rangaraj và cs. 2025 ([arXiv:2505.01415](https://arxiv.org/abs/2505.01415)), Read và cs. 2019 ([doi:10.1029/2019WR024922](https://doi.org/10.1029/2019WR024922)), Hollmann và cs. 2025 ([doi:10.1038/s41586-024-08328-6](https://doi.org/10.1038/s41586-024-08328-6)), Water Research 2026 DO ([doi:10.1016/j.watres.2025.124931](https://doi.org/10.1016/j.watres.2025.124931)).

## 7. Việc cần chủ dự án quyết

1. Chọn ứng viên 1 và tạp chí đích đầu tiên (EMS hay Aquacultural Engineering).
2. Đồng ý hỏi GreenLab / đơn vị vận hành: (a) đầu dò nhiệt có đổi vị trí / vỏ quanh 12–20/08; (b) có cho công bố chuỗi nhiệt độ NB1 đã QC không.
3. Có xin NERRS 2024–2025 qua CDMO (đăng ký miễn phí) để có thang bản tin trên nhiều trạm không.
4. Có cho chạy Chronos (torch) ở shadow để có bằng chứng ngoài mẫu thật cho bài không (decisions mới nếu đồng ý).
