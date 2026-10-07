import sys
from pathlib import Path

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pyproj import Transformer
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import DATA_DIR, STATIONS, map_reference_station_for_sensor
from core.pipeline import run_pipeline
from core.forecast_evaluation import ledger_summary
from core.spatial_overlay import build_observed_hsi_partition_demo_overlays, display_water_position
from core.chart_timeline import bridge_forecast_from_current

st.set_page_config(
    page_title='GreenLab Realtime Demo',
    page_icon='🌊',
    layout='wide'
)

@st.cache_data
def load_station_coordinates():
    try:
        df = pd.read_csv(DATA_DIR / 'map' / 'station_coordinates.csv')
        return df.set_index('Station')
    except Exception as exc:
        st.error(f'Lỗi load tọa độ: {exc}')
        return pd.DataFrame()

GRANULARITY_OPTIONS = {
    'Phút': 'minute',
    'Giờ': 'hour',
    'Ngày': 'day',
}

HORIZON_OPTIONS = {
    'minute': {
        '15 phút': 15,
        '30 phút': 30,
        '60 phút': 60,
    },
    'hour': {
        '1 giờ': 1,
        '24 giờ (1 ngày)': 24,
        '72 giờ (3 ngày)': 72,
    },
    'day': {
        '3 ngày': 3,
        '7 ngày': 7,
    },
}


def split_line_at_time_gaps(timestamps, values, max_gap_minutes: int = 5):
    """Insert Plotly nulls so observations are never drawn across missing time."""
    x_values, y_values = [], []
    previous = None
    gaps = 0
    for timestamp, value in zip(timestamps, values):
        current = pd.to_datetime(timestamp, utc=True)
        if previous is not None and current - previous > pd.Timedelta(minutes=max_gap_minutes):
            # A null y-value makes Plotly start a new segment at this timestamp.
            x_values.append(previous)
            y_values.append(None)
            gaps += 1
        x_values.append(current)
        y_values.append(value)
        previous = current
    return x_values, y_values, gaps


