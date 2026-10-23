import { ApiError, getJson } from '../../api/client'

/** Mirrors `GET /api/v1/research/site-exposure` (backend `app/site_exposure_layer.py`). Theory only. */
export type ExposureClass = 'exposed' | 'semi' | 'sheltered'
export type RoseSector = {
  direction: string
  bearing: number | null
  fetch_km: number | null
  fetch_censored: boolean | null
  hs_m: number | null
  wave_class: string | null
  tier: number | null
  local_beaufort: number | null
  shelter_factor: number | null
}
export type ExposureStation = {
  id: string
  name: string | null
  lon: number | null
  lat: number | null
  exposure_class: ExposureClass | null
  exposure_label_vi: string | null
  worst_direction: string | null
  dangerous_directions: string[]
  watch_directions: string[]
  sheltered_directions: string[]
  fetch_straight_worst_km: number | null
  fetch_effective_max_km: number | null
  hs_worst_m: { c8: number | null; c10: number | null; c12: number | null }
  tier_worst: { c8: number | null; c10: number | null; c12: number | null }
  depth_site_m: number | null
  depth_site_flag: string | null
  current_p95_ms: number | null
  current_class_p95: string | null
  rose: RoseSector[]
}
export type SiteExposure = {
  status: 'ready' | 'unavailable'
  reason?: string
  run_name?: string
  created_at?: string | null
  rose_beaufort?: number
  rose_wind_ms?: number
  dangerous_hs_m?: number
  watch_hs_m?: number
  method_vi?: string
  stations?: ExposureStation[]
  used_by_alerts: false
  notification_eligible: false
  basis: 'theory_only_unvalidated'
}

export async function getSiteExposure(signal?: AbortSignal): Promise<SiteExposure> {
  try {
    return await getJson<SiteExposure>('/research/site-exposure', signal)
  } catch (error) {
    // Older backend without the layer: an explicit unavailable state, never a fallback.
    if (error instanceof ApiError && error.status === 404) return { status: 'unavailable', reason: 'site_exposure_api_missing', used_by_alerts: false, notification_eligible: false, basis: 'theory_only_unvalidated' }
    throw error
  }
}

export const EXPOSURE_LABEL: Record<ExposureClass, string> = { exposed: 'hở', semi: 'bán kín', sheltered: 'kín' }
export const EXPOSURE_ORDER: ExposureClass[] = ['exposed', 'semi', 'sheltered']
export const DANGEROUS_HS_M = 2.0
export const WATCH_HS_M = 1.0
/** Rose radius saturates here (largest Hs in the 20261023 run at cấp 10 ≈ 3.3 m). */
export const ROSE_HS_MAX = 3.5

export const DIRECTION_VI: Record<string, string> = {
  N: 'B', NNE: 'BĐB', NE: 'ĐB', ENE: 'ĐĐB', E: 'Đ', ESE: 'ĐĐN', SE: 'ĐN', SSE: 'NĐN',
  S: 'N', SSW: 'NTN', SW: 'TN', WSW: 'TTN', W: 'T', WNW: 'TTB', NW: 'TB', NNW: 'BTB',
}
export const directionVi = (direction: string) => DIRECTION_VI[direction] ?? direction

export type HsBand = 'danger' | 'watch' | 'low' | 'none'
export const hsBand = (hs: number | null | undefined): HsBand =>
  hs == null || !Number.isFinite(hs) ? 'none' : hs >= DANGEROUS_HS_M ? 'danger' : hs >= WATCH_HS_M ? 'watch' : 'low'

/** SVG path of one rose wedge centred on `bearing` (deg from north, wind FROM that direction). */
export function wedgePath(cx: number, cy: number, inner: number, outer: number, bearing: number, halfWidthDeg = 9.5): string {
  const point = (r: number, deg: number) => {
    const rad = (deg - 90) * Math.PI / 180
    return `${(cx + r * Math.cos(rad)).toFixed(2)} ${(cy + r * Math.sin(rad)).toFixed(2)}`
  }
  const a0 = bearing - halfWidthDeg, a1 = bearing + halfWidthDeg
  return `M ${point(inner, a0)} L ${point(outer, a0)} A ${outer} ${outer} 0 0 1 ${point(outer, a1)} L ${point(inner, a1)} A ${inner} ${inner} 0 0 0 ${point(inner, a0)} Z`
}

export const roseRadius = (hs: number, inner: number, outer: number) =>
  inner + (outer - inner) * Math.min(1, Math.max(0, hs) / ROSE_HS_MAX)
