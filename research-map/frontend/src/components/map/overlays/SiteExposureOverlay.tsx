import { memo, useMemo, useState } from 'react'
import L from 'leaflet'
import { Marker, useMap, useMapEvents } from 'react-leaflet'
import type { Theme } from '../../../hooks/useTheme'
import type { Stations } from '../../../types/monitor'
import { directionVi, EXPOSURE_LABEL, hsBand, roseRadius, wedgePath, DANGEROUS_HS_M, WATCH_HS_M, type ExposureStation, type SiteExposure } from '../siteExposure'

/**
 * Exposure ink: one neutral ink (no hue), so the rose never competes with the
 * station's advisory colour. Opacity carries the Hs band; wedge length carries Hs.
 */
export const EXPOSURE_INK: Record<Theme, string> = { light: '#1d2939', dark: '#e4ebf3' }
const BAND_OPACITY = { danger: 0.92, watch: 0.42, low: 0.14, none: 0 } as const

const MAP_ROSE = { size: 48, inner: 10.5, outer: 23 }

function mapRoseSvg(station: ExposureStation, ink: string): string {
  const c = MAP_ROSE.size / 2
  // On the map only the sectors that matter (Hs ≥ 1 m at cấp 10) are drawn; the popup shows all 16.
  const wedges = station.rose.filter(sector => sector.bearing != null && sector.hs_m != null && sector.hs_m >= WATCH_HS_M).map(sector => {
    const band = hsBand(sector.hs_m)
    return `<path d="${wedgePath(c, c, MAP_ROSE.inner, roseRadius(sector.hs_m!, MAP_ROSE.inner + 3, MAP_ROSE.outer), sector.bearing!)}" fill="${ink}" fill-opacity="${BAND_OPACITY[band]}" />`
  }).join('')
  return `<svg width="${MAP_ROSE.size}" height="${MAP_ROSE.size}" viewBox="0 0 ${MAP_ROSE.size} ${MAP_ROSE.size}" aria-hidden="true">${wedges}</svg>`
}

function exposureIcon(station: ExposureStation, theme: Theme, withLabel: boolean): L.DivIcon {
  const ink = EXPOSURE_INK[theme]
  const label = station.exposure_class ? EXPOSURE_LABEL[station.exposure_class] : '?'
  const size = MAP_ROSE.size
  return L.divIcon({
    className: 'site-exposure-marker',
    html: `<div style="position:relative;width:${size}px;height:${size}px;pointer-events:none">${mapRoseSvg(station, ink)}`
      + (!withLabel ? '</div>' : `<span style="position:absolute;left:50%;top:${size / 2 + 10}px;transform:translateX(-50%);white-space:nowrap;padding:0 5px;border-radius:5px;`
      + `font:600 10px/15px inherit;font-family:inherit;color:var(--fg);background:var(--surface);border:1px solid var(--line-strong);box-shadow:var(--shadow-sm)">${label}</span></div>`),
    iconSize: [size, size], iconAnchor: [size / 2, size / 2],
  })
}

/**
 * Theory-only exposure layer: per network station a mini "dangerous direction"
 * rose (Hs at open-water cấp 10 by wind direction) plus the exposure class
 * (hở / bán kín / kín). Drawn under the station dot at the station's registry
 * position so it reads as part of that marker; never interactive itself.
 */
