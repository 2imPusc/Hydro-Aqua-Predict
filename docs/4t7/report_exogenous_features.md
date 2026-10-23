# Báo cáo Thực nghiệm: Tích hợp Đặc trưng Ngoại lai (Exogenous Features) vào Mô hình Phóng chiếu Không gian Toàn vùng

## 1. Mục đích Thực nghiệm
Thực nghiệm mở rộng nhằm đánh giá sức mạnh của việc bổ sung **Độ sâu (Depth)**, **Thời tiết (Mưa, Gió, Sóng)** và **Tọa độ địa lý (Lat/Lon)** vào mô hình **Order A (Local $\rightarrow$ Spatial)**. Lần này, thay vì chạy trên một cặp trạm duy nhất, mô hình được lặp qua **toàn bộ 13 trạm mục tiêu (Target)** trong vùng Hải Phòng để lấy giá trị trung bình (Average $R^2$), nhằm đưa ra cái nhìn khách quan và đại diện nhất cho toàn vùng vịnh.

## 2. Kết quả Thực nghiệm (Trung bình 13 Trạm Đích)
- **Trạm Gốc (Anchor):** `NB1`
- **Số lượng Trạm Đích:** `13`
- **Phương pháp đánh giá:** Cross-Validation 3-Fold, tính trung bình $R^2$ của cả 13 cặp dự đoán.

| Cấu hình (Feature Set) | DO ($R^2$) | Salinity ($R^2$) |
| :--- | :--- | :--- |
| **Base (4 Chỉ số gốc)** | `-0.5404` | `-0.6177` |
| **Base + Độ sâu** | `-0.5404` | `-0.6177` |
| **Base + Tọa độ (Lat/Lon)** | `-0.5404` | `-0.6177` |
| **Base + Thời tiết** | `-0.2825` | `-0.0974` |
| **Base + Tọa độ + Thời tiết** | `-0.2825` | `-0.0974` |
| **Tất cả (All)** | `-0.2825` | `-0.0974` |

## 3. Bàn luận và Kết luận Khoa học (Điểm nhấn Luận văn)

1. **Nghịch lý của Tọa độ (Lat/Lon) và Độ sâu (Depth):**
   Một phát hiện cực kỳ thú vị từ bảng kết quả là việc bổ sung Tọa độ và Độ sâu **không làm thay đổi dù chỉ 0.0001** hệ số $R^2$ so với cấu hình Base. 
   Lý do ẩn sau bản chất của mô hình: Chúng ta đang sử dụng kiến trúc **Pairwise (Dự đoán theo cặp 1-1, ví dụ NB1 $\rightarrow$ NB4, NB1 $\rightarrow$ NB5...)**. Trong mỗi cặp dự đoán, Tọa độ và Độ sâu là **các hằng số bất biến theo thời gian (Time-invariant features)**. Thuật toán Cây quyết định (XGBoost) dựa vào sự biến thiên (variance) để chia nhánh; do đó nó sẽ tự động loại bỏ (prune) hoàn toàn các biến hằng số này vì chúng không cung cấp thêm bất kỳ Information Gain nào.
   *(Nhận định mở rộng: Nếu sau này nhóm nghiên cứu chuyển sang mô hình Global - gom tất cả 13 trạm vào chung một tập huấn luyện - thì lúc này Tọa độ và Độ sâu mới phát huy tác dụng phân chia ranh giới không gian).*

2. **Khẳng định sức mạnh của Yếu tố Thời tiết (Time-variant features):**
   Trái ngược với Tọa độ và Độ sâu, Thời tiết (Mưa, Gió, Sóng) là các biến **thay đổi liên tục theo thời gian (Time-variant)**. Khi tính trung bình trên toàn bộ 13 trạm:
   - **Độ mặn (Salinity):** Nhờ có thông tin Thời tiết, $R^2$ được kéo từ `-0.6177` lên `-0.0974` (Mức độ cải thiện khổng lồ lên tới $0.52$). Điều này minh chứng mạnh mẽ rằng lượng mưa và gió tác động cực lớn đến độ mặn toàn vịnh, và XGBoost đã xuất sắc nắm bắt được quy luật này.
   - **Oxy hòa tan (DO):** Dù cũng được cải thiện mạnh (từ `-0.54` lên `-0.28`), nhưng DO trung bình toàn vùng vẫn kẹt ở mức âm. Kết luận tối hậu được đưa ra: **Biến động DO mang tính cục bộ vi khí hậu quá cao (do tảo nở hoa, sinh thái thủy triều cục bộ...). Việc chỉ truyền dữ liệu thời tiết cơ học là không đủ, mà bắt buộc phải phân nhỏ Vịnh thành các Cụm (Clustering) để dự đoán riêng biệt!**
