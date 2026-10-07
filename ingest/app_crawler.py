import streamlit as st
import pandas as pd
import yaml
import subprocess
import os
import json
import re
from datetime import datetime
import sys

# Cấu hình Path để nhận diện các module của gốc dự án
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.forecast import forecast_24h

st.set_page_config(page_title="GreenLab Dashboard", layout="wide", page_icon="🌍")

# ---------------------------------------------------------
# CONSTANTS & PATHS
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIONS_FILE = os.path.join(BASE_DIR, "stations.yaml")
FETCH_SCRIPT = os.path.join(BASE_DIR, "fetch_api.js")
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "data", "greenlab", "exports")

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
@st.cache_data
def load_stations():
    try:
        with open(STATIONS_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("stations", [])
    except Exception as e:
        st.error(f"Cannot load stations.yaml: {e}")
        return []

def get_latest_data():
    """Loads the AllDevices_Latest.json file to display on dashboard"""
    latest_path = os.path.join(EXPORTS_DIR, "snapshots", "AllDevices_Latest.json")
    if not os.path.exists(latest_path):
        return None, None
    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        mtime = os.path.getmtime(latest_path)
        dt_str = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y %H:%M:%S')
        return data, dt_str
    except:
        return None, None

@st.cache_data
def parse_data_file(filepath):
    """Parses JSON or CSV into a Pandas DataFrame. Cached for performance."""
    try:
        if filepath.endswith(".json"):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, dict):
                # GreenLab custom schema handling
                if "devices" in data and len(data["devices"]) > 0:
                    dfs = []
                    for dev in data["devices"]:
                        if "readings" in dev and dev["readings"]:
                            df_temp = pd.json_normalize(dev["readings"])
                            df_temp["DeviceSerialNumber"] = dev.get("DeviceSerialNumber", "")
                            df_temp["FetchedAt"] = data.get("fetchedAt", "")
                            dfs.append(df_temp)
                    if dfs:
                        return pd.concat(dfs, ignore_index=True)
                return pd.json_normalize(data)
            elif isinstance(data, list):
                return pd.json_normalize(data)
            else:
                return pd.DataFrame([data])
        elif filepath.endswith(".csv"):
            return pd.read_csv(filepath)
    except Exception as e:
        st.error(f"Lỗi đọc file: {e}")
    return pd.DataFrame()

def scan_exports_grouped():
    """Scan the exports folder and group files by subdirectory."""
    grouped = {"all_data": [], "intervals": [], "snapshots": []}
    for root, dirs, filenames in os.walk(EXPORTS_DIR):
        for filename in filenames:
            if filename.endswith(".json") or filename.endswith(".csv"):
                rel_path = os.path.relpath(os.path.join(root, filename), EXPORTS_DIR)
                category = rel_path.split(os.sep)[0]
                if category in grouped:
                    grouped[category].append(rel_path)
    
    # Filter out .json if .csv exists to keep UI clean, and sort
    for k in grouped:
        files = grouped[k]
        csv_files = set(f[:-4] for f in files if f.endswith(".csv"))
        filtered = [f for f in files if f.endswith(".csv") or (f.endswith(".json") and f[:-5] not in csv_files)]
        grouped[k] = sorted(filtered, reverse=True)
        
    return grouped

def render_optimized_chart(df, time_col, plot_cols, time_filter):
    """
    Renders an optimized Streamlit line chart based on predefined filters.
    Auto-downsamples if data points > 5000 to prevent browser lag.
    """
    st.subheader("Biểu đồ Phân tích (Time Series)")
    
    # 1. Convert time column to datetime for filtering
    df_chart = df.copy()
    df_chart[time_col] = pd.to_datetime(df_chart[time_col], errors='coerce')
    df_chart = df_chart.dropna(subset=[time_col]).sort_values(time_col)
    
    if df_chart.empty:
        st.warning("Không có dữ liệu thời gian hợp lệ để vẽ biểu đồ.")
        return
        
    # 2. Apply Time Filter
    if time_filter != "Toàn bộ":
        latest_time = df_chart[time_col].max()
        if time_filter == "7 ngày gần nhất":
            cutoff = latest_time - pd.Timedelta(days=7)
        elif time_filter == "24 giờ gần nhất":
            cutoff = latest_time - pd.Timedelta(hours=24)
        else:
            cutoff = latest_time - pd.Timedelta(hours=1)
        df_chart = df_chart[df_chart[time_col] >= cutoff]
        
    # Drop rows where all selected plot columns are NaN (prevents blank margins)
    df_chart = df_chart.dropna(subset=plot_cols, how='all')
    
    if df_chart.empty:
        st.warning("Không có dữ liệu hợp lệ cho (các) thông số này trong khoảng thời gian đã chọn.")
        return
        
    # 3. Downsampling if too large
    total_rows = len(df_chart)
    if total_rows > 5000:
        import math
        step = math.ceil(total_rows / 5000)
        df_chart = df_chart.iloc[::step]
        
    # 4. Render chart
    st.line_chart(df_chart.set_index(time_col)[plot_cols])

