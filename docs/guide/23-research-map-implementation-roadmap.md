# Tài liệu hướng dẫn triển khai tiếp theo cho Research Map

**Lưu ý:** Tài liệu này dành cho người trực tiếp lập trình, kiểm thử và vận hành trên hệ điều hành Windows/PowerShell.
Việc tạo tài liệu này không bao gồm triển khai các thay đổi ứng dụng.

## Phạm vi
Hướng dẫn chi tiết sửa nền tảng dữ liệu, cảnh báo, API/UI và worker; kèm lộ trình nghiên cứu dự báo và suy rộng không gian.

---

## 1. Nội dung hướng dẫn triển khai

### Giai đoạn A — Sửa độ đúng dữ liệu, ưu tiên P0

#### A1. Chọn đúng quan trắc sensor
- **Vấn đề hiện tại:** Có nguy cơ ghi đè giá trị quan trắc mới bằng giá trị cũ, bỏ qua metadata quan trọng (thời gian, đơn vị, nguồn, QC).
- **Hành vi mong muốn:**
  - Lấy bản ghi mới nhất hợp lệ cho từng chỉ số; tránh ghi đè giá trị mới bằng giá trị cũ.
  - Giữ `observed_at`, đơn vị, nguồn và QC cho từng chỉ số.
  - Dùng cấu hình freshness hiện có; dữ liệu quá hạn không được coi là hiện tại.
  - Chỉ quy đổi NH3 khi NH4, pH và nhiệt độ hợp lệ, còn hạn và lệch thời gian không quá 5 phút (giới hạn này là mặc định kỹ thuật có thể cấu hình).
  - Giữ hệ số quy đổi đang cấu hình; ghi rõ cần xác nhận cơ sở đo NH4/TAN và đơn vị với tài liệu sensor trước khi xem kết quả là đã hiệu chuẩn.
- **Thành phần cần sửa:** Backend worker (xử lý sensor), Database Schema (nếu thiếu metadata).
- **Thứ tự thực hiện:** Sửa logic lưu bản ghi -> Thêm validation NH3 -> Cập nhật cấu hình metadata.
- **Kiểm thử:** Unit test logic chọn bản ghi và tính NH3.
- **Điều kiện nghiệm thu:** Bản ghi mới luôn thắng; NH3 không quy đổi nếu thiếu tham số.
- **Cách khôi phục:** Rollback thay đổi logic xử lý sensor trong worker.

#### A2. Chuẩn hóa thời tiết cho cảnh báo
- **Vấn đề hiện tại:** Dữ liệu tính cảnh báo và dữ liệu vẽ bản đồ chưa tách biệt; thời tiết dùng tức thời.
- **Hành vi mong muốn:**
  - Tách dữ liệu tính cảnh báo khỏi GeoJSON dùng để vẽ bản đồ.
  - Chuẩn hóa vận tốc về m/s; chuyển rõ sang km/h khi so với ngưỡng hiện có.
  - Lưu chuỗi dự báo theo giờ cùng thời gian phát hành/thu nhận, thời gian hiệu lực và tọa độ nguồn.
  - Tính tổng mưa và cực đại gió từ sáu khoảng dự báo một giờ hoàn chỉnh tiếp theo. Không dùng một giá trị tức thời rồi đặt nhãn “6h”.
  - Thiếu bất kỳ khoảng giờ bắt buộc nào thì đánh dấu cửa sổ chưa đầy đủ; không điền bằng 0.
  - Giữ `provenance` để truy ngược artifact về snapshot nguồn.
- **Thành phần cần sửa:** Backend worker (xử lý thời tiết).
- **Thứ tự thực hiện:** Tách cấu trúc dữ liệu -> Cập nhật logic parse và lưu chuỗi giờ -> Logic tính tổng/cực đại 6h.
- **Kiểm thử:** Unit test tính tổng 6h và xử lý khuyết giờ.
- **Điều kiện nghiệm thu:** 6h đủ dữ liệu mới tính; `provenance` lưu lại rõ ràng.
- **Cách khôi phục:** Rollback parser thời tiết.