def render_station_forecast_panel(data: dict, anchor_serial: str) -> None:
    """Station selector with historical/current/projected values and safety state."""
    monitored_parameters = (
        'Temperature', 'pH', 'NH4', 'NH3', 'TSS', 'DO', 'Salinity', 'COD',
    )
    direct_sensor_parameters = {'Temperature', 'pH', 'NH4', 'NH3', 'TSS'}
    inferred_parameters = {'DO', 'Salinity'}
    records = data.get('history', [])
    virtual_current = data.get('virtual_stations', {})
    choices = {anchor_serial: f'{anchor_serial} — sensor anchor (NB1)'}
    choices.update({station_id: f'{station_id} — trạm ảo không gian' for station_id in virtual_current})
    station_id = st.selectbox('Chọn điểm trạm', list(choices), format_func=choices.get, key='station_forecast_selector')
    is_anchor = station_id == anchor_serial
    current = data['anchor_classification'] if is_anchor else virtual_current.get(station_id, {})
    current_wqi = ({'score': float(current.get('score', 0)) * 100, 'label': current.get('label', 'Unknown')}
                   if is_anchor else current.get('wqi', {'score': 0, 'label': 'Unknown'}))
    future = data.get('station_future', {}).get(station_id, [])
    future_scores = [float(item.get('wqi', {}).get('score', 0)) for item in future]
    minimum_future = min(future_scores) if future_scores else None
    state = ('Ổn định' if minimum_future is not None and minimum_future >= 75 else
             'Cần theo dõi' if minimum_future is not None and minimum_future >= 50 else
             'Cảnh báo' if minimum_future is not None else 'Chưa có dự báo')
    status_col, current_col, future_col = st.columns(3)
    with status_col:
        st.metric('Trạng thái điểm trạm', state, current_wqi.get('label', 'Unknown'))
    with current_col:
        st.metric('WQI hiện tại', f"{float(current_wqi.get('score', 0)):.1f}/100")
    with future_col:
        st.metric('WQI thấp nhất trong 15 phút tới', f'{minimum_future:.1f}/100' if minimum_future is not None else 'Chưa có')

    if not records:
        st.info('Chưa có chuỗi lịch sử để dựng biểu đồ.')
        return
    if is_anchor:
        current_params = {
            **current.get('params', {}).get('defaulted', {}),
            **current.get('params', {}).get('imputed', {}),
            **current.get('params', {}).get('measured', {}),
        }
    else:
        current_params = current.get('values', {})

    # Keep a stable monitoring grid.  A missing value is clinically relevant:
    # do not hide its chart or fabricate an estimate, show its data state instead.
    parameters = [name for name in monitored_parameters if name in current_params or name in inferred_parameters or name in direct_sensor_parameters]
    st.markdown(f'#### Diễn biến chỉ số — {station_id}')
    chart_columns = st.columns(2)
    for index, parameter in enumerate(parameters):
        with chart_columns[index % 2]:
            history_x, history_y = [], []
            if is_anchor and parameter in {'Temperature', 'pH', 'NH4', 'NH3', 'TSS'}:
                for item in data.get('sensor_chart_history', []):
                    if item.get(parameter) is not None:
                        history_x.append(item['fetchedAt'])
                        history_y.append(item[parameter])
            else:
                for record in records:
                    if is_anchor:
                        params = record['anchor_classification']['params']
                        values = {
                            **params.get('defaulted', {}),
                            **params.get('imputed', {}),
                            **params.get('measured', {}),
                        }
                    else:
                        values = record.get('virtual_stations', {}).get(station_id, {}).get('values', {})
                    if values.get(parameter) is not None:
                        history_x.append(record['timestamp'])
                        history_y.append(values[parameter])
            future_x = [item['timestamp'] for item in future if item.get('values', {}).get(parameter) is not None]
            future_y = [item['values'][parameter] for item in future if item.get('values', {}).get(parameter) is not None]
            current_value = current_params.get(parameter)
            has_current = current_value is not None and pd.notna(current_value)
            figure = go.Figure()
            if history_x:
                history_plot_x, history_plot_y, gap_count = split_line_at_time_gaps(history_x, history_y)
                figure.add_trace(go.Scatter(
                    x=history_plot_x, y=history_plot_y, mode='lines', name='Lịch sử / hiện tại',
                    connectgaps=False, line={'color': '#64748b'},
                ))
            if has_current:
                figure.add_trace(go.Scatter(
                    x=[data['timestamp']], y=[current_value], mode='markers', name='Điểm hiện tại',
                    marker={'color': '#0f766e', 'size': 9},
                ))
            if future_x:
                forecast_x, forecast_y, _bridged = bridge_forecast_from_current(
                    future_x, future_y,
                    current_timestamp=data.get('timestamp'), current_value=current_value,
                )
                figure.add_trace(go.Scatter(x=forecast_x, y=forecast_y, mode='lines+markers', name='Dự báo 1–15 phút', line={'color': '#f97316', 'dash': 'dash'}))
            source = ('đo trực tiếp từ sensor' if parameter in direct_sensor_parameters
                      else 'nội suy từ các chỉ số sensor' if parameter in inferred_parameters
                      else 'giá trị hỗ trợ cho đánh giá')
            title = f'{parameter} · {source}'
            if not history_x and not future_x and not has_current:
                detail = 'Chưa có giá trị hợp lệ trong dữ liệu hiện có'
                if parameter in inferred_parameters:
                    detail = 'Nội suy chưa khả dụng — cần đủ đầu vào hợp lệ để mô hình chấp nhận'
                figure.add_annotation(
                    text=detail, showarrow=False, x=0.5, y=0.5,
                    xref='paper', yref='paper', font={'color': '#94a3b8', 'size': 13},
                    align='center',
                )
                figure.update_xaxes(visible=False)
                figure.update_yaxes(visible=False)
            elif not future_x:
                figure.add_annotation(
                    text='Chưa có dự báo ngắn hạn', showarrow=False, x=1, y=1,
                    xref='paper', yref='paper', xanchor='right', yanchor='top',
                    font={'color': '#f59e0b', 'size': 11},
                )
            figure.update_layout(title=title, height=260, margin={'l': 20, 'r': 20, 't': 40, 'b': 15}, legend={'orientation': 'h'})
            st.plotly_chart(figure, use_container_width=True, key=f'{station_id}_{parameter}_forecast_chart')
            if history_x and gap_count:
                st.caption(f'Đã ngắt đường tại {gap_count} khoảng thiếu dữ liệu (>5 phút); không nội suy để nối các điểm này.')
    if future:
        source = future[0].get('source', 'unknown')
        source_text = ('sensor NB1: +15 phút từ mô hình; +1 đến +14 phút là nội suy hiển thị'
                       if source == 'sensor_first_forecast'
                       else 'dự báo sensor NB1, sau đó nội suy không gian tới trạm ảo')
        st.caption(f'Nguồn dự báo: {source_text}.')