export const SiteExposureOverlay = memo(function SiteExposureOverlay({ exposure, stations, theme }: { exposure: SiteExposure | null; stations: Stations | null; theme: Theme }) {
  const map = useMap()
  const [zoom, setZoom] = useState(() => map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  const placed = useMemo(() => {
    if (exposure?.status !== 'ready') return []
    const registry = new Map((stations?.features ?? []).map(feature => [String(feature.properties?.station ?? ''), feature.geometry]))
    return (exposure.stations ?? []).map(station => {
      const geometry = registry.get(station.id)
      const [lon, lat] = geometry?.type === 'Point' ? geometry.coordinates as [number, number] : [station.lon, station.lat]
      if (lon == null || lat == null) return null
      return { station, position: [lat, lon] as [number, number] }
    }).filter(item => item !== null)
  }, [exposure, stations])
  // Class pills that would overlap at this zoom are dropped (more exposed first); the rose always stays
  // and the class is still in the popup / inspector.
  const items = useMemo(() => {
    const rank = { exposed: 0, semi: 1, sheltered: 2 } as const
    const order = [...placed].sort((a, b) => rank[a.station.exposure_class ?? 'sheltered'] - rank[b.station.exposure_class ?? 'sheltered'])
    const kept: L.Point[] = []
    const labelled = new Set<string>()
    for (const item of order) {
      const p = map.project(item.position, zoom)
      if (kept.some(q => Math.abs(q.x - p.x) < 44 && Math.abs(q.y - p.y) < 20)) continue
      kept.push(p); labelled.add(item.station.id)
    }
    return placed.map(item => ({ ...item, icon: exposureIcon(item.station, theme, labelled.has(item.station.id)) }))
  }, [placed, map, zoom, theme])
  return <>{items.map(item => (
    <Marker key={`exposure-${item.station.id}`} position={item.position} icon={item.icon} interactive={false} keyboard={false} zIndexOffset={-1000} />
  ))}</>
})

/* ---------------------------------------------------------- detail rose (SVG) */

/** Full 16-sector rose for popups / inspector: every sector, rings at the 1 m and 2 m thresholds. */
export function ExposureRose({ station, theme, size = 132 }: { station: ExposureStation; theme: Theme; size?: number }) {
  const ink = EXPOSURE_INK[theme]
  const c = size / 2, inner = size * 0.08, outer = size / 2 - 13
  const ring = (hs: number) => roseRadius(hs, inner, outer)
  const cardinals: Array<[string, number]> = [['B', 0], ['Đ', 90], ['N', 180], ['T', 270]]
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={`Hoa hướng sóng ở gió cấp 10, trạm ${station.id}: ${station.rose.filter(s => (s.hs_m ?? 0) >= DANGEROUS_HS_M).map(s => directionVi(s.direction)).join(', ') || 'không có hướng nguy hiểm'}`}>
      <circle cx={c} cy={c} r={ring(WATCH_HS_M)} fill="none" stroke={ink} strokeOpacity={0.35} strokeDasharray="2 3" />
      <circle cx={c} cy={c} r={ring(DANGEROUS_HS_M)} fill="none" stroke={ink} strokeOpacity={0.55} strokeDasharray="4 3" />
      {station.rose.map(sector => sector.bearing == null || sector.hs_m == null ? null : (
        <path key={sector.direction} d={wedgePath(c, c, inner, Math.max(inner + 1.5, ring(sector.hs_m)), sector.bearing)}
          fill={ink} fillOpacity={Math.max(0.1, BAND_OPACITY[hsBand(sector.hs_m)])} stroke={ink} strokeOpacity={0.5} strokeWidth={0.6}>
          <title>{`${directionVi(sector.direction)} (${sector.direction}): Hs ${sector.hs_m.toFixed(1)} m · đà gió ${sector.fetch_km == null ? '—' : `${sector.fetch_censored ? '≥ ' : ''}${sector.fetch_km.toFixed(1)} km`}`}</title>
        </path>
      ))}
      {cardinals.map(([label, deg]) => {
        const rad = (deg - 90) * Math.PI / 180, r = size / 2 - 6
        return <text key={label} x={c + r * Math.cos(rad)} y={c + r * Math.sin(rad)} textAnchor="middle" dominantBaseline="central" fontSize={10} fontWeight={600} fill="currentColor" opacity={0.7}>{label}</text>
      })}
      <text x={c + ring(DANGEROUS_HS_M) * 0.71 + 2} y={c + ring(DANGEROUS_HS_M) * 0.71 + 2} fontSize={8.5} fill="currentColor" opacity={0.65}>2 m</text>
    </svg>
  )
}

const fmt = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits).replace('.', ',')

/** Exposure block for a station popup / inspector row. Theory only, labelled as such. */
export function ExposureDetail({ station, theme, roseSize = 132 }: { station: ExposureStation; theme: Theme; roseSize?: number }) {
  const danger = station.rose.filter(s => (s.hs_m ?? 0) >= DANGEROUS_HS_M)
  const watch = station.rose.filter(s => (s.hs_m ?? 0) >= WATCH_HS_M && (s.hs_m ?? 0) < DANGEROUS_HS_M)
  const list = (items: typeof danger) => items.map(s => `${directionVi(s.direction)} ${fmt(s.hs_m)} m`).join(' · ')
  return (
    <div style={{ fontSize: 11.5, lineHeight: 1.4 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
        <b>Phơi nhiễm: {station.exposure_class ? EXPOSURE_LABEL[station.exposure_class] : 'chưa rõ'}</b>
        <span style={{ fontSize: 10, padding: '0 5px', borderRadius: 4, color: 'var(--info)', background: 'var(--info-bg)' }}>lý thuyết</span>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
        <ExposureRose station={station} theme={theme} size={roseSize} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ opacity: 0.75 }}>Sóng Hs theo hướng gió, gió ngoài khơi cấp 10 (24,5 m/s)</div>
          <div style={{ marginTop: 3 }}><b>Nguy hiểm (≥ 2 m):</b> {danger.length ? list(danger) : 'không'}</div>
          <div><b>Cần chú ý (1–2 m):</b> {watch.length ? list(watch) : 'không'}</div>
          <div style={{ marginTop: 3, opacity: 0.75 }}>Hs lớn nhất cấp 8 / 10 / 12: {fmt(station.hs_worst_m.c8)} / {fmt(station.hs_worst_m.c10)} / {fmt(station.hs_worst_m.c12)} m</div>
        </div>
      </div>
      <div style={{ marginTop: 4, fontSize: 10.5, opacity: 0.7 }}>Đà gió + che chắn địa hình + SPM 1984; chưa kiểm chứng hiện trường, không dùng cho cảnh báo.</div>
    </div>
  )
}
