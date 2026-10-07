import sys

from pathlib import Path



import folium

import pandas as pd

import plotly.graph_objects as go

import streamlit as st

from pyproj import Transformer

from streamlit_folium import st_folium




sys.path.insert(0, str(Path(__file__).resolve().parents[1]))



from core.pipeline import run_pipeline



st.set_page_config(layout="wide", page_title="GreenLab - Virtual Sensor Network")





@st.cache_data

def load_station_coordinates():

    try:

        df = pd.read_csv("data/haiphong/clean_data.csv")[

            ["Station", "Station_Name", "X", "Y"]

        ].drop_duplicates()



        proj_str = (

            "+proj=tmerc +lat_0=0 +lon_0=105.75 +k=0.9999 +x_0=500000 "

            "+y_0=0 +ellps=WGS84 +units=m +no_defs"

        )

        transformer = Transformer.from_crs(proj_str, "EPSG:4326", always_xy=True)



        lats, lons = [], []

        for _, row in df.iterrows():

            lon, lat = transformer.transform(row["Y"], row["X"])

            lats.append(lat)

            lons.append(lon)



        df["Lat"] = lats

        df["Lon"] = lons

        return df.set_index("Station")

    except Exception as exc:

        st.error(f"Lỗi load tọa độ: {exc}")

        return pd.DataFrame()





def refresh_pipeline(target_station: str, forecast_horizon: int = 24, show_feedback: bool = False):

    with st.spinner("Đang tải dữ liệu demo và chạy pipeline..."):

        result = run_pipeline(target_station, "haiphong", "cobia", forecast_horizon=forecast_horizon)



    if result and result.get("status") == "success":

        st.session_state["pipeline_result"] = result

        st.session_state.pop("pipeline_error", None)

        if show_feedback:

            st.success("Cập nhật thành công!")

        return



    st.session_state.pop("pipeline_result", None)

    st.session_state["pipeline_error"] = (result or {}).get("message", "Lỗi không xác định")

    if show_feedback:

        st.error(st.session_state["pipeline_error"])





coords_df = load_station_coordinates()



st.title("Dashboard")

st.markdown(

    "Hệ thống Demo thời gian thực sử dụng **Local Imputation + Spatial Extrapolation + Hybrid Forecasting**."

)



st.sidebar.header("🕹️ Bảng Điều Khiển")

target_station = "06M26042804"



if "pipeline_bootstrapped" not in st.session_state:

    st.session_state["pipeline_bootstrapped"] = True

    st.session_state["last_horizon"] = 1

    refresh_pipeline(target_station, forecast_horizon=1, show_feedback=False)



if st.sidebar.button("🚀 Quét Lại Sensor (Refresh)", type="primary"):

    refresh_pipeline(target_station, forecast_horizon=st.session_state.get("last_horizon", 1), show_feedback=True)



if "pipeline_error" in st.session_state:

    st.error(st.session_state["pipeline_error"])



if "pipeline_result" not in st.session_state:

    st.info("👈 Không tải được dữ liệu ban đầu. Hãy bấm 'Quét Lại Sensor (Refresh)' ở bên trái để thử lại.")

    st.stop()



tab_dash, tab_model = st.tabs(["🚀 Dashboard", "🧪 Model Evaluation"])



with tab_dash:

    data = st.session_state["pipeline_result"]

    anchor_data = data["anchor_classification"]



if data.get("warning"):

    st.warning(data["warning"])



col1, col2, col3 = st.columns(3)

with col1:

    st.metric("📍 Trạm Vật lý (Anchor)", "Bến Bèo (NB2)", "Hoạt động tốt")

with col2:

    wqi_score = anchor_data["score"]

    st.metric("🏆 Điểm WQI", f"{wqi_score:.2f} / 100", anchor_data["label"])

with col3:

    st.metric("🕒 Thời điểm cập nhật", data["timestamp"])



