import { memo, useEffect, useMemo } from 'react'
import L from 'leaflet'
import { Circle, Tooltip, useMap } from 'react-leaflet'
import type { AquacultureMap, Stations } from '../../../types/monitor'
import type { ReliabilityVn } from '../../../types/research'
import { advisoryForStation, SEVERITY_STYLE, STALE_STYLE, toSeverity } from './StationMarkers'

/**
 * How far the single sensor (NB1, salinity regime "marine") can stand for a place: same regime as NB1 →
 * usable, transitional → weak, estuarine → not representative (H4, 1 km cells near observed QN stations).
 */
export const RELIABILITY_CLASSES = {
  same: { color: [20, 150, 140] as const, alpha: 0.34, label: 'Tin cậy — cùng chế độ nước với NB1' },
  transitional: { color: [217, 160, 40] as const, alpha: 0.3, label: 'Kém tin cậy — vùng chuyển tiếp' },
  other: { color: [120, 120, 130] as const, alpha: 0.32, label: 'Không đại diện — nước lợ cửa sông' },
}
/** Radius of the farming-status halo around each station (m). */
export const STATUS_HALO_M = 2500

type Props = { data: ReliabilityVn | null; water?: GeoJSON.Geometry | null; dataKey: string }

const classOf = (regime: string | undefined, nb1: string): keyof typeof RELIABILITY_CLASSES =>
  regime === nb1 ? 'same' : regime === 'transitional' ? 'transitional' : 'other'

function trace(ctx: CanvasRenderingContext2D, map: L.Map, geometry: GeoJSON.Geometry) {
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.type === 'MultiPolygon' ? geometry.coordinates : []
  for (const polygon of polygons) for (const ring of polygon) ring.forEach(([lon, lat], i) => {
    const p = map.latLngToContainerPoint([lat, lon])
    if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y)
  })
}

/** Reliability zones as one soft canvas field (1 km cells drawn as blurred discs, clipped to water). */
export const ReliabilityZonesOverlay = memo(function ReliabilityZonesOverlay({ data, water, dataKey }: Props) {
  const map = useMap()
  const cells = useMemo(() => {
    if (!data || data.status !== 'ready' || !data.layer) return []
    const nb1 = data.nb1_regime?.nb1_observed_regime_class_by_nearest ?? data.nb1_regime?.nb1_model_derived_class ?? 'marine'
    return data.layer.features.map(f => ({ lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], cls: classOf(f.properties?.regime_class, nb1) }))
  }, [data])
  useEffect(() => {
    if (!cells.length) return undefined
    const pane = 'reliability-zones'
    if (!map.getPane(pane)) { const el = map.createPane(pane); el.style.zIndex = '340'; el.style.pointerEvents = 'none' }
    const canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide') as HTMLCanvasElement
    canvas.style.pointerEvents = 'none'
    map.getPane(pane)!.appendChild(canvas)
    const draw = () => {
      const size = map.getSize(), ratio = window.devicePixelRatio || 1
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
      canvas.width = size.x * ratio; canvas.height = size.y * ratio
      canvas.style.width = `${size.x}px`; canvas.style.height = `${size.y}px`
      const ctx = canvas.getContext('2d')!
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      ctx.clearRect(0, 0, size.x, size.y)
      if (water) { ctx.beginPath(); trace(ctx, map, water); ctx.clip('evenodd') }
      // ~600 m disc per 1 km cell, softened so the 1 km lattice reads as zones, not dots or squares.
      const c = map.getCenter()
      const r = Math.max(2, Math.abs(map.latLngToContainerPoint([c.lat, c.lng + 0.0068]).x - map.latLngToContainerPoint(c).x))
      ctx.filter = `blur(${Math.max(1, r * 0.45)}px)`
      for (const key of ['other', 'transitional', 'same'] as const) {
        const { color, alpha } = RELIABILITY_CLASSES[key]
        ctx.fillStyle = `rgba(${color[0]},${color[1]},${color[2]},${alpha})`
        ctx.beginPath()
        for (const cell of cells) {
          if (cell.cls !== key) continue
          const p = map.latLngToContainerPoint([cell.lat, cell.lon])
          if (p.x < -r || p.y < -r || p.x > size.x + r || p.y > size.y + r) continue
          ctx.moveTo(p.x + r, p.y); ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
        }
        ctx.fill()
      }
      ctx.filter = 'none'
    }
    draw()
    map.on('moveend zoomend resize viewreset', draw)
    return () => { map.off('moveend zoomend resize viewreset', draw); canvas.remove() }
  }, [map, cells, water, dataKey])
  return null
})

/** Farming-status halo per station (colour = latest advisory; hatched grey when the advisory is stale). */
export const StatusHalos = memo(function StatusHalos({ stations, aquacultureMap, stale }: { stations: Stations | null; aquacultureMap: AquacultureMap | null; stale: boolean }) {
  if (!stations) return null
  return <>{stations.features.map((feature, index) => {
    if (feature.geometry.type !== 'Point') return null
    const [lon, lat] = feature.geometry.coordinates as [number, number]
    const id = feature.properties?.station
    const advisory = advisoryForStation(aquacultureMap, id, index)
    const status = SEVERITY_STYLE[toSeverity(advisory?.properties?.severity)]
    const color = stale ? '#94a3b8' : status.color
    return (
      <Circle key={`halo-${id}`} center={[lat, lon]} radius={STATUS_HALO_M} interactive
        pathOptions={{ color, weight: 1.2, opacity: 0.7, fillColor: color, fillOpacity: 0.16, dashArray: stale ? '4 4' : undefined }}>
        <Tooltip sticky>{`${id}: ${stale ? STALE_STYLE.label : status.label}`}</Tooltip>
      </Circle>
    )
  })}</>
})