#### A3. Tách mức cảnh báo và chất lượng dữ liệu
- **Vấn đề hiện tại:** Trạng thái cảnh báo và chất lượng dữ liệu dễ nhầm lẫn.
- **Hành vi mong muốn:**
  - Mức nguy cơ: `NORMAL`, `WATCH`, `WARNING`; cho phép chưa xác định khi không đủ dữ liệu.
  - Chất lượng dữ liệu: `complete`, `partial`, `stale`, `missing`.
  - Chỉ hiển thị bình thường khi dữ liệu bắt buộc của nhóm đánh giá đầy đủ và không vượt ngưỡng.
  - Nếu còn bằng chứng hợp lệ về nguy cơ, giữ cảnh báo đó và ghi rõ dữ liệu thiếu; không xóa cảnh báo chỉ vì một nguồn khác mất kết nối.
  - Tách nhóm chất lượng nước, thời tiết và kết quả phù hợp nuôi trồng.
  - Giữ ngưỡng hiện tại dưới nhãn chính sách nghiên cứu có phiên bản; chưa coi chúng là tiêu chuẩn vận hành đã được thẩm định.
- **Thành phần cần sửa:** Backend API (đánh giá nguy cơ), cấu trúc artifact.
- **Thứ tự thực hiện:** Định nghĩa enum nguy cơ/chất lượng -> Cập nhật engine đánh giá -> Cập nhật API response.
- **Kiểm thử:** Scenario test thiếu dữ liệu kèm nguy cơ.
- **Điều kiện nghiệm thu:** Mất kết nối một nguồn không xóa đi cảnh báo đang có.
- **Cách khôi phục:** Revert hàm đánh giá logic trạng thái.

### Giai đoạn B — Đồng bộ artifact, API và giao diện

#### B1. Artifact theo từng điểm bản đồ
- **Vấn đề hiện tại:** Chưa trả về thông tin cục bộ riêng từng điểm.
- **Hành vi mong muốn:**
  - Backend xuất một feature cho mỗi mã điểm trong registry, dùng tọa độ thật.
  - Tính thời tiết theo vị trí điểm.
  - Khi tham chiếu sensor pilot cho điểm khác, ghi `pilot_reference`, mã sensor nguồn và phạm vi áp dụng; không gọi thao tác sao chép này là nội suy.
  - Chưa sinh giá trị chất lượng nước riêng cho từng điểm khi chưa có mô hình không gian được kiểm định.
- **Thành phần cần sửa:** Backend API (tạo artifact).
- **Thứ tự thực hiện:** Thêm tọa độ cho điểm -> Gắn thời tiết -> Gắn `pilot_reference`.
- **Kiểm thử:** API check trả về feature tương ứng từng điểm.
- **Điều kiện nghiệm thu:** Artifact chứa tọa độ và ref nguồn rõ ràng.
- **Cách khôi phục:** Rollback generator API.

#### B2. Hợp đồng API
- **Vấn đề hiện tại:** Thiếu thuộc tính để xử lý chế độ live/mock và nguyên nhân cảnh báo.
- **Hành vi mong muốn:**
  - Giữ endpoint `/api/v1/aquaculture-map`, nâng phiên bản artifact để chứa tối thiểu:
    - Mã điểm và chế độ live/mock.
    - Trạng thái dữ liệu, mức cảnh báo và các nguyên nhân.
    - Nguồn đo trực tiếp/tham chiếu pilot/dữ liệu mock.
    - Thời gian quan trắc theo chỉ số, thời gian hiệu lực dự báo, snapshot và phiên bản chính sách.
  - Backend và frontend cập nhật cùng đợt. Cache phiên bản mới nằm riêng; không dùng lại artifact cũ thiếu trường rồi mặc định thành bình thường.
