import { memo, useMemo } from 'react'
import { GeoJSON, Marker } from 'react-leaflet'
import type { FlowArtifact } from '../../../types/monitor'
import { arrowIcon, bearingBetween, type Lod } from '../mapConfig'

/** Precomputed, water-clipped flow rays plus research-only current/station compatibility edges. */
export const FlowArtifactOverlay = memo(function FlowArtifactOverlay({ artifact, lod }: { artifact: FlowArtifact; lod: Lod }) {
  const visible = useMemo(() => {
    const rays = artifact.features.filter(feature => feature.properties?.kind === 'flow_ray')
    return artifact.features.filter(feature => feature.properties?.kind === 'current_supported_station_edge').concat(rays)
  }, [artifact])
  const data = useMemo(() => ({ ...artifact, features: visible }) as GeoJSON.FeatureCollection, [artifact, visible])
  const arrows = useMemo(() => visible.map((feature, index) => {
    if (feature.properties?.kind === 'flow_ray' || feature.geometry.type !== 'LineString') return null
    const coordinates = feature.geometry.coordinates as [number, number][]
    if (coordinates.length < 3) return null
    const middle = Math.floor(coordinates.length / 2)
    const [from, to] = [coordinates[middle - 1], coordinates[middle]]
    const color = feature.properties?.kind === 'flow_streamline' ? '#005fcc' : '#ea580c'
    return <Marker key={`precomputed-flow-arrow-${index}`} position={[to[1], to[0]]} icon={arrowIcon(bearingBetween(from, to), color, 0)} />
  }), [visible])
  const rayWeight = lod === 'high' ? 1.5 : 1.25
  return <>
    <GeoJSON key={artifact.artifact_id} data={data} style={feature => feature?.properties?.kind === 'flow_ray'
      ? { color: '#0b5fc1', weight: rayWeight, opacity: .82 }
      : { color: '#ea580c', weight: 2.8, opacity: .95 }} onEachFeature={(feature, layer) => layer.bindTooltip(
        feature.properties?.kind === 'flow_ray'
          ? `Tia dòng chảy nội suy theo nước · snapshot ${artifact.snapshot_id.slice(0, 8)}`
          : `Current compatibility (research only) · ${feature.properties?.station_a} -> ${feature.properties?.station_b}`,
      )} />
    {arrows}
  </>
})