# ---------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------
stations = load_stations()
station_options = {f"{s['serial']} - {s['name_vi']} ({s.get('region', 'Unknown')})": s['serial'] for s in stations}
station_names = list(station_options.keys())

st.title("🌍 GreenLab Control Center")
st.markdown("Hệ thống giám sát trạm thời gian thực & Quản lý tập dữ liệu cho Lab.")

# ---------------------------------------------------------
# TABS SETUP
# ---------------------------------------------------------
tab_dash, tab_view = st.tabs(["📊 Dashboard & Crawl", "📁 View Data"])

# =========================================================
# TAB 1: DASHBOARD
# =========================================================
with tab_dash:
    st.subheader("1. Tổng quan các trạm (Latest Snapshot)")
    
    # Refresh logic
    col_btn, _ = st.columns([1, 5])
    if col_btn.button("🔄 Lấy số liệu mới nhất (All)"):
        with st.spinner("Đang tải dữ liệu từ API..."):
            result = subprocess.run(["node", FETCH_SCRIPT, "latest"], cwd=BASE_DIR, capture_output=True, text=True)
            if result.returncode == 0:
                st.success("✅ Cập nhật dữ liệu thành công!")
            else:
                st.error("❌ Có lỗi xảy ra khi tải dữ liệu.")
            # Clear cache so it reads the new file
            get_latest_data.clear() if hasattr(get_latest_data, "clear") else None

    # Load and display grid
    latest_json, fetch_time = get_latest_data()
    device_data_map = {}
    
    if latest_json and "children" in latest_json:
        for dev in latest_json["children"]:
            serial = dev.get("name")
            device_data_map[serial] = {
                "latestReceivedDate": dev.get("DateSync") or fetch_time or "Data Updated",
                "readings": dev.get("children", [])
            }
            
    # Create Columns for stations (limit to top 4 for UI neatness, or iterate all)
    display_stations = stations[:4] if len(stations) > 4 else stations
    cols = st.columns(len(display_stations) if display_stations else 1)
    
    if not display_stations:
        st.warning("Không tìm thấy trạm nào trong cấu hình.")
    
    for idx, station in enumerate(display_stations):
        serial = station["serial"]
        dev_data = device_data_map.get(serial)
        
        with cols[idx]:
            st.markdown(f"**{station['name_vi']}**")
            st.caption(f"Code: `{serial}`")
            if dev_data and dev_data.get("readings"):
                time_received = dev_data.get("latestReceivedDate", "")
                st.write(f"⏱️ `{time_received}`")
                html_str = "<div style='font-size: 0.9em; line-height: 1.6; padding: 10px; background-color: #f8f9fa; border-radius: 5px; margin-top: 10px;'>"
                for r in dev_data["readings"]:
                    html_str += f"<div style='display: flex; justify-content: space-between; border-bottom: 1px solid #eee; padding-bottom: 3px; margin-bottom: 3px;'><span><b>{r.get('SensorType', '')}</b></span> <span>{r.get('Value', 0)} <small>{r.get('Unit', '')}</small></span></div>"
                html_str += "</div>"
                st.markdown(html_str, unsafe_allow_html=True)
            else:
                st.info("Chưa có dữ liệu.")
                
    st.divider()
    
    # ------------------ CRAWL PANEL ------------------
    st.subheader("2. Điều khiển Crawl Dữ Liệu")
    
    col_mode, col_station = st.columns(2)
    with col_mode:
        mode = st.selectbox("Chế độ Crawl", ["Latest (Snapshot)", "History (Theo Giờ/Ngày)", "By-Date (Khoảng Ngày)", "All Data (Toàn bộ)", "Devices (Xem DS Thiết bị)"])
    with col_station:
        if mode != "Devices":
            selected_station_name = st.selectbox("Chọn Thiết Bị", station_names)
            selected_station = station_options[selected_station_name]
        else:
            selected_station = None
            
    cmd_args = ["node", FETCH_SCRIPT]
    
    # Dynamic form based on mode
    if mode == "Devices":
        cmd_args.append("devices")
    elif mode == "Latest (Snapshot)":
        cmd_args.extend(["latest", "-s", selected_station])
    elif mode == "History (Theo Giờ/Ngày)":
        col1, col2 = st.columns(2)
        with col1:
            sensor = st.selectbox("Chọn Sensor", ["COD", "NH4", "pH", "Temp", "TSS"])
        with col2:
            period = st.selectbox("Khoảng thời gian", ["1h", "24h", "7d", "30d"])
        cmd_args.extend(["history", "-s", selected_station, "-t", sensor, "-p", period])
    elif mode == "By-Date (Khoảng Ngày)":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Ngày Bắt Đầu")
        with col2:
            end_date = st.date_input("Ngày Kết Thúc")
        cmd_args.extend(["by-date", "-s", selected_station, "--start", start_date.strftime("%Y-%m-%d"), "--end", end_date.strftime("%Y-%m-%d")])
    elif mode == "All Data (Toàn bộ)":
        cmd_args.extend(["all", "-s", selected_station])

    if st.button("🚀 Thực thi Lệnh Crawl", type="primary"):
        with st.spinner("Đang kết nối tới API GreenLab..."):
            try:
                result = subprocess.run(cmd_args, cwd=BASE_DIR, capture_output=True, text=True, check=True)
                output = result.stdout if result.stdout is not None else ""
                
                # Regex to find saved path
                match = re.search(r"✅ Data saved successfully to: (.*)", output)
                if match:
                    st.success(f"Dữ liệu đã được tải về và tự động lưu tại: `{match.group(1).strip()}`")
                    st.info("Chuyển sang Tab **View Data** để xem bản dữ liệu này!")
                else:
                    st.success("Lệnh hoàn thành!")
                    with st.expander("Log hệ thống"):
                        st.text(output)
            except subprocess.CalledProcessError as e:
                st.error("Crawl thất bại!")
                st.code(e.stderr if e.stderr is not None else "No error output captured.")

