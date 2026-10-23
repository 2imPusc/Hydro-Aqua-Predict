import { memo, useEffect, useMemo } from 'react'
import L from 'leaflet'
import { useMap } from 'react-leaflet'
import type { Layer } from '../../../types/monitor'
import { LABEL, escapeHtml } from '../mapConfig'

/** Blue/cyan ramp shared with the legend (avoids a dominant green fill for rain). */
export const scalarColor = (ratio: number) => `hsl(${215 - Math.max(0, Math.min(1, ratio)) * 35} 78% 52%)`

/** RGB of `scalarColor` (HSL → RGB) for the field image. */
function scalarRgb(ratio: number): [number, number, number] {
  const h = 215 - Math.max(0, Math.min(1, ratio)) * 35, sat = 0.78, light = 0.52
  const a = sat * Math.min(light, 1 - light)
  const f = (n: number) => { const k = (n + h / 30) % 12; return Math.round(255 * (light - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))) }
  return [f(0), f(8), f(4)]
}

type Node = { lon: number; lat: number; value: number; feature: GeoJSON.Feature }
type Field = { lons: number[]; lats: number[]; grid: Array<number | null>; min: number; max: number; nodes: Node[] }

const key6 = (value: number) => Math.round(value * 1e6) / 1e6

/** Sample points (requested grid when present, else the point geometry) on a regular lon/lat grid. */
function buildField(layer: Layer): Field | null {
  const nodes: Node[] = []
  for (const feature of layer.geojson?.features ?? []) {
    const value = Number(feature.properties?.value)
    if (!Number.isFinite(value)) continue
    let lon = Number(feature.properties?.requested_lon), lat = Number(feature.properties?.requested_lat)
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
      if (feature.geometry.type !== 'Point') continue
      ;[lon, lat] = feature.geometry.coordinates as [number, number]
    }
    nodes.push({ lon: key6(lon), lat: key6(lat), value, feature })
  }
  if (!nodes.length) return null
  const lons = [...new Set(nodes.map(node => node.lon))].sort((a, b) => a - b)
  const lats = [...new Set(nodes.map(node => node.lat))].sort((a, b) => b - a) // row 0 = north
  const grid: Array<number | null> = new Array(lons.length * lats.length).fill(null)
  for (const node of nodes) grid[lats.indexOf(node.lat) * lons.length + lons.indexOf(node.lon)] = node.value
  const values = nodes.map(node => node.value)
  return { lons, lats, grid, min: Math.min(...values), max: Math.max(...values), nodes }
}

/** Nearest-valid fill so bilinear smoothing never blends toward "no value"; the water clip limits the result. */
function filled(field: Field): number[] {
  const { lons, lats, grid } = field
  return grid.map((value, index) => {
    if (value != null) return value
    const x = index % lons.length, y = Math.floor(index / lons.length)
    let best = Infinity, out = field.min
    grid.forEach((other, j) => {
      if (other == null) return
      const d = (j % lons.length - x) ** 2 + (Math.floor(j / lons.length) - y) ** 2
      if (d < best) { best = d; out = other }
    })
    return out
  })
}

function pathRings(ctx: CanvasRenderingContext2D, map: L.Map, geometry: GeoJSON.Geometry) {
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.type === 'MultiPolygon' ? geometry.coordinates : []
  for (const polygon of polygons) for (const ring of polygon) ring.forEach(([lon, lat], i) => {
    const p = map.latLngToContainerPoint([lat, lon])
    if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y)
  })
}

/**
 * Coarse model scalar (rain, sea level, MLD …) as ONE smooth canvas field:
 * node values are bilinearly interpolated by the browser's image smoothing and
 * clipped to the context water polygon — no square cells. Click = nearest sample.
 */
export const ScalarGridOverlay = memo(function ScalarGridOverlay({ layer, dataKey, waterGeometry }: { layer: Layer; dataKey: string; waterGeometry?: GeoJSON.Geometry }) {
  const map = useMap()
  const field = useMemo(() => buildField(layer), [layer])
  useEffect(() => {
    if (!field) return
    const { lons, lats, min, max } = field
    const values = filled(field)
    const image = document.createElement('canvas')
    image.width = lons.length; image.height = lats.length
    const imageCtx = image.getContext('2d')!
    const pixels = imageCtx.createImageData(lons.length, lats.length)
    values.forEach((value, index) => {
      pixels.data.set([...scalarRgb(max > min ? (value - min) / (max - min) : 0.5), 255], index * 4)
    })
    imageCtx.putImageData(pixels, 0, 0)
    const dLon = lons.length > 1 ? (lons[lons.length - 1] - lons[0]) / (lons.length - 1) : 0.01
    const dLat = lats.length > 1 ? (lats[0] - lats[lats.length - 1]) / (lats.length - 1) : 0.01

    const canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide') as HTMLCanvasElement
    canvas.style.pointerEvents = 'none'
    canvas.style.opacity = '0.55'
    map.getPanes().overlayPane.appendChild(canvas)
    const draw = () => {
      const size = map.getSize(), ratio = window.devicePixelRatio || 1
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
      canvas.width = size.x * ratio; canvas.height = size.y * ratio
      canvas.style.width = `${size.x}px`; canvas.style.height = `${size.y}px`
      const ctx = canvas.getContext('2d')!
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      ctx.clearRect(0, 0, size.x, size.y)
      if (waterGeometry) { ctx.beginPath(); pathRings(ctx, map, waterGeometry); ctx.clip('evenodd') }
      // Pixel centres sit on sample nodes, so the smoothing is node-to-node bilinear.
      const nw = map.latLngToContainerPoint([lats[0] + dLat / 2, lons[0] - dLon / 2])
      const se = map.latLngToContainerPoint([lats[lats.length - 1] - dLat / 2, lons[lons.length - 1] + dLon / 2])
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(image, nw.x, nw.y, se.x - nw.x, se.y - nw.y)
    }
    const onClick = (event: L.LeafletMouseEvent) => {
      let best: Node | null = null, distance = Infinity
      for (const node of field.nodes) {
        const d = (node.lon - event.latlng.lng) ** 2 + (node.lat - event.latlng.lat) ** 2
        if (d < distance) { distance = d; best = node }
      }
      if (!best || Math.sqrt(distance) > Math.max(dLon, dLat) * 1.5) return
      const feature = best.feature
      L.popup().setLatLng(event.latlng).setContent(`<b>${escapeHtml(LABEL[layer.layer])}</b><br/>${escapeHtml(feature?.properties?.variable)}: ${best.value.toFixed(3)} ${escapeHtml(feature?.properties?.unit ?? '')}<br/><small>Giá trị mẫu gần nhất · lưới nguồn ${escapeHtml(layer.provenance?.source_grid_resolution ?? layer.provenance?.grid_resolution ?? '—')}</small><hr/>${escapeHtml(layer.provenance?.source)}<br/>valid: ${escapeHtml(layer.provenance?.valid_at)}`).openOn(map)
    }
    draw()
    map.on('moveend zoomend resize', draw)
    map.on('click', onClick)
    return () => { map.off('moveend zoomend resize', draw); map.off('click', onClick); canvas.remove() }
  }, [map, field, waterGeometry, layer, dataKey])
  return null
})
