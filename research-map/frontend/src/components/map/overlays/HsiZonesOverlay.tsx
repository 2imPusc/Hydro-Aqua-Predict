import { memo, useMemo } from 'react'
import { GeoJSON } from 'react-leaflet'
import type { AquacultureMap, HsiZones } from '../../../types/monitor'
import { SEVERITY_STYLE, STALE_STYLE, toSeverity } from './StationMarkers'

/** RL-25: HP salinity/temperature are model-gridded (CMEMS/GLORYS), not measured. */
export const HSI_LEGACY_LABEL = 'Kết quả luận văn · chưa kiểm chứng (độ mặn HP là dữ liệu mô hình)'

export const HSI_CLASSES = [
  { id: 'very_suitable', label: 'Rất phù hợp', color: '#22c55e' },
  { id: 'suitable', label: 'Phù hợp', color: '#eab308' },
  { id: 'less_suitable', label: 'Kém / không phù hợp', color: '#ef4444' },
] as const

function styleFor(feature?: GeoJSON.Feature) {
  const label = feature?.properties?.hsi_label
  if (label === 'very_suitable') return { color: '#16a34a', weight: 1.5, fillColor: '#22c55e', fillOpacity: 0.5 }
  if (label === 'suitable') return { color: '#ca8a04', weight: 1.5, fillColor: '#eab308', fillOpacity: 0.5 }
  if (label === 'less_suitable' || label === 'not_suitable') return { color: '#dc2626', weight: 1.5, fillColor: '#ef4444', fillOpacity: 0.5 }
  return { color: '#0f766e', weight: 1.5, fillColor: '#2dd4bf', fillOpacity: 0.18 }
}

const DISPLAY: Record<string, string> = { very_suitable: 'Rất phù hợp', suitable: 'Phù hợp', less_suitable: 'Kém phù hợp', not_suitable: 'Không phù hợp' }

const DRIVER: Record<string, string> = { NH3_derived: 'NH3', Temperature: 'nhiệt độ nước', forecast_rain_6h: 'mưa 6 giờ tới', forecast_wind_6h: 'gió 6 giờ tới', TSS: 'độ đục' }

/**
 * Historical HSI zones (thesis output, unvalidated) — fill = historical suitability class; thick outline =
 * the zone's CURRENT farming status from its station's live advisory (sensor + 6 h weather forecast).
 */
export const HsiZonesOverlay = memo(function HsiZonesOverlay({ zones, aquacultureMap, stale }: { zones: HsiZones; aquacultureMap?: AquacultureMap | null; stale?: boolean }) {
  const data = useMemo(() => ({ type: 'FeatureCollection', features: zones.features }) as GeoJSON.FeatureCollection, [zones])
  const advisory = useMemo(() => new Map((aquacultureMap?.features ?? []).map(item => [String(item.properties?.station_serial ?? ''), item.properties ?? {}])), [aquacultureMap])
  const statusOf = (station: string) => {
    const props = advisory.get(station)
    return { props, style: stale ? { ...SEVERITY_STYLE.UNKNOWN, label: STALE_STYLE.label } : SEVERITY_STYLE[toSeverity(props?.severity)] }
  }
  const style = (feature?: GeoJSON.Feature) => {
    const base = styleFor(feature)
    if (!aquacultureMap) return base
    const { style: status } = statusOf(String(feature?.properties?.anchor_station ?? ''))
    return { ...base, color: status.color, weight: 3.5, opacity: 0.95, dashArray: stale ? '6 4' : undefined }
  }
  return <GeoJSON key={`${zones.observed_at || 'zones'}-${aquacultureMap?.generated_at ?? ''}-${stale}`} data={data} style={style} onEachFeature={(feature, layer) => {
    const station = String(feature.properties?.anchor_station ?? '')
    const label = DISPLAY[String(feature.properties?.hsi_label)] ?? 'Không xác định'
    const { props, style: status } = statusOf(station)
    const drivers = (props?.drivers as Array<{ metric: string; severity: string }> | undefined ?? []).filter(d => d.severity === 'WATCH' || d.severity === 'WARNING').map(d => DRIVER[d.metric] ?? d.metric)
    const missing = (props?.drivers as Array<{ metric: string; severity: string }> | undefined ?? []).filter(d => d.severity === 'UNKNOWN').map(d => DRIVER[d.metric] ?? d.metric)
    const why = drivers.length ? `do ${drivers.join(', ')}` : missing.length ? `thiếu ${missing.join(', ')}` : ''
    layer.bindTooltip(`<b>${station}</b> · hiện trạng: <b>${status.label}</b>${why ? ` (${why})` : ''}<br/>HSI lịch sử: ${label}`, { sticky: true })
  }} />
})