- **Thành phần cần sửa:** Backend API endpoint `/api/v1/aquaculture-map`, Frontend.
- **Thứ tự thực hiện:** Cập nhật schema -> Triển khai Backend -> Cập nhật Frontend.
- **Kiểm thử:** Schema validation.
- **Điều kiện nghiệm thu:** Cache không trộn lẫn phiên bản.
- **Cách khôi phục:** Triển khai lại cả FE và BE về commit trước đó.

#### B3. Hiển thị bản đồ và Sidebar
- **Vấn đề hiện tại:** Giao diện chưa phân biệt rõ trạng thái, có thể báo lỗi hoặc hiển thị quá mức.
- **Hành vi mong muốn:**
  - Dùng chung bộ ánh xạ trạng thái và nhãn nguyên nhân.
  - Xanh: bình thường; cam: cần theo dõi; đỏ: cảnh báo; vòng xám/rỗng: chưa đủ dữ liệu.
  - Popup và Sidebar hiển thị nguồn, thời gian và nguyên nhân tiếng Việt.
  - Dùng “gió mạnh”, “mưa lớn”, “NH3 vượt ngưỡng” theo dữ liệu thực có; không suy ra “bão” chỉ từ vận tốc gió.
  - Giữ một lớp marker trạng thái, tránh tái xuất hiện ba vòng tròn lớn.
  - Hiển thị lỗi tải và trạng thái đang tạo artifact; không nuốt lỗi rồi tô xanh.
  - Hủy timer/request khi đổi mode để tránh phản hồi cũ ghi đè chế độ mới.
- **Thành phần cần sửa:** Frontend (Map, Sidebar, API fetcher).
- **Thứ tự thực hiện:** Màu sắc UI -> Nhãn tiếng Việt -> Quản lý request/timer.
- **Kiểm thử:** UI test đổi mode live/mock nhanh.
- **Điều kiện nghiệm thu:** Không bị lag marker, không lỗi đè request.
- **Cách khôi phục:** Revert Frontend UI component.

#### B4. Mock phục vụ kiểm thử
- **Vấn đề hiện tại:** Mock chưa đồng bộ trạng thái chính xác.
- **Hành vi mong muốn:**
  - Backend cung cấp danh sách scenario để frontend không duy trì danh sách riêng.
  - Ánh xạ scenario theo mã điểm cố định, thay cho modulo theo thứ tự danh sách.
  - Mỗi scenario có kết quả mong đợi xác định: bình thường, mưa/gió cần theo dõi, NH3 cần theo dõi, nhiệt độ cảnh báo, nhiều nguy cơ, dữ liệu thiếu và dữ liệu quá hạn.
  - Điều chỉnh fixture NH3 đúng dải `WATCH`; tách trường hợp `WARNING`.
  - Kịch bản so sánh cá giò–hàu phải thực sự tính hai chính sách và hiển thị kết quả so sánh.
  - Nhãn mock luôn hiện rõ; thay đổi scenario chỉ tác động dữ liệu demo đã mô tả.
- **Thành phần cần sửa:** Backend mock endpoint, Frontend selector.
- **Thứ tự thực hiện:** Thêm danh sách kịch bản API -> Mapping kịch bản.
- **Kiểm thử:** E2E test các kịch bản.
- **Điều kiện nghiệm thu:** Chọn kịch bản nào đúng kịch bản đó, ổn định.
- **Cách khôi phục:** Rollback mock service.