def refresh_pipeline(
    target_station: str,
    forecast_granularity: str = 'minute',
    forecast_horizon: int = 15,
    show_feedback: bool = False,
    include_legacy_forecast: bool = False,
):
    with st.spinner('Đang tải dữ liệu demo và chạy pipeline...'):
        from core.fetch import fetch_raw
        df_raw = fetch_raw(target_station)
        simulated_now = df_raw['fetchedAt'].max() if not df_raw.empty else None
        
        result = run_pipeline(
            target_station,
            'haiphong',
            'cobia',
            forecast_granularity=forecast_granularity,
            forecast_horizon=forecast_horizon,
            previous_alert=st.session_state.get('aquaculture_alert_state'),
            previous_inferred_do_alert=st.session_state.get('inferred_do_alert_state'),
            previous_forecast_advisory=st.session_state.get('forecast_advisory_state'),
            include_legacy_forecast=include_legacy_forecast,
            now=simulated_now,
        )

    if result and result.get('status') == 'success':
        st.session_state['pipeline_result'] = result
        st.session_state['aquaculture_alert_state'] = result.get('aquaculture_alert', {})
        st.session_state['inferred_do_alert_state'] = result.get('inferred_do_alert', {})
        st.session_state['forecast_advisory_state'] = result.get('forecast_advisory', {})
        st.session_state.pop('pipeline_error', None)
        if show_feedback:
            st.success('Cập nhật thành công!')
        return

    st.session_state.pop('pipeline_result', None)
    st.session_state['pipeline_error'] = (result or {}).get('message', 'Lỗi không xác định')
    if show_feedback:
        st.error(st.session_state['pipeline_error'])

coords_df = load_station_coordinates()

st.title('Dashboard demo')
st.markdown('Hệ thống Demo thời gian thực sử dụng **Local Imputation + Spatial Extrapolation + Hybrid Forecasting**.')

st.sidebar.header('🕹️ Bảng Điều Khiển')
target_station = '06M26042804'
station_info = STATIONS.get(target_station, {})
anchor_reference = station_info.get('weather_location', {})
anchor_reference_id = map_reference_station_for_sensor(target_station) or str(anchor_reference.get('source', 'map_station_NB1')).replace('map_station_', '')

if 'pipeline_bootstrapped' not in st.session_state:
    st.session_state['pipeline_bootstrapped'] = True
    st.session_state['last_granularity'] = 'minute'
    st.session_state['last_horizon'] = 15
    refresh_pipeline(target_station, forecast_granularity='minute', forecast_horizon=15, show_feedback=False)

if st.sidebar.button('🚀 Quét Lại Sensor (Refresh)', type='primary'):
    refresh_pipeline(
        target_station,
        forecast_granularity=st.session_state.get('last_granularity', 'minute'),
        forecast_horizon=st.session_state.get('last_horizon', 15),
        show_feedback=True,
    )

if 'pipeline_error' in st.session_state:
    st.error(st.session_state['pipeline_error'])

if 'pipeline_result' not in st.session_state:
    st.info('👈 Không tải được dữ liệu ban đầu. Hãy bấm "Quét Lại Sensor (Refresh)" ở bên trái để thử lại.')
    st.stop()

tab_dash, tab_model, tab_shadow = st.tabs(['Dashboard', 'Model Evaluation', 'Forecast Shadow'])

