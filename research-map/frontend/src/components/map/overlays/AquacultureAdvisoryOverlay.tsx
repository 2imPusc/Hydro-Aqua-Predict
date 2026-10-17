import { CircleMarker, Popup } from 'react-leaflet'
import type { AquacultureMap } from '../../../types/monitor'

type Driver = { metric: string; value: unknown; unit: string }

/** Advisory circles per sensor point. Not mounted by the monitor view (station markers carry severity); kept for reuse. */
export function AquacultureAdvisoryOverlay({ artifact }: { artifact: AquacultureMap | null }) {
  if (!artifact || artifact.status !== 'ready') return null
  return <>{artifact.features.map((feature, index) => {
    if (feature.geometry?.type !== 'Point') return null
    const [longitude, latitude] = feature.geometry.coordinates as [number, number]
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const props = (feature.properties ?? {}) as Record<string, any>
    const watch = props.severity === 'WATCH'
    const warning = props.severity === 'WARNING'
    const color = warning ? '#dc2626' : (watch ? '#ea580c' : '#0f766e')
    const metrics = props.metrics ?? {}
    const weather = props.weather ?? {}
    const drivers: Driver[] = props.drivers ?? []
    return <CircleMarker key={`aquaculture-${index}`} center={[latitude, longitude]} radius={warning ? 22 : (watch ? 18 : 14)} pathOptions={{ color, weight: 3, fillColor: color, fillOpacity: warning ? .5 : .28 }}>
      <Popup><b>{artifact.mode === 'mock' ? `MOCK | ${props.scenario}` : 'LIVE | sensor advisory'}</b><br />
        Mức: {props.severity}<br />NH4: {metrics.NH4 ?? '—'} · NH3 quy đổi: {props.nh3_derived_mg_l ?? '—'} mg/L<br />
        Nhiệt độ: {metrics.Temperature ?? '—'} °C · pH: {metrics.pH ?? '—'}<br />
        Mưa 6h: {weather.rain_6h_mm ?? '—'} mm · Gió 6h: {weather.wind_6h_kmh ?? '—'} km/h<br />
        {drivers.length ? <><hr />Yếu tố: {drivers.map(item => `${item.metric}=${item.value} ${item.unit}`).join(', ')}</> : <><hr />Chưa có yếu tố cần theo dõi.</>}
        <hr /><small>Advisory theo điểm sensor; không thay đổi phân loại nuôi trồng.</small>
      </Popup>
    </CircleMarker>
  })}</>
}
