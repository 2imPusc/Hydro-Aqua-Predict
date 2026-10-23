import { memo, useMemo } from 'react'
import L from 'leaflet'
import { Marker, Popup } from 'react-leaflet'
import type { AquacultureMap, Stations } from '../../../types/monitor'
import type { Theme } from '../../../hooks/useTheme'
import { formatAge } from '../../../hooks/useNow'
import type { SiteExposure } from '../siteExposure'
import { ExposureDetail } from './SiteExposureOverlay'

export type Severity = 'WARNING' | 'WATCH' | 'UNKNOWN' | 'NORMAL'
export const SEVERITY_STYLE: Record<Severity, { color: string; label: string; tone: 'danger' | 'warn' | 'neutral' | 'ok' }> = {
  WARNING: { color: '#dc2626', label: 'Cảnh báo', tone: 'danger' },
  WATCH: { color: '#f59e0b', label: 'Cần theo dõi', tone: 'warn' },
  UNKNOWN: { color: '#94a3b8', label: 'Thiếu dữ liệu', tone: 'neutral' },
  NORMAL: { color: '#16a34a', label: 'Bình thường', tone: 'ok' },
}
export const toSeverity = (value: unknown): Severity => {
  const upper = String(value ?? 'UNKNOWN').toUpperCase()
  return upper === 'WARNING' || upper === 'WATCH' || upper === 'UNKNOWN' ? upper : 'NORMAL'
}

/* --------------------------------------------------------------- freshness */

/** A live advisory older than this is "cũ": markers drop tier colours (AGENTS.md hard rule 4). */
export const ADVISORY_STALE_SECONDS = 90 * 60
/** Neutral hatch for stale markers and their legend swatch (colour alone never says "old"). */
export const STALE_STYLE = {
  color: '#94a3b8',
  pattern: 'repeating-linear-gradient(135deg, #8a96a8 0 2.5px, #e3e8ef 2.5px 5px)',
  label: 'Cũ (> 90 phút)',
}

export function advisoryAgeSeconds(map: AquacultureMap | null | undefined, now: number): number | null {
  if (!map?.generated_at) return null
  const generated = Date.parse(map.generated_at)
  return Number.isFinite(generated) ? Math.max(0, (now - generated) / 1000) : null
}

/** Live advisory artifact present but older than 90 min. Mock maps are never "stale" (they carry their own label). */
export function isAdvisoryStale(map: AquacultureMap | null | undefined, now: number): boolean {
  if (!map || map.mode === 'mock' || map.status !== 'ready') return false
  const age = advisoryAgeSeconds(map, now)
  return age == null || age > ADVISORY_STALE_SECONDS
}

/**
 * The pilot has one physical sensor. Its advisory is the regional status;
 * mock mode may still provide per-point variants for demonstrations.
 */
export function advisoryForStation(aquacultureMap: AquacultureMap | null | undefined, station: unknown, index: number) {
  const advisories = aquacultureMap?.features ?? []
  return advisories.find(item => String(item.properties?.station_serial ?? '') === String(station ?? ''))
    ?? (aquacultureMap?.mode === 'mock' ? advisories[index % Math.max(1, advisories.length)] : advisories[0])
}

const iconCache = new Map<string, L.DivIcon>()
function stationIcon(color: string, mock: boolean, stale: boolean) {
  const key = `${color}-${mock}-${stale}`
  let icon = iconCache.get(key)
  if (!icon) {
    const background = stale ? STALE_STYLE.pattern : color
    icon = L.divIcon({
      className: 'station-marker',
      html: `<span class="station-dot${mock ? ' is-mock' : ''}" style="background:${background}"></span>`,
      iconSize: [16, 16], iconAnchor: [8, 8],
    })
    iconCache.set(key, icon)
  }
  return icon
}

type Driver = { metric: string; value: unknown; unit: string }

type Props = {
  stations: Stations
  aquacultureMap?: AquacultureMap | null
  /** Live advisory older than 90 min: neutral hatched markers, tier shown only as "lúc dựng". */
  stale?: boolean
  staleAgeSeconds?: number | null
  exposure?: SiteExposure | null
  theme: Theme
}

export const StationMarkers = memo(function StationMarkers({ stations, aquacultureMap, stale = false, staleAgeSeconds = null, exposure, theme }: Props) {
  const exposureById = useMemo(() => new Map((exposure?.status === 'ready' ? exposure.stations ?? [] : []).map(item => [item.id, item])), [exposure])
  const items = useMemo(() => stations.features.map((feature, index) => {
    if (feature.geometry?.type !== 'Point') return null
    const [longitude, latitude] = feature.geometry.coordinates as [number, number]
    const properties = feature.properties ?? {}
    const advisory = advisoryForStation(aquacultureMap, properties.station, index)
    const status = SEVERITY_STYLE[toSeverity(advisory?.properties?.severity)]
    return { index, latitude, longitude, properties, advisory, status }
  }), [stations, aquacultureMap])
  const mock = aquacultureMap?.mode === 'mock'
  return <>{items.map(item => {
    if (!item) return null
    const site = exposureById.get(String(item.properties.station ?? ''))
    const drivers = (item.advisory?.properties?.drivers ?? []) as Driver[]
    return (
      <Marker key={`station-${String(item.properties.station ?? item.index)}-${item.index}`} position={[item.latitude, item.longitude]}
        icon={stationIcon(item.status.color, mock, stale)} title={`Trạm ${String(item.properties.station ?? '')}${stale ? ' · khuyến nghị cũ' : ` · ${item.status.label}`}`}>
        <Popup maxWidth={340}>
          {/* Explicit width: Leaflet measures the popup before React fills it, which collapses the rose row. */}
          <div style={{ width: site ? 296 : undefined }}>
          {mock && <div className="popup-mock">MÔ PHỎNG · không phải dữ liệu thật</div>}
          <b>{String(item.properties.station ?? 'Trạm')}</b><br />{String(item.properties.name ?? '')}<br />
          {stale ? (
            <>
              <b>Khuyến nghị cũ · {formatAge(staleAgeSeconds)}</b><br />
              <span style={{ opacity: 0.75 }}>Lúc dựng: {item.status.label}. Không phải trạng thái hiện tại.</span>
            </>
          ) : <b style={{ color: item.status.color }}>{item.status.label}</b>}
          {!stale && drivers.length ? <><hr />Yếu tố: {drivers.map(driver => `${driver.metric}=${driver.value} ${driver.unit}`).join(', ')}</> : null}
          {site && <><hr /><ExposureDetail station={site} theme={theme} roseSize={112} /></>}
          </div>
        </Popup>
      </Marker>
    )
  })}</>
})
