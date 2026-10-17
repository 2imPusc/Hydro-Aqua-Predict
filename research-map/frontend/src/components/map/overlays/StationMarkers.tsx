import { memo, useMemo } from 'react'
import L from 'leaflet'
import { Marker, Popup } from 'react-leaflet'
import type { AquacultureMap, Stations } from '../../../types/monitor'

export type Severity = 'WARNING' | 'WATCH' | 'UNKNOWN' | 'NORMAL'
export const SEVERITY_STYLE: Record<Severity, { color: string; label: string; tone: 'danger' | 'warn' | 'neutral' | 'ok' }> = {
  WARNING: { color: '#dc2626', label: 'Cảnh báo', tone: 'danger' },
  WATCH: { color: '#f59e0b', label: 'Cần theo dõi', tone: 'warn' },
  UNKNOWN: { color: '#94a3b8', label: 'Không rõ', tone: 'neutral' },
  NORMAL: { color: '#16a34a', label: 'Bình thường', tone: 'ok' },
}
export const toSeverity = (value: unknown): Severity => {
  const upper = String(value ?? 'UNKNOWN').toUpperCase()
  return upper === 'WARNING' || upper === 'WATCH' || upper === 'UNKNOWN' ? upper : 'NORMAL'
}

/**
 * The pilot has one physical sensor. Its advisory is the regional status;
 * mock mode may still provide per-point variants for demonstrations.
 */
export function advisoryForStation(aquacultureMap: AquacultureMap | null | undefined, station: unknown, index: number) {
  const advisories = aquacultureMap?.features ?? []
  return advisories.find(item => String(item.properties?.station_serial ?? '') === String(station ?? ''))
    ?? (aquacultureMap?.mode === 'mock' ? advisories[index % Math.max(1, advisories.length)] : advisories[0])
}

const iconCache = new Map<string, L.DivIcon>()
function stationIcon(color: string, mock: boolean) {
  const key = `${color}-${mock}`
  let icon = iconCache.get(key)
  if (!icon) {
    icon = L.divIcon({
      className: 'station-marker',
      html: `<span class="station-dot${mock ? ' is-mock' : ''}" style="background:${color}"></span>`,
      iconSize: [16, 16], iconAnchor: [8, 8],
    })
    iconCache.set(key, icon)
  }
  return icon
}

type Driver = { metric: string; value: unknown; unit: string }

export const StationMarkers = memo(function StationMarkers({ stations, aquacultureMap }: { stations: Stations; aquacultureMap?: AquacultureMap | null }) {
  const items = useMemo(() => stations.features.map((feature, index) => {
    if (feature.geometry?.type !== 'Point') return null
    const [longitude, latitude] = feature.geometry.coordinates as [number, number]
    const properties = feature.properties ?? {}
    const advisory = advisoryForStation(aquacultureMap, properties.station, index)
    const status = SEVERITY_STYLE[toSeverity(advisory?.properties?.severity)]
    return { index, latitude, longitude, properties, advisory, status }
  }), [stations, aquacultureMap])
  const mock = aquacultureMap?.mode === 'mock'
  return <>{items.map(item => item && (
    <Marker key={`station-${String(item.properties.station ?? item.index)}-${item.index}`} position={[item.latitude, item.longitude]} icon={stationIcon(item.status.color, mock)}>
      <Popup>
        {mock && <div className="popup-mock">MÔ PHỎNG · không phải dữ liệu thật</div>}
        <b>{String(item.properties.station ?? 'Trạm')}</b><br />{String(item.properties.name ?? '')}<br />
        <b style={{ color: item.status.color }}>{item.status.label}</b>
        {item.advisory?.properties?.drivers?.length ? <><hr />Yếu tố: {(item.advisory.properties.drivers as Driver[]).map(driver => `${driver.metric}=${driver.value} ${driver.unit}`).join(', ')}</> : null}
      </Popup>
    </Marker>
  ))}</>
})
