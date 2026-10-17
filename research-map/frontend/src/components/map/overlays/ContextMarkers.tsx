import { memo } from 'react'
import { CircleMarker, Marker, Popup } from 'react-leaflet'
import type { Layer } from '../../../types/monitor'
import { LABEL, arrowIcon } from '../mapConfig'

const COLOR: Partial<Record<Layer['layer'], string>> = { wind: '#0ea5e9', rain: '#3b82f6', wave: '#7c3aed' }

function LayerPopup({ layer, props, calm }: { layer: Layer; props: Record<string, unknown>; calm?: boolean }) {
  return <Popup>
    <b>{LABEL[layer.layer]}</b>
    {calm && <div>Dòng yếu / hướng không ổn định</div>}
    {Object.entries(props).map(([key, value]) => <div key={key}>{key}: {String(value)}</div>)}
    <hr />{layer.provenance?.source}<br />valid: {layer.provenance?.valid_at}
  </Popup>
}

/** Provider-sampled point vectors (wave, …): arrows when a bearing exists, dots otherwise. */
export const ContextMarkers = memo(function ContextMarkers({ layer }: { layer: Layer }) {
  const color = COLOR[layer.layer] ?? '#f97316'
  return <>{layer.geojson?.features.map((feature, index) => {
    if (feature.geometry.type !== 'Point') return null
    const [longitude, latitude] = feature.geometry.coordinates as [number, number]
    const props = (feature.properties ?? {}) as Record<string, string | number | null>
    const isCalm = layer.layer === 'current' && Number(props.speed_m_s ?? 0) < .35
    const hasDirection = !isCalm && props.display_bearing_degrees !== undefined && props.display_bearing_degrees !== null
    const bearing = Number(props.display_bearing_degrees ?? 0)
    const speed = Number(props.speed_m_s ?? props.height_m ?? 0)
    if (!hasDirection) return <CircleMarker key={`${layer.layer}-${index}`} center={[latitude, longitude]} radius={isCalm ? 4 : 6} pathOptions={{ color, fillColor: color, fillOpacity: isCalm ? .25 : .55 }}><LayerPopup layer={layer} props={props} calm={isCalm} /></CircleMarker>
    return <Marker key={`${layer.layer}-${index}`} position={[latitude, longitude]} icon={arrowIcon(bearing, color, speed, layer.layer === 'wind')}>
      <LayerPopup layer={layer} props={props} />
    </Marker>
  })}</>
})