col_map, col_details = st.columns([5, 2])



    with col_details:

        st.subheader("📊 Hồ sơ Trạm Gốc")

        measured = anchor_data["params"]["measured"]

        imputed = anchor_data["params"]["imputed"]



        all_params = {}

        for key, value in measured.items():

            if key.startswith("month"): continue

            all_params[key] = {"Value": f"{value:.2f}", "Source": "🟢 Sensor"}

        for key, value in imputed.items():

            if key.startswith("month"): continue

            all_params[key] = {"Value": f"{value:.2f}", "Source": "🤖 AI Imputer"}



        df_params = pd.DataFrame.from_dict(all_params, orient="index")

        st.dataframe(df_params, use_container_width=True)



    with col_map:

        st.subheader("🗺️ Bản đồ Trạm Ảo (Spatial Extrapolation)")



        anchor_lat = 20.7307

        anchor_lon = 107.0553

        if "NB2" in coords_df.index:

            anchor_lat = coords_df.loc["NB2", "Lat"]

            anchor_lon = coords_df.loc["NB2", "Lon"]



        map_view = folium.Map(location=[anchor_lat, anchor_lon], zoom_start=11, tiles="CartoDB positron")



        def get_wqi_color(label):

            lowered = label.lower()

            if "rất" in lowered:

                return "green"

            if "chưa" in lowered:

                return "red"

            return "orange"



        anchor_color = get_wqi_color(anchor_data["label"])

        folium.Marker(

            [anchor_lat, anchor_lon],

            popup=f"<b>Trạm Gốc (NB2)</b><br>WQI: {wqi_score:.1f} - {anchor_data['label']}",

            icon=folium.Icon(color=anchor_color, icon="star"),

        ).add_to(map_view)



        virtual_stations = data.get("virtual_stations", {})

        for station_id, station_data in virtual_stations.items():

            if station_id not in coords_df.index:

                continue



            lat = coords_df.loc[station_id, "Lat"]

            lon = coords_df.loc[station_id, "Lon"]

            name = coords_df.loc[station_id, "Station_Name"]

            station_wqi = station_data.get("wqi", {"score": 0, "label": "Unknown"})



            popup_html = f"<b>{station_id} - {name}</b><br>"

            popup_html += f"WQI: <b>{station_wqi['score']:.1f}</b> ({station_wqi['label']})<br><hr>"

            popup_html += f"<b>Chi tiết {len(station_data['values'])} thông số:</b><br>"

            popup_html += "<div style='max-height: 200px; overflow-y: auto; font-size: 11px;'>"

            popup_html += "<table style='width: 100%; border-collapse: collapse;'>"

            popup_html += (

                "<tr style='background-color: #f2f2f2;'>"

                "<th style='border: 1px solid #ddd; padding: 4px; text-align: left;'>Chỉ số</th>"

                "<th style='border: 1px solid #ddd; padding: 4px; text-align: right;'>Giá trị</th>"

                "<th style='border: 1px solid #ddd; padding: 4px; text-align: left;'>Nguồn</th>"

                "</tr>"

            )



            for param_name, param_value in station_data["values"].items():

                param_source = station_data["imputed_by"].get(param_name, "unknown")

                color = "blue" if param_source == "xgboost_spatial" else "gray"

                popup_html += (

                    f"<tr><td style='border: 1px solid #ddd; padding: 4px; color: {color}; font-weight: bold;'>{param_name}</td>"

                    f"<td style='border: 1px solid #ddd; padding: 4px; color: {color}; text-align: right;'>{param_value:.2f}</td>"

                    f"<td style='border: 1px solid #ddd; padding: 4px; color: {color};'><i>{param_source}</i></td></tr>"

                )

            popup_html += "</table></div>"



            marker_color = get_wqi_color(station_wqi["label"])

            folium.Marker(

                [lat, lon],

                popup=folium.Popup(popup_html, max_width=350),

                icon=folium.Icon(color=marker_color, icon="cloud"),

            ).add_to(map_view)



        st_folium(map_view, height=600, width=1200)



    st.divider()



    st.subheader("🔭 Trạm Quan Sát Chi Tiết (Thực tế & Dự báo)")



    horizon_options = {

        "1 giờ (1h)": 1,

        "24 giờ (1 ngày)": 24,

        "168 giờ (1 tuần)": 168

    }

    

    selected_horizon_label = st.selectbox(

        "Khoảng thời gian dự báo:",

        list(horizon_options.keys()),

        index=0

    )

    selected_horizon = horizon_options[selected_horizon_label]

    

    if st.session_state.get("last_horizon") != selected_horizon:

        st.session_state["last_horizon"] = selected_horizon

        refresh_pipeline(target_station, forecast_horizon=selected_horizon, show_feedback=False)

        st.rerun()



    historical_records = data.get("history", [])



    if historical_records:

        station_choices = [f"{target_station} (Trạm Gốc Anchor)"]

        if data["virtual_stations"]:

            station_choices.extend(list(data["virtual_stations"].keys()))



        selected_station = st.selectbox("👉 Chọn Trạm để xem biểu đồ:", station_choices)



        is_anchor = "Trạm Gốc" in selected_station

        actual_station_id = target_station if is_anchor else selected_station



        all_param_names = []

        if is_anchor:

            all_param_names = list(historical_records[-1]["anchor_classification"]["params"]["imputed"].keys())

        elif actual_station_id in historical_records[-1]["virtual_stations"]:

            all_param_names = list(historical_records[-1]["virtual_stations"][actual_station_id]["values"].keys())



        all_param_names = [p for p in all_param_names if not p.startswith("month")]



        ts_data = {"timestamp": [], "WQI": []}

        for param_name in all_param_names:

            ts_data[param_name] = []



        for record in historical_records:

            ts_data["timestamp"].append(record["timestamp"])

            if is_anchor:

                params = record["anchor_classification"]["params"]["imputed"]

                wqi = record["anchor_classification"]["score"]

            else:

                if actual_station_id in record["virtual_stations"]:

                    station_values = record["virtual_stations"][actual_station_id]

                    params = station_values["values"]

                    wqi = station_values.get("wqi", {}).get("score", 0)

                else:

                    params = {}

                    wqi = 0



            ts_data["WQI"].append(wqi)

            for param_name in all_param_names:

                ts_data[param_name].append(params.get(param_name, 0))



        df_history = pd.DataFrame(ts_data)



        df_forecast = None

        forecast = data.get("forecast", {})

        if is_anchor and "timeline" in forecast and forecast["timeline"]:

            df_forecast = pd.DataFrame(forecast["timeline"])

            if forecast.get("early_warnings"):

                st.error(f"🚨 **CẢNH BÁO:** {forecast['early_warnings'][0]}")



        st.markdown("#### Biến thiên Từng Chỉ số")

    

        plot_params = ["WQI"] + all_param_names

    

        for param_name in plot_params:

            fig = go.Figure()

        

            if param_name in df_history.columns:

                fig.add_trace(

                    go.Scatter(

                        x=df_history["timestamp"],

                        y=df_history[param_name],

                        name=f"Thực tế",

                        mode="lines+markers",

                        line=dict(color="#0068c9" if param_name != "WQI" else "purple", width=3),

                    )

                )

            

            if is_anchor and df_forecast is not None and param_name in df_forecast.columns:

                last_hist_time = df_history["timestamp"].iloc[-1] if not df_history.empty else None

                last_hist_val = df_history[param_name].iloc[-1] if not df_history.empty else None

            

                f_timestamps = df_forecast["timestamp"].tolist()

                f_values = df_forecast[param_name].tolist()

            

                if last_hist_time and last_hist_val is not None:

                    f_timestamps.insert(0, last_hist_time)

                    f_values.insert(0, last_hist_val)

                

                fig.add_trace(

                    go.Scatter(

                        x=f_timestamps,

                        y=f_values,

                        name=f"Dự báo XGBoost" if param_name != "WQI" else "Dự báo (Quy đổi)",

                        mode="lines+markers",

                        line=dict(color="#ef4444", width=3, dash="dot"),

col_map, col_details = st.columns([5, 2])

    with col_details:
        st.subheader("📊 Hồ sơ Trạm Gốc")
        measured = anchor_data["params"]["measured"]
        imputed = anchor_data["params"]["imputed"]

        all_params = {}
        for key, value in measured.items():
            if key.startswith("month"): continue
            all_params[key] = {"Value": f"{value:.2f}", "Source": "🟢 Sensor"}
        for key, value in imputed.items():
            if key.startswith("month"): continue
            all_params[key] = {"Value": f"{value:.2f}", "Source": "🤖 AI Imputer"}

        df_params = pd.DataFrame.from_dict(all_params, orient="index")
        st.dataframe(df_params, use_container_width=True)

    with col_map:
        st.subheader("🗺️ Bản đồ Trạm Ảo (Spatial Extrapolation)")

        anchor_lat = 20.7307
        anchor_lon = 107.0553
        if "NB2" in coords_df.index:
            anchor_lat = coords_df.loc["NB2", "Lat"]
            anchor_lon = coords_df.loc["NB2", "Lon"]

        map_view = folium.Map(location=[anchor_lat, anchor_lon], zoom_start=11, tiles="CartoDB positron")

        def get_wqi_color(label):
            lowered = label.lower()
            if "rất" in lowered:
                return "green"
            if "chưa" in lowered:
                return "red"
            return "orange"

        anchor_color = get_wqi_color(anchor_data["label"])
        folium.Marker(
            [anchor_lat, anchor_lon],
            popup=f"<b>Trạm Gốc (NB2)</b><br>WQI: {wqi_score:.1f} - {anchor_data['label']}",
            icon=folium.Icon(color=anchor_color, icon="star"),
        ).add_to(map_view)

        virtual_stations = data.get("virtual_stations", {})
        for station_id, station_data in virtual_stations.items():
            if station_id not in coords_df.index:
                continue

            lat = coords_df.loc[station_id, "Lat"]
            lon = coords_df.loc[station_id, "Lon"]
            name = coords_df.loc[station_id, "Station_Name"]
            station_wqi = station_data.get("wqi", {"score": 0, "label": "Unknown"})

            popup_html = f"<b>{station_id} - {name}</b><br>"
            popup_html += f"WQI: <b>{station_wqi['score']:.1f}</b> ({station_wqi['label']})<br><hr>"
            popup_html += f"<b>Chi tiết {len(station_data['values'])} thông số:</b><br>"
            popup_html += "<div style='max-height: 200px; overflow-y: auto; font-size: 11px;'>"
            popup_html += "<table style='width: 100%; border-collapse: collapse;'>"
            popup_html += (
                "<tr style='background-color: #f2f2f2;'>"
                "<th style='border: 1px solid #ddd; padding: 4px; text-align: left;'>Chỉ số</th>"
                "<th style='border: 1px solid #ddd; padding: 4px; text-align: right;'>Giá trị</th>"
                "<th style='border: 1px solid #ddd; padding: 4px; text-align: left;'>Nguồn</th>"
                "</tr>"
            )

            for param_name, param_value in station_data["values"].items():
                param_source = station_data["imputed_by"].get(param_name, "unknown")
                color = "blue" if param_source == "xgboost_spatial" else "gray"
                popup_html += (
                    f"<tr><td style='border: 1px solid #ddd; padding: 4px; color: {color}; font-weight: bold;'>{param_name}</td>"
                    f"<td style='border: 1px solid #ddd; padding: 4px; color: {color}; text-align: right;'>{param_value:.2f}</td>"
                    f"<td style='border: 1px solid #ddd; padding: 4px; color: {color};'><i>{param_source}</i></td></tr>"
                )
            popup_html += "</table></div>"

            marker_color = get_wqi_color(station_wqi["label"])
            folium.Marker(
                [lat, lon],
                popup=folium.Popup(popup_html, max_width=350),
                icon=folium.Icon(color=marker_color, icon="cloud"),
            ).add_to(map_view)

        st_folium(map_view, height=600, width=1200)

    st.divider()

    st.subheader("🔭 Trạm Quan Sát Chi Tiết (Thực tế & Dự báo)")

    horizon_options = {
        "1 giờ (1h)": 1,
        "24 giờ (1 ngày)": 24,
        "168 giờ (1 tuần)": 168
    }
    
    selected_horizon_label = st.selectbox(
        "Khoảng thời gian dự báo:",
        list(horizon_options.keys()),
        index=0
    )
    selected_horizon = horizon_options[selected_horizon_label]
    
    if st.session_state.get("last_horizon") != selected_horizon:
        st.session_state["last_horizon"] = selected_horizon
        refresh_pipeline(target_station, forecast_horizon=selected_horizon, show_feedback=False)
        st.rerun()

    historical_records = data.get("history", [])

    if historical_records:
        station_choices = [f"{target_station} (Trạm Gốc Anchor)"]
        if data["virtual_stations"]:
            station_choices.extend(list(data["virtual_stations"].keys()))

        selected_station = st.selectbox("👉 Chọn Trạm để xem biểu đồ:", station_choices)

        is_anchor = "Trạm Gốc" in selected_station
        actual_station_id = target_station if is_anchor else selected_station

        all_param_names = []
        if is_anchor:
            all_param_names = list(historical_records[-1]["anchor_classification"]["params"]["imputed"].keys())
        elif actual_station_id in historical_records[-1]["virtual_stations"]:
            all_param_names = list(historical_records[-1]["virtual_stations"][actual_station_id]["values"].keys())

        all_param_names = [p for p in all_param_names if not p.startswith("month")]

        ts_data = {"timestamp": [], "WQI": []}
        for param_name in all_param_names:
            ts_data[param_name] = []

        for record in historical_records:
            ts_data["timestamp"].append(record["timestamp"])
            if is_anchor:
                params = record["anchor_classification"]["params"]["imputed"]
                wqi = record["anchor_classification"]["score"]
            else:
                if actual_station_id in record["virtual_stations"]:
                    station_values = record["virtual_stations"][actual_station_id]
                    params = station_values["values"]
                    wqi = station_values.get("wqi", {}).get("score", 0)
                else:
                    params = {}
                    wqi = 0

            ts_data["WQI"].append(wqi)
            for param_name in all_param_names:
                ts_data[param_name].append(params.get(param_name, 0))

        df_history = pd.DataFrame(ts_data)

        df_forecast = None
        forecast = data.get("forecast", {})
        if is_anchor and "timeline" in forecast and forecast["timeline"]:
            df_forecast = pd.DataFrame(forecast["timeline"])
            if forecast.get("early_warnings"):
                st.error(f"🚨 **CẢNH BÁO:** {forecast['early_warnings'][0]}")

        st.markdown("#### Biến thiên Từng Chỉ số")
    
        plot_params = ["WQI"] + all_param_names
    
        for param_name in plot_params:
            fig = go.Figure()
        
            if param_name in df_history.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_history["timestamp"],
                        y=df_history[param_name],
                        name=f"Thực tế",
                        mode="lines+markers",
                        line=dict(color="#0068c9" if param_name != "WQI" else "purple", width=3),
                    )
                )
            
            if is_anchor and df_forecast is not None and param_name in df_forecast.columns:
                last_hist_time = df_history["timestamp"].iloc[-1] if not df_history.empty else None
                last_hist_val = df_history[param_name].iloc[-1] if not df_history.empty else None
            
                f_timestamps = df_forecast["timestamp"].tolist()
                f_values = df_forecast[param_name].tolist()
            
                if last_hist_time and last_hist_val is not None:
                    f_timestamps.insert(0, last_hist_time)
                    f_values.insert(0, last_hist_val)
                
                fig.add_trace(
                    go.Scatter(
                        x=f_timestamps,
                        y=f_values,
                        name=f"Dự báo XGBoost" if param_name != "WQI" else "Dự báo (Quy đổi)",
                        mode="lines+markers",
                        line=dict(color="#ef4444", width=3, dash="dot"),
                    )
                )
            
            fig.update_layout(
                title=f"Chỉ số: {param_name}",
                height=350,
                margin=dict(l=20, r=20, t=40, b=10),
                xaxis_title="Thời gian",
                hovermode="x unified"
            )
            st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("Chưa có dữ liệu lịch sử.")

