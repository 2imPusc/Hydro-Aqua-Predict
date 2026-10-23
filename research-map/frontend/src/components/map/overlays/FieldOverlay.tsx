import { memo, useEffect, useMemo } from 'react'
import L from 'leaflet'
import { useMap } from 'react-leaflet'
import { escapeHtml } from '../mapConfig'
import { paletteRgba, type Palette } from '../fieldPalettes'

export type FieldNode = { lon: number; lat: number; value: number | null; label?: string }

type Grid = { lon0: number; lat0: number; nx: number; ny: number; step: number; values: Float32Array; has: Uint8Array; nodes: FieldNode[] }

/** Snap nodes to the regular lattice (row 0 = north); a node without a value stays a hole. */
function lattice(nodes: FieldNode[], step: number): Grid | null {
  const valid = nodes.filter(node => Number.isFinite(node.lon) && Number.isFinite(node.lat))
  if (!valid.length || !(step > 0)) return null
  const lon0 = Math.min(...valid.map(n => n.lon)), lat0 = Math.max(...valid.map(n => n.lat))
  const ix = (lon: number) => Math.round((lon - lon0) / step), iy = (lat: number) => Math.round((lat0 - lat) / step)
  const nx = Math.max(...valid.map(n => ix(n.lon))) + 1, ny = Math.max(...valid.map(n => iy(n.lat))) + 1
  const values = new Float32Array(nx * ny), has = new Uint8Array(nx * ny)
  for (const node of valid) {
    if (node.value == null || !Number.isFinite(node.value)) continue
    const k = iy(node.lat) * nx + ix(node.lon)
    values[k] = node.value; has[k] = 1
  }
  return { lon0, lat0, nx, ny, step, values, has, nodes: valid }
}

const UPSAMPLE = 6

/**
 * Value-space bilinear field (colour applied AFTER interpolation, so the ramp is honest), upsampled
 * UPSAMPLE× the model lattice. Holes (land nodes of a marine field) take the nearest valued node so the
 * coast does not fade toward "no value"; the water clip then removes land.
 */
function render(grid: Grid, palette: Palette): HTMLCanvasElement {
  const { nx, ny, values, has } = grid
  const filled = new Float32Array(values)
  if (has.some(v => v === 0)) {
    for (let k = 0; k < nx * ny; k++) {
      if (has[k]) continue
      const x = k % nx, y = Math.floor(k / nx)
      let best = Infinity
      for (let j = 0; j < nx * ny; j++) {
        if (!has[j]) continue
        const d = (j % nx - x) ** 2 + (Math.floor(j / nx) - y) ** 2
        if (d < best) { best = d; filled[k] = values[j] }
      }
    }
  }
  const w = (nx - 1) * UPSAMPLE + 1, h = (ny - 1) * UPSAMPLE + 1
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, w); canvas.height = Math.max(1, h)
  const ctx = canvas.getContext('2d')!
  const image = ctx.createImageData(canvas.width, canvas.height)
  const at = (x: number, y: number) => filled[Math.min(ny - 1, y) * nx + Math.min(nx - 1, x)]
  for (let py = 0; py < canvas.height; py++) {
    const gy = py / UPSAMPLE, y0 = Math.floor(gy), fy = gy - y0
    for (let px = 0; px < canvas.width; px++) {
      const gx = px / UPSAMPLE, x0 = Math.floor(gx), fx = gx - x0
      const value = at(x0, y0) * (1 - fx) * (1 - fy) + at(x0 + 1, y0) * fx * (1 - fy) + at(x0, y0 + 1) * (1 - fx) * fy + at(x0 + 1, y0 + 1) * fx * fy
      const [r, g, b, a] = paletteRgba(palette, value)
      const o = (py * canvas.width + px) * 4
      image.data[o] = r; image.data[o + 1] = g; image.data[o + 2] = b; image.data[o + 3] = a
    }
  }
  ctx.putImageData(image, 0, 0)
  return canvas
}

