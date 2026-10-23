import { memo, useMemo } from 'react'
import { GeoJSON } from 'react-leaflet'
import type { HsiZones } from '../../../types/monitor'

/** RL-25: HP salinity/temperature are model-gridded (CMEMS/GLORYS), not measured. */
export const HSI_LEGACY_LABEL = 'Kết quả luận văn · chưa kiểm chứng (độ mặn HP là dữ liệu mô hình)'

export const HSI_CLASSES = [
  { id: 'very_suitable', label: 'Rất phù hợp', color: '#22c55e' },
  { id: 'suitable', label: 'Phù hợp', color: '#eab308' },
  { id: 'less_suitable', label: 'Kém / không phù hợp', color: '#ef4444' },
] as const

function styleFor(feature?: GeoJSON.Feature) {
  const label = feature?.properties?.hsi_label
  if (label === 'very_suitable') return { color: '#16a34a', weight: 1.5, fillColor: '#22c55e', fillOpacity: 0.3 }
  if (label === 'suitable') return { color: '#ca8a04', weight: 1.5, fillColor: '#eab308', fillOpacity: 0.3 }
  if (label === 'less_suitable' || label === 'not_suitable') return { color: '#dc2626', weight: 1.5, fillColor: '#ef4444', fillOpacity: 0.3 }
  return { color: '#0f766e', weight: 1.5, fillColor: '#2dd4bf', fillOpacity: 0.18 }
}

const DISPLAY: Record<string, string> = { very_suitable: 'Rất phù hợp', suitable: 'Phù hợp', less_suitable: 'Kém phù hợp', not_suitable: 'Không phù hợp' }

/** Legacy historical HSI zones (thesis output). Not validated; display only. */
export const HsiZonesOverlay = memo(function HsiZonesOverlay({ zones }: { zones: HsiZones }) {
  const data = useMemo(() => ({ type: 'FeatureCollection', features: zones.features }) as GeoJSON.FeatureCollection, [zones])
  return <GeoJSON key={zones.observed_at || 'zones'} data={data} style={styleFor} onEachFeature={(feature, layer) => {
    const label = DISPLAY[String(feature.properties?.hsi_label)] ?? 'Không xác định'
    layer.bindTooltip(`<b>HSI · ${HSI_LEGACY_LABEL}</b><br/>Phân loại: ${label}<br/>Điểm HSI: ${feature.properties?.hsi ?? '-'}<br/>Trạm gốc: ${feature.properties?.anchor_station ?? ''}`)
  }} />
})