### Giai đoạn C — Worker, lưu trữ và hiệu năng
- **Vấn đề hiện tại:** Task liên kết chặt chẽ dễ gây chặn, ghi file thiếu đồng bộ, chưa tối ưu hiệu năng đồ họa.
- **Hành vi mong muốn:**
  - Tách vòng thu sensor, thu thời tiết và xây artifact nặng thành các tác vụ được giám sát độc lập; lỗi tác vụ này không dừng tác vụ khác.
  - Tạo mock sớm khi khởi động; cập nhật live advisory khi quan trắc hoặc snapshot đầu vào thay đổi.
  - Ghi artifact bằng file tạm và thay thế nguyên tử; có phiên bản và hash đầu vào.
  - Bổ sung log thời gian chạy, lần thành công gần nhất, lỗi provider và trạng thái từng tác vụ; không log bí mật cấu hình.
  - Giữ snapshot tốt gần nhất khi provider lỗi nhưng phản ánh đúng độ cũ.
  - Đo thời gian dựng artifact, kích thước response, độ trễ API và FPS trước khi tối ưu.
  - Với hạt chuyển động: dùng deltaTime, giới hạn bước khi tab hoạt động lại, tiền tính nội suy khi trường dữ liệu/viewport đổi và kiểm tra đoạn di chuyển qua mask.
  - WebGL/texture/tiling là bước mở rộng sau khi benchmark xác định giới hạn của canvas hiện tại.
- **Thành phần cần sửa:** Backend Task queue (Celery/APScheduler), UI rendering (Canvas).
- **Thứ tự thực hiện:** Tách task -> Lưu trữ atomic -> Log -> Tối ưu UI animation.
- **Kiểm thử:** Stress test worker lỗi, benchmark UI.
- **Điều kiện nghiệm thu:** Không gián đoạn khi một provider sập, đồ họa dùng deltaTime mượt.
- **Cách khôi phục:** Revert cấu hình worker và canvas animation.

---

## 2. Kiểm thử và triển khai

### Ma trận kiểm thử

| Nhóm | Điều kiện nghiệm thu |
| --- | --- |
| Sensor | Bản ghi mới thắng bản ghi cũ; giá trị không mang timestamp của chỉ số khác |
| NH3 | Kiểm tra đơn vị, thiếu đầu vào, QC lỗi, quá hạn và lệch thời gian |
| Thời tiết | Chuyển đổi đơn vị đúng; tổng/cực đại sáu giờ đúng; thiếu giờ không biến thành 0 |
| Trạng thái | Thiếu dữ liệu không thành xanh; cảnh báo có bằng chứng vẫn được giữ |
| API/artifact | Đọc đồng thời lúc ghi không trả JSON dở; cache cũ không bị hiểu là phiên bản mới |
| Mock | Mọi scenario có kết quả đúng và ổn định theo mã điểm |
| UI | Marker và Sidebar đồng nhất; đổi nhanh live/mock không hiển thị kết quả sai chế độ |
| Worker | Giả lập tác vụ hình học chậm không chặn vòng thu sensor |
| Animation | Cùng thời gian thực cho chuyển động tương đương ở FPS khác nhau; đoạn hạt không vượt đất |

### Vận hành PowerShell (Triển khai & Kiểm tra)

**Môi trường:**
- Thư mục chạy rõ ràng: `research-map`
- Kiểm tra dependencies: Python, Node.js, Docker.

**Các bước (chưa xác minh):**
```powershell
# Di chuyển vào thư mục làm việc
cd D:\2impusc\Hydro-Aqua-Predict\research-map

# 1. Ghi lại cấu hình và Image ID trước triển khai
docker images > pre_deploy_images.txt
Copy-Item .env pre_deploy.env

# 2. Kiểm tra Test BE/FE (Giả định có thư mục tests hoặc lệnh test)
# python -m pytest tests/
# cd frontend; npm run test; cd ..

# 3. Build & Rebuild Services
# KHÔNG reset database, KHÔNG xóa volume, KHÔNG đè .env
docker compose build frontend backend-fastapi
docker compose up -d --no-deps frontend backend-fastapi

# 4. Kiểm tra dịch vụ hoạt động (Endpoints mặc định)
Invoke-WebRequest -Uri http://localhost:8010/docs -UseBasicParsing | Select-Object StatusCode
Invoke-WebRequest -Uri http://localhost:5173 -UseBasicParsing | Select-Object StatusCode
Invoke-WebRequest -Uri http://localhost:8083 -UseBasicParsing | Select-Object StatusCode
```