with tab_dash:
    data = st.session_state['pipeline_result']
    anchor_data = data['anchor_classification']

    alert = data.get('aquaculture_alert', {})
    inferred = data.get('inferred_do_alert', {})
    technical_notes = []
    if inferred.get('severity') not in {'NORMAL', 'BLOCKED', None}:
        st.warning(f"RỦI RO DO NỘI SUY: {inferred['severity']} — DO dự đoán {inferred.get('predicted_do')} mg/L")
    elif inferred.get('severity') == 'BLOCKED':
        technical_notes.append(f"DO nội suy chưa tạo cảnh báo: {inferred.get('reason', 'model_rejected')}")
    severity = alert.get('severity', 'NORMAL')
    if severity == 'EMERGENCY':
        st.error(f"RỦI RO NUÔI CÁ GIÒ: {severity} — {alert.get('risk_score', 0)}/100")
    elif severity == 'WARNING':
        st.warning(f"RỦI RO NUÔI CÁ GIÒ: {severity} — {alert.get('risk_score', 0)}/100")
    elif severity == 'WATCH':
        st.info(f"RỦI RO NUÔI CÁ GIÒ: {severity} — {alert.get('risk_score', 0)}/100")

    if alert:
        driver_text = ', '.join(
            f"{item['metric']} ({item['status']})" for item in alert.get('drivers', [])
        ) or 'Chưa có chỉ số vượt rule cảnh báo.'
        technical_notes.append(
            f"Độ tin cậy={alert.get('confidence', 'unknown')}; DO trực tiếp="
            f"{'có' if alert.get('sensor_health', {}).get('direct_do_available') else 'chưa có'}; nguyên nhân={driver_text}."
        )
        if severity != 'NORMAL':
            st.markdown('**Hành động đề xuất:** ' + ' • '.join(alert.get('recommended_actions', [])))
        if alert.get('disclaimer'):
            technical_notes.append(alert['disclaimer'])
        health = alert.get('sensor_health', {})
        health_flags = [
            f"{metric}: {', '.join(detail.get('flags', []))}"
            for metric, detail in health.get('metrics', {}).items()
            if detail.get('flags')
        ]
        if health_flags or health.get('data_gap'):
            technical_notes.append('Tình trạng sensor: ' + (' • '.join(health_flags) or 'Có khoảng trống dữ liệu.'))

    if data.get('warning'):
        technical_notes.append(data['warning'])

    future_shadow = data.get('sensor_future', {})
    forecast_advisory = data.get('forecast_advisory', {})
    weather_advisory = data.get('weather_advisory', {})
    if weather_advisory.get('status') == 'ready':
        weather_state = 'Cần theo dõi' if weather_advisory.get('severity') == 'WATCH' else 'Bình thường'
        weather_windows = weather_advisory.get('windows', {})
        weather_3h, weather_6h, weather_24h = (weather_windows.get(f'next_{hours}h', {}) for hours in (3, 6, 24))
        st.markdown('#### Thời tiết dự báo tại điểm tham chiếu')
        weather_col1, weather_col2, weather_col3, weather_col4 = st.columns(4)
        with weather_col1:
            st.metric('Trạng thái thời tiết', weather_state, 'advisory vận hành')
        with weather_col2:
            st.metric('Mưa 3 giờ tới', f"{weather_3h.get('rain_sum_mm', 0):.1f} mm" if weather_3h.get('rain_sum_mm') is not None else 'Chưa có')
        with weather_col3:
            st.metric('Mưa 24 giờ tới', f"{weather_24h.get('rain_sum_mm', 0):.1f} mm" if weather_24h.get('rain_sum_mm') is not None else 'Chưa có')
        with weather_col4:
            st.metric('Gió cực đại 6 giờ', f"{weather_6h.get('max_wind', 0):.1f} km/h" if weather_6h.get('max_wind') is not None else 'Chưa có')
        if weather_advisory.get('drivers'):
            driver_text = ', '.join(f"{item['metric']}={item['value']} {item['unit']}" for item in weather_advisory['drivers'])
            st.info(f'Yếu tố cần theo dõi: {driver_text}.')
        st.caption(weather_advisory.get('disclaimer', 'Weather chỉ dùng làm ngữ cảnh.'))
    elif weather_advisory:
        technical_notes.append(f"Weather advisory chưa sẵn sàng: {weather_advisory.get('reason', 'unknown')}.")
    if forecast_advisory.get('notification_eligible'):
        st.error(
            f"CẢNH BÁO VẬN HÀNH ĐỦ ĐIỀU KIỆN THÔNG BÁO: {forecast_advisory.get('notification_reason')}. "
            "DO là nội suy; cần kiểm tra thực địa ngay, nhưng không tạo Emergency tự động."
        )
    risk_timeline = forecast_advisory.get('timeline', [])
    if risk_timeline:
        max_horizon = max(item['horizon_minutes'] for item in risk_timeline)
        earliest = forecast_advisory.get('earliest_horizon_minutes')
        state_copy = {
            'NORMAL': ('Ổn định', 'Chưa phát hiện ngưỡng rủi ro trong cửa sổ dự báo.'),
            'WATCH': ('Cần theo dõi', 'Có chỉ số dự báo chạm ngưỡng theo dõi.'),
            'WARNING': ('Cảnh báo sớm', 'Có chỉ số dự báo vượt ngưỡng cảnh báo.'),
            'CRITICAL_ADVISORY': ('Cảnh báo sớm nghiêm trọng', 'Cần kiểm tra thực địa ngay.'),
        }.get(forecast_advisory.get('severity'), ('Chưa đủ dữ liệu', 'Forecast chưa sẵn sàng.'))
        state_col, time_col, window_col = st.columns(3)
        with state_col:
            st.metric('Trạng thái dự báo', state_copy[0], state_copy[1])
        with time_col:
            st.metric('Mốc cần chú ý', f'+{earliest} phút' if earliest is not None else 'Không có', 'mốc rủi ro sớm nhất')
        with window_col:
            st.metric('Cửa sổ đang dự báo', f'{max_horizon} phút', '15 / 30 / 60 phút')

        render_station_forecast_panel(data, target_station)

        with st.expander('Chi tiết timeline rủi ro kỹ thuật'):
            st.caption('DO và độ mặn là nội suy; bảng này chỉ là advisory shadow, không kích hoạt notification hay Emergency.')
            risk_view = pd.DataFrame([{
                'Horizon (phút)': item['horizon_minutes'],
                'Mức advisory': item['severity'],
                'DO nội suy': item['inputs'].get('DO_inferred'),
                'Nhiệt độ': item['inputs'].get('Temperature'),
                'NH3 quy đổi': item['inputs'].get('NH3'),
                'Độ mặn nội suy': item['inputs'].get('Salinity_inferred'),
                'Yếu tố': ', '.join(f"{driver['metric']}={driver['value']}" for driver in item['drivers']) or 'Không',
            } for item in risk_timeline])
            st.dataframe(risk_view, use_container_width=True, hide_index=True)
    if future_shadow.get('status') == 'unavailable':
        technical_notes.append(f"Dự báo sensor-first chưa sẵn sàng: {future_shadow.get('reason')}.")

    ledger = data.get('forecast_evaluation', {})
    if ledger.get('issued_records') or ledger.get('resolved_outcomes'):
        technical_notes.append(
            f"Shadow ledger: đã phát hành thêm {ledger.get('issued_records', 0)} forecast, "
            f"đối chiếu thêm {ledger.get('resolved_outcomes', 0)} actual sensor."
        )
    temperature_metrics = [item for item in ledger.get('metrics', []) if item.get('param') == 'Temperature']
    if temperature_metrics:
        best = min(temperature_metrics, key=lambda item: item['mae'])
        technical_notes.append(
            f"Đánh giá Temperature hiện có: n={best['n']}, horizon={best['horizon_minutes']} phút, "
            f"MAE={best['mae']:.3f}°C, RMSE={best['rmse']:.3f}°C."
        )
    if technical_notes:
        with st.expander('Chẩn đoán kỹ thuật', expanded=False):
            for note in technical_notes:
                st.caption(note)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric('📍 Trạm Vật lý (Anchor)', f'{anchor_reference_id} - Cát Bà', 'Hoạt động tốt')
    with col2:
        wqi_score = anchor_data['score']
        st.metric('🏆 Điểm WQI', f'{wqi_score:.2f} / 100', anchor_data['label'])
    with col3:
        st.metric('🕒 Thời điểm cập nhật', data['timestamp'])

    col_map, col_details = st.columns([5, 2])

    with col_details:
        st.subheader('📊 Hồ sơ Trạm Gốc')
        measured = anchor_data['params']['measured']
        imputed = anchor_data['params']['imputed']

        all_params = {}
        for key, value in measured.items():
            if key.startswith('month'): continue
            all_params[key] = {'Value': f'{value:.2f}', 'Source': '🟢 Sensor'}
        for key, value in imputed.items():
            if key.startswith('month'): continue
            all_params[key] = {'Value': f'{value:.2f}', 'Source': '🤖 AI Imputer'}

        df_params = pd.DataFrame.from_dict(all_params, orient='index')
        st.dataframe(df_params, use_container_width=True)

    with col_map:
        st.subheader('🗺️ Bản đồ Trạm Ảo (Spatial Extrapolation)')

        st.caption('Vùng HSI lịch sử theo đường nước: mỗi trạm có bán kính từ HSI quan trắc, chặn tối đa 5 km; cell chỉ thuộc trạm gần nhất theo water-path. Đây là lớp demo, không dùng cho alert.')

        anchor_lat = anchor_reference.get('latitude', 20.71894498573044)
        anchor_lon = anchor_reference.get('longitude', 107.042635855355)
        if anchor_reference_id in coords_df.index:
            anchor_lat = coords_df.loc[anchor_reference_id, 'Lat']
            anchor_lon = coords_df.loc[anchor_reference_id, 'Lon']

        anchor_display = display_water_position(float(anchor_lon), float(anchor_lat))
        anchor_lat, anchor_lon = anchor_display['latitude'], anchor_display['longitude']

        map_view = folium.Map(location=[anchor_lat, anchor_lon], zoom_start=11, tiles='CartoDB positron')

        def get_wqi_color(label):
            lowered = label.lower()
            if 'rất' in lowered: return 'green'
            if 'chưa' in lowered: return 'red'
            return 'orange'

        def get_wqi_region_color(label):
            lowered = str(label or '').lower()
            if 'rất' in lowered:
                return '#16a34a'  # green: very suitable
            if 'chưa' in lowered or 'không' in lowered:
                return '#dc2626'  # red: unsuitable
            return '#eab308'      # yellow: suitable / needs attention

        anchor_color = get_wqi_color(anchor_data['label'])
        folium.Marker(
            [anchor_lat, anchor_lon],
            popup=(f"<b>Sensor anchor → {anchor_reference_id}</b><br>Coordinate source: historical station reference"
                   f"<br>Display snap to water: {anchor_display['offset_m']:.0f} m<br>WQI: {wqi_score:.1f} - {anchor_data['label']}"),
            icon=folium.Icon(color=anchor_color, icon='star'),
        ).add_to(map_view)

        # Keep validation/legacy layers out of the demo surface.  Their
        # evidence remains in experiment artifacts until it is ready to ship.
        spatial_mode = 'water_path_demo'
        virtual_stations = data.get('virtual_stations', {})

        try:
            hsi_period, demo_overlays = build_observed_hsi_partition_demo_overlays(max_radius_km=5.0)
            palette = ['#0ea5e9', '#14b8a6', '#8b5cf6', '#f97316', '#ec4899', '#84cc16']
            for index, overlay in enumerate(demo_overlays):
                color = palette[index % len(palette)]
                folium.GeoJson(
                    overlay['geometry'], name='Historical HSI radius areas',
                    style_function=lambda _feature, color=color: {
                        'color': color, 'weight': 1.5, 'fillColor': color, 'fillOpacity': .16,
                    },
                    tooltip=(f"Vùng HSI lịch sử | trạm neo={overlay['anchor_station']} | "
                             f"HSI={overlay['hsi']:.3f} ({overlay['hsi_label']}) | "
                             "cell thuộc trạm gần nhất theo water-path"),
                ).add_to(map_view)
            if not demo_overlays:
                st.caption(f'Không tạo được vùng HSI historical water-path cho snapshot {hsi_period}.')
            if spatial_mode == 'HSI research partition (v2)':
                hsi_overlays = build_hsi_partition_overlays()
                for overlay in hsi_overlays:
                    folium.GeoJson(
                        overlay['geometry'], name='HSI research partition v2',
                        style_function=lambda _feature: {'color': '#0f766e', 'weight': 1.5, 'fillColor': '#2dd4bf', 'fillOpacity': .24},
                        tooltip=(f"HSI research gate | anchor={overlay['anchor_station']} | water-path {overlay['distance_bin_km']} km | "
                                 f"90% bound={overlay.get('mean_bound')} | not used by alerts"),
                    ).add_to(map_view)
                if not hsi_overlays:
                    st.caption('HSI research v2: no water-path bin currently passes the 90% / 30-pair gate; all cells are not applicable.')
            if spatial_mode in {'Demo HSI legacy (tất cả trạm)', 'Cả hai lớp'}:
                legacy_period, legacy_overlays = legacy_hsi_demo_overlays()
                for overlay in legacy_overlays:
                    overlay_wqi_label = (
                        anchor_data['label'] if overlay['station'] == anchor_reference_id
                        else virtual_stations.get(overlay['station'], {}).get('wqi', {}).get('label', 'Unknown')
                    )
                    region_color = get_wqi_region_color(overlay_wqi_label)
                    confidence_style = {
                        'high': {'opacity': .32, 'weight': 2.2, 'dash': None},
                        'medium': {'opacity': .20, 'weight': 1.6, 'dash': '6 4'},
                        'low': {'opacity': .10, 'weight': 1.0, 'dash': '2 5'},
                    }[overlay['confidence']['band']]
                    folium.GeoJson(
                        overlay['geometry'], name='Legacy HSI demo',
                        style_function=lambda _feature, color=region_color, cs=confidence_style: {
                            'color': color, 'weight': cs['weight'], 'fillColor': color,
                            'fillOpacity': cs['opacity'], 'dashArray': cs['dash'],
                        },
                        tooltip=(f"HSI legacy demo | {overlay['station']} | {overlay['period']} | "
                                 f"WQI hiện tại={overlay_wqi_label} | "
                                 f"HSI={overlay['hsi']:.3f} ({overlay['hsi_label']}) | Euclidean R={overlay['radius_km']:.1f} km | "
                                 f"heuristic confidence={overlay['confidence']['band']} ({overlay['confidence']['score']:.2f}, n={overlay['confidence']['n_neighbours']}) | land clipped | not validated"),
                    ).add_to(map_view)
                st.caption(f'HSI legacy demo: {len(legacy_overlays)} trạm, snapshot {legacy_period}; màu vùng theo WQI hiện tại của trạm (xanh/vàng/đỏ), độ đậm và viền theo confidence heuristic. Vòng Euclidean được cắt đất liền, không dùng alert.')
            if spatial_mode in {'Validated shadow (gate mới)', 'Cả hai lớp'}:
                for overlay in build_shadow_overlays(anchor_lon, anchor_lat):
                    folium.GeoJson(
                        overlay['geometry'], name='Spatial applicability shadow',
                        style_function=lambda _feature: {'color': '#7c3aed', 'weight': 2, 'fillColor': '#a78bfa', 'fillOpacity': .22},
                        tooltip=(f"Research shadow only: {overlay['parameter']} | {overlay['inner_km']:.0f}-{overlay['outer_km']:.0f} km | coverage target {overlay['coverage_target']:.0%}. Land is clipped."),
                    ).add_to(map_view)
            folium.LayerControl(collapsed=True).add_to(map_view)
        except (FileNotFoundError, ValueError) as exc:
            st.caption(f'Spatial applicability overlay unavailable: {exc}')

        for station_id, station_data in virtual_stations.items():
            if station_id not in coords_df.index: continue

            source_lat = float(coords_df.loc[station_id, 'Lat'])
            source_lon = float(coords_df.loc[station_id, 'Lon'])
            display_position = display_water_position(source_lon, source_lat)
            lat = display_position['latitude']
            lon = display_position['longitude']
            name = coords_df.loc[station_id, 'Station_Name']
            station_wqi = station_data.get('wqi', {'score': 0, 'label': 'Unknown'})

            popup_html = f"<b>{station_id} - {name}</b><br>"
            popup_html += f"WQI: <b>{station_wqi['score']:.1f}</b> ({station_wqi['label']})<br><hr>"
            if display_position['offset_m'] > 1:
                popup_html += f"<i>Marker display snapped to water by {display_position['offset_m']:.0f} m; source coordinate preserved.</i><br>"
            popup_html += f"<b>Chi tiết {len(station_data['values'])} thông số:</b><br>"
            popup_html += "<div style='max-height: 200px; overflow-y: auto; font-size: 11px;'>"
            popup_html += "<table style='width: 100%; border-collapse: collapse;'>"
            popup_html += "<tr style='background-color: #f2f2f2;'><th style='border: 1px solid #ddd; padding: 4px; text-align: left;'>Chỉ số</th><th style='border: 1px solid #ddd; padding: 4px; text-align: right;'>Giá trị</th><th style='border: 1px solid #ddd; padding: 4px; text-align: left;'>Nguồn</th></tr>"

            for param_name, param_value in station_data['values'].items():
                param_source = station_data['imputed_by'].get(param_name, 'unknown')
                color = 'blue' if param_source == 'xgboost_spatial' else 'gray'
                popup_html += f"<tr><td style='border: 1px solid #ddd; padding: 4px; color: {color}; font-weight: bold;'>{param_name}</td><td style='border: 1px solid #ddd; padding: 4px; color: {color}; text-align: right;'>{param_value:.2f}</td><td style='border: 1px solid #ddd; padding: 4px; color: {color};'><i>{param_source}</i></td></tr>"
            popup_html += "</table></div>"

            marker_color = get_wqi_color(station_wqi['label'])
            folium.Marker(
                [lat, lon],
                popup=folium.Popup(popup_html, max_width=350),
                icon=folium.Icon(color=marker_color, icon='cloud'),
            ).add_to(map_view)

        st_folium(map_view, height=600, width=1200)

    st.divider()

    st.subheader('🔭 Trạm Quan Sát Chi Tiết (Thực tế & Dự báo)')
    
    selected_granularity_label = st.selectbox(
        'Độ phân giải dự báo:',
        list(GRANULARITY_OPTIONS.keys()),
        index=list(GRANULARITY_OPTIONS.values()).index(st.session_state.get('last_granularity', 'hour')),
    )
    selected_granularity = GRANULARITY_OPTIONS[selected_granularity_label]
    horizon_options = HORIZON_OPTIONS[selected_granularity]
    horizon_values = list(horizon_options.values())
    current_horizon = st.session_state.get('last_horizon', horizon_values[0])
    if st.session_state.get('last_granularity') != selected_granularity or current_horizon not in horizon_values:
        selected_horizon_index = 0
    else:
        selected_horizon_index = horizon_values.index(current_horizon)
    selected_horizon_label = st.selectbox(
        'Khoảng thời gian dự báo:',
        list(horizon_options.keys()),
        index=selected_horizon_index,
    )
    selected_horizon = horizon_options[selected_horizon_label]

    st.caption('Dashboard refresh only runs the fast sensor-first forecast. The legacy XGBoost forecast runs on demand.')
    if st.button('Run legacy XGBoost forecast for selected horizon', key='run_legacy_forecast'):
        st.session_state['last_horizon'] = selected_horizon
        st.session_state['last_granularity'] = selected_granularity
        refresh_pipeline(
            target_station,
            forecast_granularity=selected_granularity,
            forecast_horizon=selected_horizon,
            show_feedback=True,
            include_legacy_forecast=True,
        )
        st.rerun()

    if (
        st.session_state.get('last_horizon') != selected_horizon
        or st.session_state.get('last_granularity') != selected_granularity
    ):
        st.session_state['last_horizon'] = selected_horizon
        st.session_state['last_granularity'] = selected_granularity
        refresh_pipeline(
            target_station,
            forecast_granularity=selected_granularity,
            forecast_horizon=selected_horizon,
            show_feedback=False,
        )
        st.rerun()

    historical_records = data.get('history', [])

    if False and historical_records:  # Replaced by render_station_forecast_panel above.
        station_choices = [f"{target_station} (Trạm Gốc Anchor)"]
        if data['virtual_stations']:
            station_choices.extend(list(data['virtual_stations'].keys()))

        selected_station = st.selectbox('👉 Chọn Trạm để xem biểu đồ:', station_choices)

        is_anchor = 'Trạm Gốc' in selected_station
        actual_station_id = target_station if is_anchor else selected_station

        all_param_names = []
        if is_anchor:
            all_param_names = list(historical_records[-1]['anchor_classification']['params']['imputed'].keys())
        elif actual_station_id in historical_records[-1]['virtual_stations']:
            all_param_names = list(historical_records[-1]['virtual_stations'][actual_station_id]['values'].keys())

        all_param_names = [p for p in all_param_names if not p.startswith('month')]

        ts_data = {'timestamp': [], 'WQI': []}
        for param_name in all_param_names: ts_data[param_name] = []

        for record in historical_records:
            ts_data['timestamp'].append(record['timestamp'])
            if is_anchor:
                params = record['anchor_classification']['params']['imputed']
                wqi = record['anchor_classification']['score']
            else:
                if actual_station_id in record['virtual_stations']:
                    station_values = record['virtual_stations'][actual_station_id]
                    params = station_values['values']
                    wqi = station_values.get('wqi', {}).get('score', 0)
                else:
                    params = {}
                    wqi = 0

            ts_data['WQI'].append(wqi)
            for param_name in all_param_names:
                ts_data[param_name].append(params.get(param_name, 0))

        df_history = pd.DataFrame(ts_data)

        df_forecast = None
        forecast = data.get('forecast', {})
        if is_anchor and 'timeline' in forecast and forecast['timeline']:
            df_forecast = pd.DataFrame(forecast['timeline'])
            if forecast.get('early_warnings'):
                st.error(f"🚨 **CẢNH BÁO:** {forecast['early_warnings'][0]}")

        st.markdown('#### Biến thiên Từng Chỉ số')
    
        plot_params = ['WQI'] + all_param_names
    
        for param_name in plot_params:
            fig = go.Figure()
        
            if param_name in df_history.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_history['timestamp'],
                        y=df_history[param_name],
                        name='Thực tế',
                        mode='lines+markers',
                        line=dict(color='#0068c9' if param_name != 'WQI' else 'purple', width=3),
                    )
                )
            
            if is_anchor and df_forecast is not None and param_name in df_forecast.columns:
                last_hist_time = df_history['timestamp'].iloc[-1] if not df_history.empty else None
                last_hist_val = df_history[param_name].iloc[-1] if not df_history.empty else None
            
                f_timestamps = df_forecast['timestamp'].tolist()
                f_values = df_forecast[param_name].tolist()
            
                if last_hist_time and last_hist_val is not None:
                    f_timestamps.insert(0, last_hist_time)
                    f_values.insert(0, last_hist_val)
                
                fig.add_trace(
                    go.Scatter(
                        x=f_timestamps,
                        y=f_values,
                        name='Dự báo XGBoost' if param_name != 'WQI' else 'Dự báo (Quy đổi)',
                        mode='lines+markers',
                        line=dict(color='#ef4444', width=3, dash='dot'),
                    )
                )
            
            fig.update_layout(
                title=f'Chỉ số: {param_name}',
                height=350,
                margin=dict(l=20, r=20, t=40, b=10),
                xaxis_title='Thời gian',
                hovermode='x unified'
            )
            st.plotly_chart(fig, use_container_width=True)

    elif not historical_records:
        st.info('Chưa có dữ liệu lịch sử.')

