import { memo } from 'react'
import { GeoJSON } from 'react-leaflet'
import type { StationNetwork } from '../../../types/monitor'

const STYLE = { color: '#64748b', weight: 1.35, opacity: .68, dashArray: '3 4' }

/**
 * Static water connectivity only: never draw a current direction arrow here.
 * Dynamic flow is rendered by FlowArtifactOverlay.
 */
export const StationNetworkOverlay = memo(function StationNetworkOverlay({ network, dataKey }: { network: StationNetwork; dataKey: string }) {
  return <GeoJSON key={dataKey} data={network} style={STYLE} onEachFeature={(feature, layer) => layer.bindTooltip(`Static water connectivity: ${feature.properties?.station_a} <-> ${feature.properties?.station_b} · ${feature.properties?.water_distance_km} km`)} />
})
