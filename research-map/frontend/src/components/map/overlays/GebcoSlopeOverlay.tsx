import { memo, useCallback } from 'react'
import { GeoJSON } from 'react-leaflet'
import type { BathymetryVectorLayer } from '../../../types/monitor'

/** Bottom-slope classes from the ~460 m GEBCO grid (backend SLOPE_EDGES_DEG 0 / 0.5 / 1 / 2°). */
export const GEBCO_SLOPE_CLASSES = [
  { color: '#bae6fd', label: '< 0,5°' },
  { color: '#fde68a', label: '0,5–1°' },
  { color: '#fb923c', label: '1–2°' },
  { color: '#b91c1c', label: '≥ 2°' },
]

/** GEBCO-derived bottom slope; the whole region, unlike the tidal-flat-only SDB slope. */
export const GebcoSlopeOverlay = memo(function GebcoSlopeOverlay({ slope }: { slope: BathymetryVectorLayer | null }) {
  const style = useCallback((feature?: GeoJSON.Feature) => {
    const color = GEBCO_SLOPE_CLASSES[Number(feature?.properties?.class ?? 0)]?.color ?? '#94a3b8'
    return { color, fillColor: color, weight: 0, opacity: 0, fillOpacity: 0.55 }
  }, [])
  if (!slope?.features?.length) return null
  return <GeoJSON key={`gebco-slope-${slope.features.length}`} data={slope} style={style}
    onEachFeature={(feature, layer) => layer.bindTooltip(`Dốc ${feature.properties?.label ?? ''}`, { sticky: true })} />
})
