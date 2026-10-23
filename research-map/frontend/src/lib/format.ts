/** Display helpers shared by the research views (Vietnamese labels, tabular numbers). */

/** Vietnamese decimal comma: "0.58" → "0,58". Display only; never parse the result. */
export const viDecimal = (text: string) => text.replace('.', ',')

export function horizonLabel(minutes: number | null | undefined): string {
  if (minutes == null) return '—'
  if (minutes < 60) return `${minutes} phút`
  const hours = minutes / 60
  return `${Number.isInteger(hours) ? hours : viDecimal(hours.toFixed(1))} giờ`
}
export const horizonShort = (minutes: number) => (minutes < 60 ? `${minutes}′` : `${minutes / 60} h`)

/** 0–1 fraction → "52 %". */
export function pct(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${viDecimal((value * 100).toFixed(digits))} %`
}
/** Already-percent value (e.g. skill 20.1) → "+20,1 %". */
export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value > 0 ? '+' : ''}${viDecimal(value.toFixed(digits))} %`
}
export function num(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return viDecimal(value.toFixed(digits))
}
export function pValue(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value < 1e-3) {
    const [mantissa, exponent] = value.toExponential(1).split('e')
    const sup = exponent.replace('+', '').replace(/[-0-9]/g, char => '⁻⁰¹²³⁴⁵⁶⁷⁸⁹'['-0123456789'.indexOf(char)])
    return `${viDecimal(mantissa)}·10${sup}`
  }
  return viDecimal(value.toPrecision(2))
}

const FEATURE_SET: Record<string, string> = {
  B0_lags: 'B0 · chỉ trễ',
  B1_calendar: 'B1 · lịch',
  B2_dynamics: 'B2 · động học',
  B3_cross_sensor: 'B3 · liên cảm biến',
  B4_quality: 'B4 · chất lượng',
  B5_external_as_issued: 'B5 · thời tiết',
  B6_tide: 'B6 · thủy triều',
}
export const baseFeatureSet = (featureSet: string) => featureSet.replace(/_nopH$/, '')
export const isNoPh = (featureSet: string) => featureSet.endsWith('_nopH')
export function featureSetLabel(featureSet: string): string {
  const base = baseFeatureSet(featureSet)
  return `${FEATURE_SET[base] ?? base}${isNoPh(featureSet) ? ' (không pH)' : ''}`
}

const METHOD: Record<string, string> = {
  static: 'static',
  static_night: 'static_night',
  aci_scaled: 'aci_scaled (mặc định)',
  aci_amp: 'aci_amp (biên độ ngày–đêm)',
}
export const methodLabel = (method: string) => METHOD[method] ?? method

const VARIABLE: Record<string, string> = {
  Temp: 'Nhiệt độ', Temperature: 'Nhiệt độ', Sal: 'Độ mặn', Salinity: 'Độ mặn', 'Sal@nonfresh': 'Độ mặn (bỏ nước ngọt)',
  pH: 'pH', 'pH@0.1': 'pH (±0,1)', DO: 'DO', Turb: 'Độ đục', TSS: 'TSS', NH3: 'NH3', 'NH3@rel30': 'NH3 (±30 %)', HSI: 'HSI',
}
export const variableLabel = (name: string) => VARIABLE[name] ?? name

const TRANSFER: Record<string, string> = { raw: 'Thô', calibrated: 'Hiệu chỉnh' }
export const transferLabel = (name: string) => TRANSFER[name] ?? name
const SCALE: Record<string, string> = { hourly: 'Theo giờ', daily: 'Theo ngày', monthly: 'Theo tháng' }
export const scaleLabel = (name: string) => SCALE[name] ?? name
const REGIME_RELATION: Record<string, string> = { same: 'Cùng chế độ', different: 'Khác chế độ', all: 'Tất cả', same_regime: 'Cùng chế độ' }
export const regimeRelationLabel = (name: string) => REGIME_RELATION[name] ?? name

export function gateLabel(gate: string): string {
  const match = /^gate(\d+)$/.exec(gate)
  return match ? `${match[1]} %` : gate
}

