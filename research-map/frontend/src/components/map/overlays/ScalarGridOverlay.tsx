import { memo, useMemo } from 'react'
import L from 'leaflet'
import { GeoJSON } from 'react-leaflet'
import type { Layer } from '../../../types/monitor'
import { LABEL, escapeHtml } from '../mapConfig'

/** Scalar grid (rain, sea level, MLD …) drawn as ONE GeoJSON layer with a blue/cyan ramp. */
export const ScalarGridOverlay = memo(function ScalarGridOverlay({ layer, dataKey }: { layer: Layer; dataKey: string }) {
  const data = useMemo(() => ({
    type: 'FeatureCollection',
    features: (layer.geojson?.features ?? []).filter(feature => feature.geometry.type === 'Point' || feature.geometry.type === 'Polygon'),
  }) as GeoJSON.FeatureCollection, [layer])
  const [minimum, maximum] = useMemo(() => {
    const values = data.features.map(feature => Number(feature.properties?.value)).filter(Number.isFinite)
    return values.length ? [Math.min(...values), Math.max(...values)] : [0, 1]
  }, [data])
  const colorFor = (feature?: GeoJSON.Feature) => {
    const value = Number(feature?.properties?.value)
    const ratio = maximum > minimum ? (value - minimum) / (maximum - minimum) : .5
    // Blue/cyan scale avoids a dominant green fill for rain.
    return `hsl(${215 - ratio * 35} 78% 52%)`
  }
  return <GeoJSON
    key={dataKey}
    data={data}
    style={feature => { const color = colorFor(feature); return { color, fillColor: color, fillOpacity: .3, weight: .4 } }}
    pointToLayer={(feature, latlng) => { const color = colorFor(feature); return L.circleMarker(latlng, { radius: 6, color, fillColor: color, fillOpacity: .3, weight: 1 }) }}
    onEachFeature={(feature, leafletLayer) => {
      const value = Number(feature.properties?.value)
      leafletLayer.bindPopup(`<b>${escapeHtml(LABEL[layer.layer])}</b><br/>${escapeHtml(feature.properties?.variable)}: ${Number.isFinite(value) ? value.toFixed(3) : '—'} ${escapeHtml(feature.properties?.unit ?? '')}<hr/>${escapeHtml(layer.provenance?.source)}<br/>valid: ${escapeHtml(layer.provenance?.valid_at)}`)
    }}
  />
})
