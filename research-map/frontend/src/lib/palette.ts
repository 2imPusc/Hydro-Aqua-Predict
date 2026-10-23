import type { Theme } from '../hooks/useTheme'
import type { RegimeClass } from '../types/research'

/**
 * Colour roles for research maps (canvas needs concrete hex; SVG charts use the
 * `--series-*` CSS tokens). Categorical hues come from the validated reference
 * palette; every map colour is paired with a text label in legends/popups.
 */

export const REGIME_ORDER: RegimeClass[] = ['fresh', 'estuarine_brackish', 'transitional', 'marine', 'unknown']
export const REGIME_LABEL: Record<RegimeClass, string> = {
  fresh: 'Nước ngọt (< 0,5)',
  estuarine_brackish: 'Lợ cửa sông (0,5–20)',
  transitional: 'Chuyển tiếp (20–28)',
  marine: 'Biển (≥ 28 psu)',
  unknown: 'Chưa xác định',
}
export const REGIME_SHORT: Record<RegimeClass, string> = {
  fresh: 'Ngọt', estuarine_brackish: 'Lợ', transitional: 'Chuyển tiếp', marine: 'Biển', unknown: 'Chưa rõ',
}
/** Validated all-pairs (light): violet, amber, aqua, blue + neutral grey for unknown. */
const REGIME_COLOR: Record<Theme, Record<RegimeClass, string>> = {
  light: { fresh: '#4a3aa7', estuarine_brackish: '#eda100', transitional: '#1baf7a', marine: '#2a78d6', unknown: '#98a2b3' },
  dark: { fresh: '#9085e9', estuarine_brackish: '#e0a100', transitional: '#22b884', marine: '#3987e5', unknown: '#7d8ba0' },
}
export const regimeColor = (regime: string | null | undefined, theme: Theme) =>
  REGIME_COLOR[theme][(regime as RegimeClass) in REGIME_COLOR[theme] ? (regime as RegimeClass) : 'unknown']
export const regimeLabel = (regime: string | null | undefined) => REGIME_LABEL[(regime as RegimeClass)] ?? String(regime ?? '—')

function hexToRgb(hex: string): [number, number, number] {
  const value = parseInt(hex.slice(1), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}
const toHex = (rgb: number[]) => `#${rgb.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('')}`
function mix(a: string, b: string, t: number): string {
  const ca = hexToRgb(a), cb = hexToRgb(b)
  return toHex(ca.map((v, i) => v + (cb[i] - v) * t))
}
/** Piecewise-linear interpolation over evenly spaced stops. */
export function ramp(stops: string[], t: number): string {
  const clamped = Math.max(0, Math.min(1, t))
  const scaled = clamped * (stops.length - 1)
  const index = Math.min(stops.length - 2, Math.floor(scaled))
  return mix(stops[index], stops[index + 1], scaled - index)
}

/** Sequential single-hue blue ramp for magnitude (suitability score). Dark mode: high = light. */
export const SEQUENTIAL: Record<Theme, string[]> = {
  light: ['#cde2fb', '#86b6ef', '#3987e5', '#256abf', '#104281'],
  dark: ['#104281', '#1c5cab', '#2a78d6', '#6da7ec', '#cde2fb'],
}
export const sequentialColor = (t: number, theme: Theme) => ramp(SEQUENTIAL[theme], t)
export const sequentialGradient = (theme: Theme) => `linear-gradient(90deg, ${SEQUENTIAL[theme].join(', ')})`

/**
 * Diverging scale for pair share, centred on the 80 % gate: red arm below,
 * blue arm above, neutral grey at the gate itself.
 */
export const SHARE_GATE = 0.8
const DIVERGING: Record<Theme, { low: string[]; mid: string; high: string[] }> = {
  light: { low: ['#b42318', '#e34948', '#f0a59a'], mid: '#a3a3a0', high: ['#86b6ef', '#2a78d6', '#104281'] },
  dark: { low: ['#ff6b5f', '#e66767', '#8f4a45'], mid: '#6b6b66', high: ['#2f5f9e', '#3987e5', '#9ec5f4'] },
}
export function shareColor(share: number | null | undefined, theme: Theme): string {
  const palette = DIVERGING[theme]
  if (share == null || !Number.isFinite(share)) return palette.mid
  if (share < SHARE_GATE) return ramp([...palette.low, palette.mid], share / SHARE_GATE)
  return ramp([palette.mid, ...palette.high], (share - SHARE_GATE) / (1 - SHARE_GATE))
}
/** CSS gradient whose geometry matches `shareColor` (gate at 80 % of the width). */
export function shareGradient(theme: Theme): string {
  const palette = DIVERGING[theme]
  const lowStops = [...palette.low, palette.mid].map((color, index, list) => `${color} ${(index / (list.length - 1)) * 80}%`)
  const highStops = palette.high.map((color, index, list) => `${color} ${80 + ((index + 1) / list.length) * 20}%`)
  return `linear-gradient(90deg, ${[...lowStops, ...highStops].join(', ')})`
}
