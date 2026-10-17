import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import L from 'leaflet'
import { MapContainer, TileLayer, ZoomControl, useMap } from 'react-leaflet'
import { basemapTiles, ESRI_ATTRIBUTION } from './mapConfig'
import type { Theme } from '../../hooks/useTheme'

/** Space (px) kept free for floating panels when fitting bounds. */
export type MapInset = { top: number; right: number; bottom: number; left: number }

/** [minLon, minLat, maxLon, maxLat] */
export type LonLatBox = [number, number, number, number]

export function boxOfPoints(points: Array<[number, number]>): LonLatBox | null {
  if (!points.length) return null
  let minLon = Infinity, minLat = Infinity, maxLon = -Infinity, maxLat = -Infinity
  for (const [lon, lat] of points) {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
    minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon); minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat)
  }
  return Number.isFinite(minLon) ? [minLon, minLat, maxLon, maxLat] : null
}

/** Re-fits the map whenever the box (by value) changes; react-leaflet ignores bounds props after mount. */
function FitBounds({ box, inset }: { box: LonLatBox | null; inset: MapInset }) {
  const map = useMap()
  const key = box ? box.map(v => v.toFixed(4)).join(',') : ''
  useEffect(() => {
    if (!box) return
    const [minLon, minLat, maxLon, maxLat] = box
    map.fitBounds([[minLat, minLon], [maxLat, maxLon]], { paddingTopLeft: [inset.left, inset.top], paddingBottomRight: [inset.right, inset.bottom], maxZoom: 13, animate: false })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key])
  return null
}

/** Keeps Leaflet's size in sync when side panels open/close. */
function InvalidateOnResize() {
  const map = useMap()
  useEffect(() => {
    const container = map.getContainer()
    const observer = new ResizeObserver(() => map.invalidateSize({ animate: false }))
    observer.observe(container)
    return () => observer.disconnect()
  }, [map])
  return null
}

type Props = {
  theme: Theme
  box: LonLatBox | null
  children?: ReactNode
  /** Space kept free for floating panels when fitting. */
  inset?: MapInset
  className?: string
  ariaLabel: string
}

/**
 * Research map shell: theme-aware Esri canvas basemap, canvas renderer, no
 * pan limits (datasets span Hong Kong to Texas), refits on `box` changes.
 */
export function ResearchMap({ theme, box, children, inset = { top: 24, right: 24, bottom: 24, left: 24 }, className = 'absolute inset-0 z-0', ariaLabel }: Props) {
  const tiles = basemapTiles('canvas', theme)
  const initial = useMemo<L.LatLngBoundsExpression>(() => box ? [[box[1], box[0]], [box[3], box[2]]] : [[20.5, 106.6], [21.1, 107.5]], [])  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className={className} role="region" aria-label={ariaLabel}>
      <MapContainer preferCanvas bounds={initial} zoomControl={false} scrollWheelZoom worldCopyJump className="absolute inset-0">
        <ZoomControl position="bottomright" zoomInTitle="Phóng to" zoomOutTitle="Thu nhỏ" />
        <TileLayer key={tiles.base} attribution={ESRI_ATTRIBUTION} url={tiles.base} />
        {tiles.labels && <TileLayer key={tiles.labels} url={tiles.labels} className="basemap-labels" zIndex={2} />}
        <FitBounds box={box} inset={inset} />
        <InvalidateOnResize />
        {children}
      </MapContainer>
    </div>
  )
}

/**
 * Imperative canvas layer group: `build` returns Leaflet layers drawn with one
 * shared canvas renderer (thousands of cells/lines without React reconciliation).
 * Rebuilt only when `deps` change.
 */
export function CanvasLayer({ build, deps, pane }: { build: (renderer: L.Canvas) => L.Layer[]; deps: readonly unknown[]; pane?: string }) {
  const map = useMap()
  const renderer = useRef<L.Canvas | null>(null)
  if (!renderer.current) renderer.current = L.canvas(pane ? { padding: 0.3, pane } : { padding: 0.3 })
  useEffect(() => {
    const group = L.layerGroup(build(renderer.current!)).addTo(map)
    return () => { group.remove() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, ...deps])
  return null
}

/** Square of `sizeDeg` (lon) × `sizeDeg` (lat) centred on a point. */
export function squareBounds(lon: number, lat: number, sizeDeg: number): L.LatLngBoundsExpression {
  const h = sizeDeg / 2
  return [[lat - h, lon - h], [lat + h, lon + h]]
}

/** Metre grid step → degrees at a latitude (for square cells drawn around point centres). */
export function metresToDeg(metres: number, lat: number): { dLat: number; dLon: number } {
  const dLat = metres / 111_320
  return { dLat, dLon: metres / (111_320 * Math.cos((lat * Math.PI) / 180)) }
}