/** "fail@10-20" → "dừng ở ô 10–20 km". */
export function stopLabel(stop: string | null | undefined): string | null {
  if (!stop) return null
  const match = /^fail@(\d+)-(\d+)$/.exec(stop)
  return match ? `trượt ở ô ${match[1]}–${match[2]} km` : stop
}

export const radiusText = (row: { radius_km: number | null; radius_label?: string | null }) =>
  row.radius_label ?? (row.radius_km == null ? 'không xác định' : `${row.radius_km % 1 === 0 ? row.radius_km.toFixed(0) : row.radius_km.toFixed(1)} km`)

/** Splits "text [RL-14]" into the text and its research-log refs. */
export function splitRefs(text: string): { text: string; refs: string[] } {
  const refs: string[] = []
  const stripped = text.replace(/\s*\[((?:RL|H)[^\]]*)\]\s*\.?\s*$/, (_match, inner: string) => {
    refs.push(...inner.split(/,\s*/))
    return ''
  })
  return { text: stripped, refs }
}

const PROVIDER: Record<string, string> = { open_meteo: 'Open-Meteo', openmeteo: 'Open-Meteo', copernicus: 'Copernicus Marine', cmems: 'Copernicus Marine', ecmwf: 'ECMWF', noaa: 'NOAA' }
/** Data provider id → display name ("open_meteo" → "Open-Meteo"). */
export const providerLabel = (provider?: string | null) => (provider ? PROVIDER[provider.toLowerCase()] ?? provider : 'nguồn chưa rõ')

/**
 * Backend `reason_code` → short Vietnamese phrase for a layer toggle or card.
 * The raw code stays available to callers (title / "Nguồn" disclosure); it is never the only text a user reads.
 */
export function layerReason(code?: string | null): string {
  if (!code) return 'không khả dụng'
  if (/_not_configured$/.test(code)) return 'chưa cấu hình nguồn dữ liệu'
  if (/_(artifact|lod)_not_ready$|_building$/.test(code)) return 'đang dựng lớp…'
  if (/_file_missing$/.test(code)) return 'chưa có file dữ liệu'
  if (/^outside_/.test(code)) return 'ngoài vùng có dữ liệu'
  if (/run_missing$|_missing/.test(code)) return 'chưa có dữ liệu'
  return 'không khả dụng'
}

const SENSOR_METRIC: Record<string, string> = { Temperature: 'Nhiệt độ', Temp: 'Nhiệt độ', Salinity: 'Độ mặn', DO: 'DO', pH: 'pH', NH4: 'NH4', COD: 'COD', TSS: 'TSS' }
export const sensorMetricLabel = (metric: string) => SENSOR_METRIC[metric] ?? metric
const UNIT: Record<string, string> = { degC: '°C', degc: '°C', celsius: '°C', vendor_unit_unknown: 'đơn vị ?', psu: 'psu', 'mg/l': 'mg/L' }
export const unitLabel = (unit?: string | null) => (unit ? UNIT[unit] ?? UNIT[unit.toLowerCase()] ?? unit : '')
const QC: Record<string, string> = { UNCHECKED: 'Chưa kiểm', PASS: 'Hợp lệ', OK: 'Hợp lệ', VALID: 'Hợp lệ', SUSPECT: 'Nghi ngờ', FAIL: 'Lỗi', INVALID: 'Lỗi', RAIL: 'Kịch thang', STUCK: 'Đứng giá trị' }
/** QC status code → Vietnamese chip text ("UNCHECKED" → "Chưa kiểm"). */
export const qcLabel = (status: string) => QC[status.toUpperCase()] ?? status

/** Pulls a short grid size ("~8 km", "1.2 km", "460 m") out of a provenance string; null when there is none. */
export function gridSize(text?: string | null): string | null {
  const match = text ? /~?\s?\d+(?:[.,]\d+)?\s?(?:km|m)\b/.exec(text) : null
  return match ? viDecimal(match[0].replace(/\s+/g, ' ').replace('~ ', '~')) : null
}
