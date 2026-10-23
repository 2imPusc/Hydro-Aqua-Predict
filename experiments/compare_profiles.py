import pandas as pd
import numpy as np

def compare_statistical_profiles():
    # 1. Tải dữ liệu Real-time (Làng bè anh Toàn)
    df_rt = pd.read_csv("data/greenlab/greenlab_export.csv")
    df_rt = df_rt[df_rt["device"] == "06M26042804"]
    
    # 2. Tải dữ liệu Lịch sử (Hải Phòng)
    df_hist = pd.read_csv("data/haiphong/clean_data.csv")
    
    # Lọc Lịch sử theo Quý 2 (Tương đồng thời gian Tháng 5/Tháng 6 hiện tại)
    df_hist['month'] = pd.to_datetime(df_hist["Quarter"]).dt.month
    df_hist = df_hist[df_hist["month"].isin([4, 5, 6])]
    
    # Các tham số chung đo được trực tiếp
    params = ["pH", "Temperature", "TSS"]
    
    # Tính giá trị Trung bình (Mean) cho Real-time
    rt_profile = df_rt[params].mean()
    
    # Tính giá trị Trung bình cho NB1 và NB2
    nb1_profile = df_hist[df_hist["Station"] == "NB1"][params].mean()
    nb2_profile = df_hist[df_hist["Station"] == "NB2"][params].mean()
    
    # Chuẩn hóa (Min-Max Scaling dựa trên Lịch sử) để tính khoảng cách không bị lệch đơn vị
    min_vals = df_hist[params].min()
    max_vals = df_hist[params].max()
    
    def normalize(profile):
        return (profile - min_vals) / (max_vals - min_vals)
        
    rt_norm = normalize(rt_profile)
    nb1_norm = normalize(nb1_profile)
    nb2_norm = normalize(nb2_profile)
    
    # Tính khoảng cách Euclidean
    dist_nb1 = np.sqrt(np.sum((rt_norm - nb1_norm)**2))
    dist_nb2 = np.sqrt(np.sum((rt_norm - nb2_norm)**2))
    
    print("=== SO SÁNH 'CHỮ KÝ SINH THÁI' (QUÝ 2 - ECOLOGICAL SIGNATURE) ===")
    print("\n[Hồ sơ Gốc - Raw Means]")
    print(f"Real-time (Anh Toàn): pH={rt_profile['pH']:.2f}, Temp={rt_profile['Temperature']:.2f}, TSS={rt_profile['TSS']:.2f}")
    print(f"Lịch sử NB1         : pH={nb1_profile['pH']:.2f}, Temp={nb1_profile['Temperature']:.2f}, TSS={nb1_profile['TSS']:.2f}")
    print(f"Lịch sử NB2         : pH={nb2_profile['pH']:.2f}, Temp={nb2_profile['Temperature']:.2f}, TSS={nb2_profile['TSS']:.2f}")
    
    print("\n[Độ lệch chuẩn hóa - Statistical Distance]")
    print(f"Độ lệch giữa (Anh Toàn) và (NB1): {dist_nb1:.4f}")
    print(f"Độ lệch giữa (Anh Toàn) và (NB2): {dist_nb2:.4f}")
    
    if dist_nb1 < dist_nb2:
        print("\n=> KẾT LUẬN: Trạm NB1 CÓ HỆ SINH THÁI GIỐNG VỚI REAL-TIME HƠN (Khi so cùng Quý 2)!")
    else:
        print("\n=> KẾT LUẬN: Trạm NB2 CÓ HỆ SINH THÁI GIỐNG VỚI REAL-TIME HƠN (Khi so cùng Quý 2)!")

if __name__ == "__main__":
    compare_statistical_profiles()
