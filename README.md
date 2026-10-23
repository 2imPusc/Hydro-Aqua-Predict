# Hydro-Aqua-Predict

Giám sát gần-thời-gian-thực, dự báo ngắn hạn và cảnh báo điều kiện nuôi lồng bè ven biển
(cá giò, hàu) từ cảm biến GreenLab tại miền Bắc Việt Nam.

Pipeline: lấy dữ liệu sensor → kiểm tra chất lượng → quy đổi NH4→NH3 → nội suy tham số
thiếu từ dữ liệu quan trắc lịch sử → chấm điểm theo QCVN 10:2023 B1 / ngưỡng loài →
dự báo và khuyến nghị ở **chế độ shadow** (ghi sổ và chấm điểm, chưa phát cho người nuôi).

Tách ra từ đồ án `DATN-20225064` (thư mục `lab-realtime/`) ngày 2026-10-08. Chạy độc lập, không phụ thuộc DATN.

## Chạy nhanh

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env        # điền TK_DHTB / MK_DHTB
# khôi phục data/ (không có trong git) → xem docs/data-policy.md
.venv\Scripts\python -m pytest -q
.venv\Scripts\streamlit run app\demo_app.py
```

Bản đồ nghiên cứu môi trường (FastAPI + React):

```powershell
powershell -ExecutionPolicy Bypass -File research-map\dev-local.ps1
```

## Cấu trúc

| Thư mục | Nội dung |
| --- | --- |
| `core/` | Pipeline xử lý, dự báo, cảnh báo, shadow runner |
| `app/` | Dashboard Streamlit |
| `research-map/` | Bản đồ ngữ cảnh môi trường (FastAPI + worker + React) |
| `ingest/` | Script lấy dữ liệu GreenLab, danh mục trạm |
| `hap_shared/` | Hàm chấm điểm và tiền xử lý dùng chung, kèm ngưỡng loài |
| `experiments/` | Script thí nghiệm; chỉ mục kết quả ở `experiments/RESULTS.md` |
| `docs/guide/` | Tài liệu thiết kế và nhật ký chạy (bắt đầu ở `00-tong-quan-du-an.md`) |

## Tài liệu

- [AGENTS.md](AGENTS.md): lệnh chạy, quy tắc, lưu ý miền (dành cho người và AI agent)
- [docs/roadmap.md](docs/roadmap.md): lộ trình phát triển, thứ tự ưu tiên 1 → 2 → 4 → 3
- [docs/decisions.md](docs/decisions.md): nhật ký quyết định kiến trúc
- [docs/data-policy.md](docs/data-policy.md): dữ liệu nào lên git, dữ liệu nào giữ local
- [docs/guide/00-tong-quan-du-an.md](docs/guide/00-tong-quan-du-an.md): tổng quan dự án
- [docs/guide/06-runbook.md](docs/guide/06-runbook.md): vận hành
