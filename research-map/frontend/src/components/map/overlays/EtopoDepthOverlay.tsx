import { memo, useCallback, useMemo, useRef } from 'react'
import L from 'leaflet'
import { GeoJSON, LayerGroup, Marker } from 'react-leaflet'
import type { BathymetryVectorLayer } from '../../../types/monitor'
import type { Theme } from '../../../hooks/useTheme'
import { ramp, SEQUENTIAL } from '../../../lib/palette'
import type { Lod } from '../mapConfig'

/** Band edges served by the backend (m): 0–2, 2–5, 5–10, 10–20, 20–30, 30–50, ≥ 50. */
export const DEPTH_BAND_LABELS = ['0–2', '2–5', '5–10', '10–20', '20–30', '30–50', '≥ 50']

/** Single-hue sequential ramp (validated SEQUENTIAL palette): shallow light → deep dark. */
export const depthBandColor = (band: number, theme: Theme) => ramp(SEQUENTIAL[theme], band / (DEPTH_BAND_LABELS.length - 1))

export type DepthSource = 'gebco' | 'etopo'

export const FLAG_STYLE = {
  suspect: { color: '#c2410c', label: 'Nghi lỗi nguồn (hố sâu kín)' },
  coarse: { color: '#64748b', label: 'Lưới quá thô (nguồn coi là đất)' },
} as const

/** Band fill opacity per confidence. GEBCO uses the TID classes; ETOPO only ok / coarse / suspect. */
const CONFIDENCE_OPACITY: Record<string, number> = { direct: 0.88, indirect: 0.58, unknown: 0.4, ok: 0.62, coarse: 0.3, suspect: 0.12 }
const SOURCE_NAME: Record<DepthSource, string> = { gebco: 'GEBCO 2024', etopo: 'ETOPO 2022' }
/** Confidence classes whose band outline is dashed (faded / not trustworthy as solid data). */
const FADED = new Set(['coarse', 'suspect'])
export const TID_LABEL: Record<string, string> = { direct: 'đo trực tiếp (TID)', indirect: 'nội suy / dự đoán (TID)', unknown: 'không rõ nguồn (TID)' }

type Props = {
  source?: DepthSource
  theme: Theme
  lod: Lod
  isobands: BathymetryVectorLayer | null
  isobaths: BathymetryVectorLayer | null
  flags: BathymetryVectorLayer | null
  showBands: boolean
  showIsobaths: boolean
  onSample: (latitude: number, longitude: number) => void
  /**
   * Draw under every other vector layer (comparison layer). All vectors share one canvas renderer whose
   * draw order is add order, so a layer toggled on later would otherwise paint over the default depth.
   */
  underlay?: boolean
}

const ready = (layer: BathymetryVectorLayer | null) => layer?.status === 'ready' ? layer : null

/** Midpoint of the longest part of a (multi)line, with its length in degrees. */
function labelAnchor(geometry: GeoJSON.Geometry): { at: [number, number]; length: number } | null {
  const parts = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.type === 'MultiLineString' ? geometry.coordinates : []
  let best: { at: [number, number]; length: number } | null = null
  for (const part of parts) {
    let length = 0
    for (let i = 1; i < part.length; i++) length += Math.hypot(part[i][0] - part[i - 1][0], part[i][1] - part[i - 1][1])
    if (!best || length > best.length) { const mid = part[Math.floor(part.length / 2)]; best = { at: [mid[1], mid[0]], length } }
  }
  return best
}

const LABEL_RULES: Record<Lod, { minLength: number; cell: number; levels: number[] }> = {
  low: { minLength: 0.12, cell: 0.12, levels: [5, 10, 20, 30] },
  medium: { minLength: 0.04, cell: 0.05, levels: [2, 5, 10, 20, 30] },
  high: { minLength: 0.015, cell: 0.02, levels: [2, 5, 10, 20, 30] },
}

function isobathLabels(lines: BathymetryVectorLayer, lod: Lod) {
  const rule = LABEL_RULES[lod]
  const taken = new Set<string>()
  const labels: Array<{ key: string; at: [number, number]; depth: number }> = []
  const candidates = lines.features
    .map(feature => ({ depth: Number(feature.properties?.depth_m), anchor: labelAnchor(feature.geometry) }))
    .filter(item => item.anchor && item.anchor.length >= rule.minLength && rule.levels.includes(item.depth))
    .sort((a, b) => b.anchor!.length - a.anchor!.length)
  for (const { depth, anchor } of candidates) {
    const bucket = `${Math.round(anchor!.at[0] / rule.cell)}:${Math.round(anchor!.at[1] / rule.cell)}`
    if (taken.has(bucket)) continue
    taken.add(bucket)
    labels.push({ key: `${depth}-${bucket}`, at: anchor!.at, depth })
    if (labels.length >= 80) break
  }
  return labels
}

