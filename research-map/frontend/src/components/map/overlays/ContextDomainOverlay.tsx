import { memo, useMemo } from 'react'
import { GeoJSON } from 'react-leaflet'
import type { ContextDomain } from '../../../types/monitor'

const styleFor = (outlineOnly: boolean) => (feature?: GeoJSON.Feature) => feature?.properties?.kind === 'context_domain_boundary'
  ? { color: '#2563eb', weight: 1, dashArray: '3 4', fillOpacity: 0 }
  : { color: '#0284c7', weight: 1, fillColor: '#38bdf8', fillOpacity: outlineOnly ? 0 : .13 }

/** Water-clipped 5 km acquisition domain around the station registry. */
export const ContextDomainOverlay = memo(function ContextDomainOverlay({ domain, dataKey, outlineOnly = false }: { domain: ContextDomain; dataKey: string; outlineOnly?: boolean }) {
  const data = useMemo(() => ({ ...domain, features: domain.features.filter(feature => feature.properties?.kind !== 'station_network_hull') }) as GeoJSON.FeatureCollection, [domain])
  return <GeoJSON key={`${dataKey}-${outlineOnly}`} data={data} style={styleFor(outlineOnly)}
    onEachFeature={(feature, layer) => layer.bindTooltip(feature.properties?.kind === 'station_network_hull'
      ? `Network hull · ${feature.properties?.station_count} trạm`
      : `Phạm vi context ${feature.properties?.water_clipped ? 'trên mặt nước' : ''} · buffer ${feature.properties?.buffer_m / 1000} km`)} />
})