with tab_model:
    st.subheader('🧪 Đánh giá Mô hình bằng Backtesting')
    st.markdown('Cơ chế Backtesting: Hệ thống sẽ tự động giấu đi dữ liệu thực tế gần nhất, yêu cầu XGBoost dự báo mù, sau đó đối chiếu kết quả dự báo với dữ liệu đã giấu để đánh giá độ chính xác thực tế.')
    
    eval_horizon_label = st.selectbox('Chọn khoảng thời gian Backtest (Ground Truth):', list(horizon_options.keys()), index=0, key='eval_horizon_label')
    eval_horizon = horizon_options[eval_horizon_label]
    
    if st.button('Chạy Backtest Ngay Lập Tức', type='primary'):
        with st.spinner(f'Đang trích xuất dữ liệu và chạy Backtest cho {eval_horizon} giờ...'):
            try:
                from core.fetch import fetch_raw
                from core.forecast import train_and_forecast_xgboost
                df_raw = fetch_raw(target_station)
                if df_raw.empty or len(df_raw) < eval_horizon + 25:
                    st.error('Dữ liệu không đủ để chia tập train và test.')
                else:
                    df = df_raw.copy()
                    if 'fetchedAt' in df.columns:
                        df['fetchedAt'] = pd.to_datetime(df['fetchedAt'], utc=True)
                        df.set_index('fetchedAt', inplace=True)
                    df_hourly = df[['Temperature', 'pH', 'NH4', 'TSS']].resample('1h').mean()
                    df_hourly = df_hourly.interpolate(method='linear').dropna()
                    if len(df_hourly) <= eval_horizon + 24:
                        st.error('Sau khi resample, dữ liệu không đủ.')
                    else:
                        train_df = df_hourly.iloc[:-eval_horizon]
                        test_df = df_hourly.iloc[-eval_horizon:]
                        preds_dict = {}
                        for param in ['Temperature', 'pH', 'NH4', 'TSS']:
                            train_subset = train_df.tail(168)
                            preds_dict[param] = train_and_forecast_xgboost(train_subset, param, horizon=eval_horizon)
                        st.markdown('#### Đối chiếu Thực tế vs Dự báo (Backtest)')
                        for param in ['Temperature', 'pH', 'NH4', 'TSS']:
                            fig = go.Figure()
                            plot_start = len(train_df) - 48 if len(train_df) > 48 else 0
                            context_df = df_hourly.iloc[plot_start:]
                            fig.add_trace(go.Scatter(x=context_df.index, y=context_df[param], name='Thực tế (Ground Truth)', mode='lines+markers', line=dict(color='#0068c9', width=2)))
                            fig.add_trace(go.Scatter(x=test_df.index, y=preds_dict[param], name='Dự báo XGBoost (Mù)', mode='lines+markers', line=dict(color='#ef4444', width=3, dash='dot')))
                            fig.update_layout(title=f'Chỉ số: {param}', height=350, margin=dict(l=20, r=20, t=40, b=10), xaxis_title='Thời gian', hovermode='x unified')
                            st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f'Có lỗi xảy ra: {e}')