function tracePolygons(ctx: CanvasRenderingContext2D, map: L.Map, geometry: GeoJSON.Geometry) {
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.type === 'MultiPolygon' ? geometry.coordinates : []
  for (const polygon of polygons) for (const ring of polygon) ring.forEach(([lon, lat], i) => {
    const p = map.latLngToContainerPoint([lat, lon])
    if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y)
  })
}

type Props = {
  nodes: FieldNode[]
  /** Lattice step in degrees (the provider query grid). */
  step: number
  palette: Palette
  /** Water polygon for marine fields; omit for weather fields that are real over land too. */
  clip?: GeoJSON.Geometry | null
  /** Short provenance line shown in the click popup. */
  source: string
  dataKey: string
  opacity?: number
}

/** Smooth Windy-style colour field for one regional variable; click = nearest model node. */
export const FieldOverlay = memo(function FieldOverlay({ nodes, step, palette, clip, source, dataKey, opacity = 0.92 }: Props) {
  const map = useMap()
  const grid = useMemo(() => lattice(nodes, step), [nodes, step])
  useEffect(() => {
    if (!grid) return undefined
    const pane = 'regional-field'
    if (!map.getPane(pane)) {
      const el = map.createPane(pane)
      el.style.zIndex = '360'
      el.style.pointerEvents = 'none'
    }
    const image = render(grid, palette)
    const canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide') as HTMLCanvasElement
    canvas.style.pointerEvents = 'none'
    canvas.style.opacity = String(opacity)
    map.getPane(pane)!.appendChild(canvas)
    const { lon0, lat0, nx, ny } = grid
    const draw = () => {
      const size = map.getSize(), ratio = window.devicePixelRatio || 1
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
      canvas.width = size.x * ratio; canvas.height = size.y * ratio
      canvas.style.width = `${size.x}px`; canvas.style.height = `${size.y}px`
      const ctx = canvas.getContext('2d')!
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      ctx.clearRect(0, 0, size.x, size.y)
      if (clip) { ctx.beginPath(); tracePolygons(ctx, map, clip); ctx.clip('evenodd') }
      // Image pixels sit on lattice nodes: the first/last pixel centre is the first/last node.
      const nw = map.latLngToContainerPoint([lat0, lon0])
      const se = map.latLngToContainerPoint([lat0 - (ny - 1) * step, lon0 + (nx - 1) * step])
      const dx = (se.x - nw.x) / Math.max(1, image.width - 1) / 2, dy = (se.y - nw.y) / Math.max(1, image.height - 1) / 2
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(image, nw.x - dx, nw.y - dy, se.x - nw.x + 2 * dx, se.y - nw.y + 2 * dy)
    }
    const onClick = (event: L.LeafletMouseEvent) => {
      let best: FieldNode | null = null, distance = Infinity
      for (const node of grid.nodes) {
        if (node.value == null) continue
        const d = (node.lon - event.latlng.lng) ** 2 + (node.lat - event.latlng.lat) ** 2
        if (d < distance) { distance = d; best = node }
      }
      if (!best || Math.sqrt(distance) > step * 0.75 || best.value == null) return
      const value = best.value.toFixed(palette.digits).replace('.', ',')
      L.popup().setLatLng(event.latlng).setContent(`<b>${escapeHtml(palette.title)}</b>: ${value} ${escapeHtml(palette.unit)}${best.label ? `<br/>${escapeHtml(best.label)}` : ''}<br/><small>Điểm mô hình gần nhất (lưới ~${Math.round(step * 111)} km) · ${escapeHtml(source)}</small>`).openOn(map)
    }
    draw()
    map.on('moveend zoomend resize viewreset', draw)
    map.on('click', onClick)
    return () => { map.off('moveend zoomend resize viewreset', draw); map.off('click', onClick); canvas.remove() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, grid, dataKey, clip, opacity])
  return null
})