/**
 * Regional depth (GEBCO 2024 by default, ETOPO 2022 for comparison): filled isobands
 * clipped to the OSM water mask, labelled isobaths, and the confidence flags (drawn with the bands).
 * GEBCO bands carry a TID confidence: direct = solid, indirect = normal, unknown/coarse/suspect = faded.
 */
export const EtopoDepthOverlay = memo(function EtopoDepthOverlay({ source = 'etopo', theme, lod, isobands, isobaths, flags, showBands, showIsobaths, onSample, underlay = false }: Props) {
  const bands = ready(isobands), lines = ready(isobaths), flagged = ready(flags)
  const bandsRef = useRef<L.GeoJSON>(null), flagsRef = useRef<L.GeoJSON>(null)
  // Flags first, then bands, so the order at the bottom of the stack is bands < flags < everything else.
  const toBack = useMemo(() => (underlay ? { add: () => { flagsRef.current?.bringToBack(); bandsRef.current?.bringToBack() } } : undefined), [underlay])
  const bandStyle = useCallback((feature?: GeoJSON.Feature) => {
    const color = depthBandColor(Number(feature?.properties?.band ?? 0), theme)
    // Opacity by confidence: coarse-grid and suspect parts fade so they never read as solid data.
    const confidence = String(feature?.properties?.confidence ?? 'ok')
    const alpha = CONFIDENCE_OPACITY[confidence] ?? CONFIDENCE_OPACITY.ok
    // Same-colour hairline hides canvas anti-alias seams between adjacent bands; faded classes get a dashed outline.
    if (FADED.has(confidence)) return { color: FLAG_STYLE[confidence as 'coarse' | 'suspect'].color, weight: 0.8, opacity: 0.55, dashArray: '3 3', fillColor: color, fillOpacity: alpha }
    return { color, weight: confidence === 'direct' ? 1 : 0.6, opacity: Math.max(alpha, 0.5), fillColor: color, fillOpacity: alpha }
  }, [theme])
  const lineColor = theme === 'dark' ? '#cde2fb' : '#1d3f6e'
  const lineStyle = useCallback((feature?: GeoJSON.Feature) => {
    const depth = Number(feature?.properties?.depth_m)
    return { color: lineColor, weight: depth % 10 === 0 ? 1.1 : 0.7, opacity: 0.7, dashArray: depth <= 2 ? '3 3' : undefined }
  }, [lineColor])
  const flagStyle = useCallback((feature?: GeoJSON.Feature) => {
    const suspect = feature?.properties?.flag === 'suspect'
    const style = FLAG_STYLE[suspect ? 'suspect' : 'coarse']
    return { color: style.color, weight: suspect ? 1.6 : 1, opacity: 0.9, dashArray: '4 3', fillColor: style.color, fillOpacity: suspect ? 0.3 : 0.18 }
  }, [])
  const labels = useMemo(() => lines && showIsobaths ? isobathLabels(lines, lod) : [], [lines, lod, showIsobaths])
  const halo = theme === 'dark' ? '#0b1220' : '#ffffff'

  return <>
    {showBands && bands && <GeoJSON ref={bandsRef} eventHandlers={toBack} key={`${source}-bands-${bands.lod}-${theme}`} data={bands} style={bandStyle}
      onEachFeature={(feature, layer) => {
        const confidence = String(feature.properties?.confidence ?? '')
        const note = confidence === 'suspect' ? ' · nghi lỗi nguồn' : confidence === 'coarse' ? ' · lưới thô' : TID_LABEL[confidence] ? ` · ${TID_LABEL[confidence]}` : ''
        layer.bindTooltip(`Độ sâu ${feature.properties?.label ?? ''} · ${SOURCE_NAME[source]} ~460 m${note}`, { sticky: true })
        layer.on('click', event => onSample(event.latlng.lat, event.latlng.lng))
      }} />}
    {showBands && flagged && <GeoJSON ref={flagsRef} eventHandlers={toBack} key={`${source}-flags-${flagged.lod}`} data={flagged} style={flagStyle}
      onEachFeature={(feature, layer) => {
        layer.bindTooltip(FLAG_STYLE[feature.properties?.flag === 'suspect' ? 'suspect' : 'coarse'].label, { sticky: true })
        layer.on('click', event => onSample(event.latlng.lat, event.latlng.lng))
      }} />}
    {showIsobaths && lines && <GeoJSON key={`${source}-lines-${lines.lod}-${theme}`} data={lines} style={lineStyle} interactive={false} />}
    {labels.length > 0 && <LayerGroup>
      {labels.map(label => <Marker key={label.key} position={label.at} interactive={false} keyboard={false}
        icon={L.divIcon({ className: '', iconSize: [0, 0], html: `<span style="position:absolute;transform:translate(-50%,-50%);font:600 10px/1 system-ui,sans-serif;color:${lineColor};text-shadow:0 0 2px ${halo},0 0 2px ${halo},0 0 3px ${halo};white-space:nowrap">${label.depth} m</span>` })} />)}
    </LayerGroup>}
  </>
})
