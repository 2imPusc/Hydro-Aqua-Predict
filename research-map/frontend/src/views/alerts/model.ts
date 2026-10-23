/**
 * Pure helpers for the per-station alert view (#/alerts, Track G).
 * Honesty rule: a tier is only drawn as a state when the record is fresh and evaluated;
 * stale / unavailable / skipped records render neutral with words, never tier colours.
 */
import type { AlertConfig, DataStatus, ExposureClass, StationAlerts, StationHazard, Tier } from '../../types/alerts'

export type TierMeta = AlertConfig['tiers'][number]
export type TierTone = 'ok' | 'info' | 'warn' | 'danger'

/** Fallback when the response carries no `tiers` (mirrors config/alert_tiers.default.json). */
export const DEFAULT_TIERS: TierMeta[] = [
  { tier: 0, label_vi: 'Bình thường', color: 'ok' },
  { tier: 1, label_vi: 'Theo dõi', color: 'info' },
  { tier: 2, label_vi: 'Chuẩn bị', color: 'warn' },
  { tier: 3, label_vi: 'Nguy hiểm', color: 'danger' },
  { tier: 4, label_vi: 'Rất nguy hiểm', color: 'danger' },
]

const TONES: TierTone[] = ['ok', 'info', 'warn', 'danger']
export const tierTone = (tiers: TierMeta[], tier: number): TierTone => {
  const color = tiers.find(item => item.tier === tier)?.color as TierTone | undefined
  return color && TONES.includes(color) ? color : 'danger'
}
export const tierLabel = (tiers: TierMeta[], tier: number) => tiers.find(item => item.tier === tier)?.label_vi ?? `Bậc ${tier}`
/** A tier repeating a lower tier's colour (4 after 3) is drawn solid so the two differ by more than text. */
export const tierSolid = (tiers: TierMeta[], tier: number) => {
  const tone = tierTone(tiers, tier)
  return tiers.some(item => item.tier < tier && tierTone(tiers, item.tier) === tone)
}

/** Fill/text classes per tone: tinted for most tiers, solid for repeated colours. */
export const TINT: Record<TierTone, string> = {
  ok: 'bg-ok-bg text-ok border-[var(--ok-line)]',
  info: 'bg-info-bg text-info border-[var(--info-line)]',
  warn: 'bg-warn-bg text-warn border-[var(--warn-line)]',
  danger: 'bg-danger-bg text-danger border-[var(--danger-line)]',
}
export const SOLID: Record<TierTone, string> = {
  ok: 'bg-ok text-[var(--fg-inverse)] border-transparent',
  info: 'bg-info text-[var(--fg-inverse)] border-transparent',
  warn: 'bg-warn text-[var(--fg-inverse)] border-transparent',
  danger: 'bg-danger text-[var(--fg-inverse)] border-transparent',
}
export const BAR: Record<TierTone, string> = { ok: 'bg-ok', info: 'bg-info', warn: 'bg-warn', danger: 'bg-danger' }
export const tierClass = (tiers: TierMeta[], tier: number) => (tierSolid(tiers, tier) ? SOLID : TINT)[tierTone(tiers, tier)]

export const EXPOSURE_LABEL: Record<ExposureClass, string> = { exposed: 'Lộ gió', semi: 'Nửa kín', sheltered: 'Kín gió' }
export const EXPOSURE_HINT: Record<ExposureClass, string> = {
  exposed: 'Lồng hở hướng gió/sóng lớn (theo phân tích đà gió site-exposure)',
  semi: 'Che chắn một phần',
  sheltered: 'Được che chắn tốt',
}

export const STATUS_LABEL: Record<DataStatus, string> = { fresh: 'Mới', stale: 'Cũ', unavailable: 'Không có dữ liệu' }

/** Vietnamese reason for skip / unavailable codes from core.hazard_runner and storm_tracks. */
const SKIP: Record<string, string> = {
  marine_disabled: 'Chưa bật dữ liệu nhiệt độ biển',
  stale_forecast: 'Bản tin dự báo đã cũ',
  input_unavailable: 'Không lấy được dữ liệu đầu vào',
  provider_request_failed: 'Lỗi khi gọi nhà cung cấp dữ liệu',
  no_exposure_profile: 'Chưa có hồ sơ che chắn của trạm',
  no_forecast_hours: 'Không có giờ dự báo trong khung này',
  unknown_wind_unit: 'Không rõ đơn vị gió',
  no_wind_direction: 'Thiếu hướng gió',
  no_complete_forecast_day: 'Chưa đủ một ngày dự báo trọn',
  no_valid_day: 'Không có ngày hợp lệ',
  no_summary: 'Chưa có tóm tắt quỹ đạo bão',
  no_records: 'Trạm chưa có bản ghi trong sổ cảnh báo',
  no_replay_wind: 'Không có gió phát lại cho trạm',
}
export const skipText = (code: string | null | undefined) => (code ? SKIP[code] ?? code : '')