# =========================================================
# TAB 2: VIEW DATA
# =========================================================
with tab_view:
    st.subheader("Khám phá Tập dữ liệu (Data Explorer)")
    
    grouped_files = scan_exports_grouped()
    has_files = any(len(v) > 0 for v in grouped_files.values())
    
    if not has_files:
        st.info("Thư mục `exports/` trống. Hãy qua phần Dashboard để tải dữ liệu về.")
    else:
        col_cat, col_file = st.columns(2)
        with col_cat:
            category = st.selectbox("1. Chọn Loại Dữ Liệu", ["All Data", "Intervals", "Snapshots"])
            
        cat_key = "all_data" if category == "All Data" else category.lower()
        available_files = grouped_files.get(cat_key, [])
        
        with col_file:
            if not available_files:
                st.info(f"Không có file nào trong thư mục {category}.")
                selected_file = None
            else:
                selected_file = st.selectbox("2. Chọn File (được tự động parse từ thư mục)", available_files)
                
        if selected_file:
            actual_file = selected_file
            if selected_file.endswith(".json"):
                csv_alt = selected_file[:-5] + ".csv"
                if os.path.exists(os.path.join(EXPORTS_DIR, csv_alt)):
                    actual_file = csv_alt
                    
            if st.button("📊 Tải Bảng Dữ Liệu", type="primary"):
                st.session_state["loaded_file"] = selected_file
                st.session_state["do_render_chart"] = False
                
            # Kiểm tra xem file đã được yêu cầu load chưa
            if st.session_state.get("loaded_file") == selected_file:
                filepath = os.path.join(EXPORTS_DIR, actual_file)
                
                with st.spinner("Đang render dữ liệu từ Cache..."):
                    df = parse_data_file(filepath)
                    
                    if df.empty:
                        st.warning("File trống hoặc không thể parse thành bảng.")
                    else:
                        st.markdown(f"**Hiển thị:** `{selected_file}`")
                        
                    # Determine format and time_col
                    df_render = df
                    time_col = None
                    
                    if "Value" in df.columns and "SensorType" in df.columns:
                        # Long-format (JSON)
                        if "Date" in df.columns: time_col = "Date"
                        elif "ReceivedDate" in df.columns: time_col = "ReceivedDate"
                        elif "latestReceivedDate" in df.columns: time_col = "latestReceivedDate"
                        elif "FetchedAt" in df.columns: time_col = "FetchedAt"
                        
                        if time_col:
                            try:
                                df_render = df.pivot_table(index=time_col, columns="SensorType", values="Value", aggfunc='mean').reset_index()
                            except:
                                pass
                    else:
                        # Wide-format (CSV)
                        if "fetchedAt" in df.columns: time_col = "fetchedAt"
                        elif "Date" in df.columns: time_col = "Date"
                        
                    # 1. Hiển thị Bảng
                    st.markdown(f"**Số lượng dòng (mốc thời gian):** `{len(df_render)}`")
                    st.dataframe(df_render.head(1000), use_container_width=True)
                        
                    # 2. Biểu đồ Options
                    if time_col and time_col in df_render.columns:
                        st.markdown("---")
                        st.subheader("⚙️ Tùy chọn Vẽ Biểu Đồ")
                        
                        num_cols = df_render.select_dtypes(include=['float64', 'int64']).columns
                        num_cols = [c for c in num_cols if c != time_col]
                        
                        if num_cols:
                            col_t, col_s = st.columns([2, 1])
                            with col_t:
                                time_filter = st.radio(
                                    "Khoảng thời gian hiển thị:", 
                                    ["Toàn bộ", "7 ngày gần nhất", "24 giờ gần nhất", "1 giờ gần nhất"], 
                                    horizontal=True
                                )
                            with col_s:
                                sensor_opts = ["Tất cả"] + list(num_cols)
                                selected_sensor = st.selectbox("Chọn chỉ số để vẽ:", sensor_opts)
                                
                            if st.button("📈 Vẽ Biểu Đồ (Render)", type="primary"):
                                st.session_state["do_render_chart"] = True
                                
                            if st.session_state.get("do_render_chart"):
                                plot_cols = num_cols if selected_sensor == "Tất cả" else [selected_sensor]
                                render_optimized_chart(df_render, time_col, plot_cols, time_filter)
                                
                            # 3. Dự báo 24h
                            st.markdown("---")
                            st.subheader("🔮 Mô phỏng & Dự báo Sinh thái 24h")
                            st.markdown("Mô phỏng chu kỳ quang hợp và bức xạ nhiệt trong 24 giờ tới dựa trên thông số hiện tại.")
                            
                            if st.button("▶️ Khởi chạy Dự báo 24h"):
                                with st.spinner("Đang chạy mô phỏng vật lý..."):
                                    # Lấy dòng mới nhất (dòng có thời gian lớn nhất)
                                    df_sorted = df_render.sort_values(time_col)
                                    latest_row = df_sorted.iloc[-1]
                                    current_time_str = str(latest_row[time_col])
                                    
                                    # Trích xuất params
                                    current_params = {}
                                    for col in num_cols:
                                        if pd.notna(latest_row[col]):
                                            current_params[col] = float(latest_row[col])
                                            
                                    try:
                                        result = forecast_24h(current_params, current_time_str)
                                        
                                        # Hiển thị Early Warnings
                                        warnings = result.get("early_warnings", [])
                                        if warnings:
                                            for w in warnings:
                                                if "Nhiệt độ" in w or "nhiệt" in w.lower():
                                                    st.error(f"🌡️ **{w}**")
                                                elif "Oxy" in w or "DO" in w:
                                                    st.error(f"🫧 **{w}**")
                                                else:
                                                    st.warning(f"⚠️ **{w}**")
                                        else:
                                            st.success("✅ Hệ sinh thái dự kiến ổn định. Không phát hiện rủi ro cực đoan trong 24 giờ tới.")
                                            
                                        # Render biểu đồ dự báo
                                        forecast_df = pd.DataFrame(result["timeline"])
                                        st.markdown("**Biểu đồ Dự báo 24h tới (Nhiệt độ, DO, Chỉ số WQI)**")
                                        
                                        # Chỉ vẽ những cột là số
                                        f_cols = [c for c in forecast_df.columns if c not in ["hour_offset", "timestamp"]]
                                        st.line_chart(forecast_df.set_index("timestamp")[f_cols])
                                        
                                        with st.expander("Xem chi tiết Bảng dự báo"):
                                            st.dataframe(forecast_df, use_container_width=True)
                                            
                                    except Exception as e:
                                        st.error(f"Lỗi khi chạy dự báo: {e}")
                        else:
                            st.info("Dữ liệu không có thông số dạng số để vẽ biểu đồ.")
                    else:
                        st.info("Dữ liệu không có cột thời gian để vẽ biểu đồ Time Series.")