**Nguyên tắc triển khai:**
- Khôi phục bằng image trước đó và cache tương thích, không reset database hoặc xóa volume.
- Không sao chép đè `.env` đã tồn tại.
- Không sửa dữ liệu trong các thư mục được bảo vệ (`data/`, `map/`, `tieu-chi/`, `model/output/**/*.pkl`, `model/cache/`, `output/`).
- Các lệnh trong tài liệu được đối chiếu với repo. Các kết quả trên terminal sau khi chạy lệnh phải hiển thị mã lỗi (VD: `StatusCode 200`), nếu chưa chạy thì hiện tại đánh giá là **chưa xác minh**.

---

## 3. Lộ trình nghiên cứu và điều kiện chuyển giai đoạn

### Các nhánh nghiên cứu
- **Dự báo chỉ số:** So sánh persistence, sensor-only và sensor + thời tiết bằng rolling evaluation và lockbox; kiểm soát thời điểm dữ liệu dự báo thực sự có sẵn.
- **Cảnh báo:** Đánh giá theo sự kiện, gồm báo giả, bỏ sót, thời gian báo trước; thử điều kiện duy trì và ngưỡng hồi phục.
- **Suy rộng không gian:** Thu mẫu đối chứng ngoài pilot theo vị trí và pha triều; so sánh tham chiếu đồng nhất với mô hình theo khoảng cách mặt nước và yếu tố môi trường.
- **Dòng chảy vùng đảo:** Tách độ đúng hiển thị khỏi độ đúng thủy động lực; chỉ nghiên cứu lan truyền sau khi có điều kiện biên, địa hình và dữ liệu kiểm định phù hợp.
- **Hiệu năng GPU:** Quyết định bằng benchmark trên cùng máy, cùng viewport và cùng số hạt.

### Điều kiện chuyển giai đoạn
- Hoàn thành **Giai đoạn A** trước **Giai đoạn B**.
- Hoàn thành hợp đồng dữ liệu **B** trước nghiệm thu giao diện.
- Thực hiện **Giai đoạn C** trước thử nghiệm chạy liên tục.
- Các nhánh nghiên cứu chỉ được nâng thành chức năng live khi có bằng chứng đánh giá tương ứng.

---

## 4. Checklist bàn giao & Phân loại

### Checklist kiểm tra
- [ ] Logic lấy mới bản ghi cảm biến hoạt động.
- [ ] Thời tiết 6 giờ gộp chính xác.
- [ ] Giao diện Map/Sidebar khớp trạng thái dữ liệu/nguy cơ.
- [ ] Animation canvas chạy theo `deltaTime`.
- [ ] Worker lưu artifact bằng file tạm atomic.

### Danh sách giả định cần xác minh
- Hệ số quy đổi NH4/TAN hiện tại đã khớp với tài liệu cảm biến chưa?
- Canvas giới hạn chịu tải với bao nhiêu hạt trên viewport cấu hình máy hiện tại?
- Tọa độ các điểm trong registry có độ lệch bao xa so với thực tế pilot?

### Bảng trạng thái

| Hạng mục | Trạng thái | Đề xuất tiếp theo |
| --- | --- | --- |
| Tài liệu hướng dẫn | Đã triển khai | - |
| Sửa nền tảng dữ liệu (A) | Chưa xác minh | Bắt đầu với logic xử lý dữ liệu sensor (A1) |
| API & UI (B) | Chưa xác minh | Thực hiện sau khi kết thúc phần A |
| Worker & Hiệu năng (C) | Chưa xác minh | Tách các task thu thập hiện tại chạy độc lập |
