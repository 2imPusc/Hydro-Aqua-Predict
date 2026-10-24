import { memo, useCallback } from 'react'
import { GeoJSON } from 'react-leaflet'
import type { BathymetryVectorLayer } from '../../../types/monitor'

type Props = {
  bands: BathymetryVectorLayer | null
  contours: BathymetryVectorLayer | null
  showBands: boolean
  showContours: boolean
  showSlope: boolean
  onSample: (latitude: number, longitude: number) => void
}

export function bathymetryColor(feature: GeoJSON.Feature | undefined, showSlope: boolean) {
  const value = Number(feature?.properties?.depth_m ?? 0)
  const slope = Number(feature?.properties?.slope_degrees ?? 0)
  if (showSlope) return slope >= 18 ? '#991b1b' : slope >= 9 ? '#ea580c' : slope >= 4 ? '#facc15' : '#0ea5e9'
  // Continuous ramp keeps the subtle 0–1.2 m variation of this shallow SDB
  // scene rather than collapsing it into a single “< 1 m” class.
  const ratio = Math.max(0, Math.min(1, value / 2))
  return `hsl(${195 + ratio * 30} 78% ${76 - ratio * 43}%)`
}

const popup = (feature: GeoJSON.Feature) => {
  const p = feature.properties ?? {}
  return `<b>Bãi triều (vệ tinh SDB ~100 m)</b><br/>Độ sâu: ${p.depth_band ?? p.depth_m ?? '—'}<br/><small>Chỉ nghiên cứu, không dùng cho hàng hải. Bấm để xem độ sâu tại điểm.</small>`
}
const contourStyle = (feature?: GeoJSON.Feature) => ({ color: Number(feature?.properties?.depth_m) >= 5 ? '#1e3a8a' : '#334155', weight: .8, opacity: .72 })

/** Copernicus SDB depth bands (or slope classes) and contours; clicking a band samples depth. */
export const BathymetryOverlay = memo(function BathymetryOverlay({ bands, contours, showBands, showContours, showSlope, onSample }: Props) {
  const bandStyle = useCallback((feature?: GeoJSON.Feature) => {
    const color = bathymetryColor(feature, showSlope)
    return { color, fillColor: color, weight: 0, opacity: 0, fillOpacity: showSlope ? .38 : .55 }
  }, [showSlope])
  return <>
    {showBands && bands?.status === 'ready' && <GeoJSON key={`bands-${bands.artifact_version ?? ''}-${bands.lod ?? ''}`} data={bands} style={bandStyle} onEachFeature={(feature, layer) => {
      layer.bindPopup(popup(feature))
      layer.on('click', event => onSample(event.latlng.lat, event.latlng.lng))
    }} />}
    {showContours && contours?.status === 'ready' && <GeoJSON key={`contours-${contours.artifact_version ?? ''}-${contours.lod ?? ''}`} data={contours} style={contourStyle} onEachFeature={(feature, layer) => layer.bindTooltip(`Đường mức ${String(feature.properties?.depth_m).replace('.', ',')} m`)} />}
  </>
})
