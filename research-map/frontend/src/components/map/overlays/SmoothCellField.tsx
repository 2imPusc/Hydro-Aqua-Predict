import { memo, useEffect, useMemo } from 'react'
import L from 'leaflet'
import { useMap } from 'react-leaflet'

export type FieldCell = { lon: number; lat: number; value: number | null }

type Lattice = { lon0: number; lat0: number; nx: number; ny: number; dLon: number; dLat: number; values: Array<number | null>; index: Int32Array }

/**
 * Snap cell centres to a regular lattice by rounding to the nominal step
 * (exported grids alternate 0.0833 / 0.0834°, so float equality is not usable).
 * Row 0 = north.
 */
function lattice(cells: FieldCell[], size: number): Lattice | null {
  const valid = cells.filter(cell => Number.isFinite(cell.lon) && Number.isFinite(cell.lat))
  if (!valid.length || !(size > 0)) return null
  const lon0 = Math.min(...valid.map(c => c.lon)), latMax = Math.max(...valid.map(c => c.lat))
  const ix = (lon: number) => Math.round((lon - lon0) / size), iy = (lat: number) => Math.round((latMax - lat) / size)
  const nx = Math.max(...valid.map(c => ix(c.lon))) + 1, ny = Math.max(...valid.map(c => iy(c.lat))) + 1
  const values: Array<number | null> = new Array(nx * ny).fill(null)
  const index = new Int32Array(nx * ny).fill(-1)
  cells.forEach((cell, i) => {
    if (!Number.isFinite(cell.lon) || !Number.isFinite(cell.lat)) return
    const k = iy(cell.lat) * nx + ix(cell.lon)
    values[k] = cell.value != null && Number.isFinite(cell.value) ? cell.value : null
    index[k] = i
  })
  return { lon0, lat0: latMax, nx, ny, dLon: size, dLat: size, values, index }
}

const UPSAMPLE = 8

/**
 * Field image at UPSAMPLE× the lattice: colour = bilinear blend of the valid
 * neighbouring nodes only (renormalised weights, never blended toward "no value");
 * alpha = bilinear coverage of valid nodes passed through a smoothstep around 0.5,
 * so the edge is a smooth curve at roughly the old square footprint instead of a
 * staircase, and nothing is drawn beyond the cells the model actually has.
 */
function renderField(grid: Lattice, color: (value: number) => [number, number, number]): HTMLCanvasElement {
  const { nx, ny, values } = grid
  const w = nx * UPSAMPLE, h = ny * UPSAMPLE
  const canvas = document.createElement('canvas')
  canvas.width = w; canvas.height = h
  const ctx = canvas.getContext('2d')!
  const image = ctx.createImageData(w, h)
  const at = (x: number, y: number) => (x < 0 || y < 0 || x >= nx || y >= ny ? null : values[y * nx + x])
  for (let py = 0; py < h; py++) {
    const gy = (py + 0.5) / UPSAMPLE - 0.5, y0 = Math.floor(gy), fy = gy - y0
    for (let px = 0; px < w; px++) {
      const gx = (px + 0.5) / UPSAMPLE - 0.5, x0 = Math.floor(gx), fx = gx - x0
      const corners: Array<[number | null, number]> = [
        [at(x0, y0), (1 - fx) * (1 - fy)], [at(x0 + 1, y0), fx * (1 - fy)],
        [at(x0, y0 + 1), (1 - fx) * fy], [at(x0 + 1, y0 + 1), fx * fy],
      ]
      let coverage = 0, sum = 0
      for (const [value, weight] of corners) if (value != null) { coverage += weight; sum += value * weight }
      if (coverage <= 0) continue
      const t = Math.max(0, Math.min(1, (coverage - 0.38) / 0.24))
      const alpha = t * t * (3 - 2 * t)
      if (alpha <= 0) continue
      const [r, g, b] = color(sum / coverage)
      const o = (py * w + px) * 4
      image.data[o] = r; image.data[o + 1] = g; image.data[o + 2] = b; image.data[o + 3] = Math.round(alpha * 255)
    }
  }
  ctx.putImageData(image, 0, 0)
  return canvas
}

const PANE = 'smooth-cell-field'

type Props = {
  cells: FieldCell[]
  /** Nominal lattice step in degrees (both axes). */
  cellSizeDeg: number
  /** RGB for a raw value (caller owns the scale). */
  color: (value: number) => [number, number, number]
  opacity?: number
  /** Click on the field → index of the nearest cell (within ~0.75 cell). */
  onCellClick?: (index: number, latlng: L.LatLng) => void
  /** Rebuild key (data identity, theme, range). */
  dataKey: string
}

/**
 * Coarse gridded score drawn as ONE smooth canvas field (no square cells),
 * bounded by the model's own cell coverage. Smoothing does not add resolution:
 * callers must state the grid step next to the legend.
 */
export const SmoothCellField = memo(function SmoothCellField({ cells, cellSizeDeg, color, opacity = 0.8, onCellClick, dataKey }: Props) {
  const map = useMap()
  const grid = useMemo(() => lattice(cells, cellSizeDeg), [cells, cellSizeDeg])
  useEffect(() => {
    if (!grid) return undefined
    if (!map.getPane(PANE)) {
      const pane = map.createPane(PANE)
      pane.style.zIndex = '350' // under vector overlays (farms) and markers
      pane.style.pointerEvents = 'none'
    }
    const image = renderField(grid, color)
    const canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide') as HTMLCanvasElement
    canvas.style.pointerEvents = 'none'
    canvas.style.opacity = String(opacity)
    map.getPane(PANE)!.appendChild(canvas)
    const { lon0, lat0, nx, ny, dLon, dLat } = grid
    const draw = () => {
      const size = map.getSize(), ratio = window.devicePixelRatio || 1
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
      canvas.width = size.x * ratio; canvas.height = size.y * ratio
      canvas.style.width = `${size.x}px`; canvas.style.height = `${size.y}px`
      const ctx = canvas.getContext('2d')!
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      ctx.clearRect(0, 0, size.x, size.y)
      // Image spans the outer cell edges: node centres sit half a cell inside.
      const nw = map.latLngToContainerPoint([lat0 + dLat / 2, lon0 - dLon / 2])
      const se = map.latLngToContainerPoint([lat0 - (ny - 0.5) * dLat, lon0 + (nx - 0.5) * dLon])
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(image, nw.x, nw.y, se.x - nw.x, se.y - nw.y)
    }
    const onClick = (event: L.LeafletMouseEvent) => {
      if (!onCellClick) return
      const x = Math.round((event.latlng.lng - lon0) / dLon), y = Math.round((lat0 - event.latlng.lat) / dLat)
      if (x < 0 || y < 0 || x >= nx || y >= ny) return
      const k = grid.index[y * nx + x]
      if (k >= 0) onCellClick(k, event.latlng)
    }
    draw()
    map.on('moveend zoomend resize viewreset', draw)
    map.on('click', onClick)
    return () => { map.off('moveend zoomend resize viewreset', draw); map.off('click', onClick); canvas.remove() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, grid, dataKey, opacity])
  return null
})