with tab_model:
    st.subheader('🧪 Đánh giá Mô hình bằng Backtesting')
    st.markdown('Cơ chế Backtesting: Hệ thống sẽ tự động giấu đi dữ liệu thực tế gần nhất, yêu cầu XGBoost dự báo mù, sau đó đối chiếu kết quả dự báo với dữ liệu đã giấu để đánh giá độ chính xác thực tế.')
    
    eval_horizon_options = HORIZON_OPTIONS['hour']
    eval_horizon_label = st.selectbox('Chọn khoảng thời gian Backtest (Ground Truth):', list(eval_horizon_options.keys()), index=0, key='eval_horizon_label')
    eval_horizon = eval_horizon_options[eval_horizon_label]
    
    if st.button('Chạy Backtest Ngay Lập Tức', type='primary'):
        with st.spinner(f'Đang trích xuất dữ liệu và chạy Backtest cho {eval_horizon} giờ...'):
            try:
                from core.fetch import fetch_raw
                from core.forecast import train_and_forecast_xgboost
                df_raw = fetch_raw(target_station)
                if df_raw.empty or len(df_raw) < eval_horizon + 25:
                    st.error('Dữ liệu không đủ để chia tập train và test. Cần thêm dữ liệu lịch sử.')
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

with tab_shadow:
    st.subheader('Forecast Sensor-First — Shadow Evaluation')
    ledger_view = ledger_summary()
    stat1, stat2, stat3 = st.columns(3)
    stat1.metric('Forecast đã phát hành', ledger_view['forecast_records'])
    stat2.metric('Outcome đã đối chiếu', ledger_view['outcome_records'])
    stat3.metric('Forecast mới nhất', ledger_view['latest_issued_at'] or 'Chưa có')
    metrics = pd.DataFrame(ledger_view['metrics'])
    if metrics.empty:
        st.info('Chưa có forecast đến hạn để tính metric. Hãy để shadow runner tiếp tục chạy.')
    else:
        st.dataframe(metrics.sort_values(['param', 'horizon_minutes', 'model']), use_container_width=True)
        st.caption('DO và độ mặn nội suy chỉ được lưu provenance; chưa có sensor/ground truth độc lập để chấm metric.')