const HAZARD_SHORT: Record<string, string> = {
  storm_wind: 'Gió tại lồng', wave_height: 'Sóng tại lồng', storm_watch: 'Theo dõi bão', heat: 'Nắng nóng',
  cold: 'Rét', disease_env: 'Nguy cơ dịch bệnh',
}
export const hazardName = (h: Pick<StationHazard, 'hazard' | 'label_vi'>) => HAZARD_SHORT[h.hazard] ?? h.label_vi ?? h.hazard

const nf = (digits: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
/** "cấp 8", "0,32 m", "31,5 °C", "0,62 / 1". */
export function hazardValue(h: StationHazard): string {
  if (h.value == null) return '—'
  switch (h.hazard) {
    case 'storm_wind': return `cấp ${nf(0).format(h.value)}`
    case 'wave_height': return `${nf(2).format(h.value)} m`
    case 'heat': case 'cold': return `${nf(1).format(h.value)} °C`
    case 'disease_env': return `${nf(2).format(h.value)} / 1`
    case 'storm_watch': return `${nf(0).format(h.value * 100)} %`
    default: return `${nf(2).format(h.value)}${h.unit ? ` ${h.unit}` : ''}`
  }
}

/** Fresh, evaluated → its tier; everything else → null (rendered neutral). */
export const usableTier = (h: StationHazard): Tier | null =>
  h.data_status && h.data_status !== 'fresh' ? null : h.skip_reason || h.tier == null ? null : h.tier

/** Highest usable tier hazard first; ties keep ledger order. */
export function topHazard(station: StationAlerts): StationHazard | null {
  let best: StationHazard | null = null
  for (const h of station.current) {
    const t = usableTier(h)
    if (t == null) continue
    if (!best || t > (usableTier(best) ?? -1)) best = h
  }
  return best
}

/** Group key used by the summary and the sort: tier when fresh, else the data state. */
export type Bucket = { kind: 'tier'; tier: Tier } | { kind: 'stale' } | { kind: 'unavailable' }
export function bucketOf(station: StationAlerts): Bucket {
  if (station.data_status === 'fresh' && station.max_tier != null) return { kind: 'tier', tier: station.max_tier }
  return station.data_status === 'stale' ? { kind: 'stale' } : { kind: 'unavailable' }
}
const rank = (b: Bucket) => (b.kind === 'tier' ? 10 + b.tier : b.kind === 'stale' ? 1 : 0)
export const sortStations = (stations: StationAlerts[]) =>
  [...stations].sort((a, b) => rank(bucketOf(b)) - rank(bucketOf(a)) || a.id.localeCompare(b.id, 'vi', { numeric: true }))

/** "Khu vực cảng cá Cát Bà." → "Cảng cá Cát Bà" (drop the generic prefix and trailing dot). */
export const shortName = (name: string) => {
  const trimmed = name.replace(/\.\s*$/, '').replace(/^Khu vực\s+/i, '').trim()
  return trimmed ? trimmed.charAt(0).toUpperCase() + trimmed.slice(1) : name
}

const TZ = 'Asia/Ho_Chi_Minh'
const weekday = new Intl.DateTimeFormat('vi-VN', { timeZone: 'UTC', weekday: 'short' })
const dayMonth = new Intl.DateTimeFormat('vi-VN', { timeZone: 'UTC', day: '2-digit', month: '2-digit' })
const hm = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const dm = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, day: '2-digit', month: '2-digit' })
/** `date` is already a local (UTC+7) calendar date string. */
export function dayLabel(date: string): { weekday: string; date: string } {
  const at = new Date(`${date}T00:00:00Z`)
  if (Number.isNaN(at.getTime())) return { weekday: '', date }
  return { weekday: weekday.format(at), date: dayMonth.format(at) }
}
export const localTime = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso : `${hm.format(at)}, ${dm.format(at)}`
}

export const isReplaySource = (station: StationAlerts) => !!station.replay
