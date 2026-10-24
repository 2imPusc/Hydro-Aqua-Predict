/** Labels, number parsing (decimal comma) and client checks for the field event log. Mirrors core/field_events.py. */
import type { EventSource, EventType, FieldEvent, FieldEventInput, MeasurementKey, Severity } from '../../types/events'

export const OTHER_STATION = 'khac'
export const NOTE_MAX = 1000
export const SHORT_TEXT_MAX = 120
export const MIN_EVENTS_FALLBACK = 10

export const EVENT_TYPES: Array<{ value: EventType; label: string }> = [
  { value: 'ca_chet', label: 'Cá chết' },
  { value: 'ca_bo_an', label: 'Cá bỏ ăn' },
  { value: 'ca_lo_do_noi_dau', label: 'Cá bơi lờ đờ / nổi đầu' },
  { value: 'nuoc_duc_doi_mau', label: 'Nước đục / đổi màu' },
  { value: 'tao_no_hoa', label: 'Tảo nở hoa' },
  { value: 'mua_lon', label: 'Mưa lớn' },
  { value: 'gio_manh_bao', label: 'Gió mạnh / bão' },
  { value: 'hu_hong_long', label: 'Hư hỏng lồng' },
  { value: 'do_tay', label: 'Đo tay (DO / độ mặn / nhiệt độ)' },
  { value: 'khac', label: 'Khác' },
]
export const EVENT_TYPE_LABEL = Object.fromEntries(EVENT_TYPES.map(item => [item.value, item.label])) as Record<EventType, string>

export const SOURCES: Array<{ value: EventSource; label: string }> = [
  { value: 'nguoi_nuoi', label: 'Người nuôi' },
  { value: 'can_bo', label: 'Cán bộ' },
  { value: 'nghien_cuu', label: 'Nghiên cứu' },
]
export const SOURCE_LABEL = Object.fromEntries(SOURCES.map(item => [item.value, item.label])) as Record<EventSource, string>

export const SEVERITIES: Array<{ value: Severity; label: string; hint: string }> = [
  { value: 1, label: 'Nhẹ', hint: 'Thấy dấu hiệu, chưa thiệt hại' },
  { value: 2, label: 'Vừa', hint: 'Ảnh hưởng một phần lồng / đàn' },
  { value: 3, label: 'Nặng', hint: 'Thiệt hại rõ, phải xử lý ngay' },
]
export const SEVERITY_LABEL: Record<Severity, string> = { 1: 'Nhẹ', 2: 'Vừa', 3: 'Nặng' }

/** Plausible ranges (typo guard, not QC thresholds) — same numbers as the server. */
export const MEASUREMENTS: Array<{ key: MeasurementKey; label: string; unit: string; min: number; max: number }> = [
  { key: 'do_mg_l', label: 'DO (oxy hòa tan)', unit: 'mg/L', min: 0, max: 20 },
  { key: 'salinity_psu', label: 'Độ mặn', unit: 'psu', min: 0, max: 45 },
  { key: 'water_temp_c', label: 'Nhiệt độ nước', unit: '°C', min: 5, max: 40 },
  { key: 'secchi_m', label: 'Độ trong (đĩa Secchi)', unit: 'm', min: 0, max: 30 },
]
const SHORT_MEAS_LABEL: Record<MeasurementKey, string> = { do_mg_l: 'DO', salinity_psu: 'Độ mặn', water_temp_c: 'Nhiệt độ', secchi_m: 'Secchi' }

const numberFormat = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 })
export const formatNumber = (value: number) => numberFormat.format(value)

/** "5,2" or "5.2" → 5.2; empty → null; anything else → NaN. */
export function parseDecimal(text: string): number | null {
  const trimmed = text.trim().replace(/\s/g, '')
  if (!trimmed) return null
  if (!/^-?\d+([.,]\d+)?$/.test(trimmed)) return Number.NaN
  return Number(trimmed.replace(',', '.'))
}
export const toDecimalText = (value: number | undefined) => (value === undefined ? '' : formatNumber(value).replace(/\./g, ''))

/** Current Vietnam time as a `datetime-local` value (independent of the browser's zone). */
export function nowVnInput(date = new Date()): string {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(part => [part.type, part.value]))
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

/** Stored values are `YYYY-MM-DDTHH:MM:SS+07:00`, so the local wall time is the first 16 characters. */
export const toVnInput = (iso: string) => iso.slice(0, 16)
export function formatObserved(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  return match ? `${match[4]}:${match[5]} · ${match[3]}/${match[2]}/${match[1]}` : iso
}

export const measurementSummary = (event: FieldEvent) =>
  MEASUREMENTS.filter(spec => event.measurements?.[spec.key] !== undefined)
    .map(spec => `${SHORT_MEAS_LABEL[spec.key]} ${formatNumber(event.measurements[spec.key] as number)} ${spec.unit}`)

export type Draft = {
  observed_at: string
  station_id: string
  station_other: string
  event_type: EventType | ''
  severity: Severity | 0
  measurements: Record<MeasurementKey, string>
  note: string
  reporter: string
  source: EventSource | ''
  supersedes: string | null
}

export const emptyMeasurements = (): Record<MeasurementKey, string> => ({ do_mg_l: '', salinity_psu: '', water_temp_c: '', secchi_m: '' })

export function emptyDraft(keep?: Partial<Draft>): Draft {
  return {
    observed_at: nowVnInput(), station_id: keep?.station_id ?? '', station_other: keep?.station_other ?? '',
    event_type: '', severity: 0, measurements: emptyMeasurements(), note: '',
    reporter: keep?.reporter ?? '', source: keep?.source ?? '', supersedes: null,
  }
}

export function draftFromEvent(event: FieldEvent): Draft {
  const measurements = emptyMeasurements()
  for (const spec of MEASUREMENTS) measurements[spec.key] = toDecimalText(event.measurements?.[spec.key])
  return {
    observed_at: toVnInput(event.observed_at), station_id: event.station_id, station_other: event.station_other ?? '',
    event_type: event.event_type, severity: event.severity, measurements, note: event.note ?? '',
    reporter: event.reporter ?? '', source: event.source, supersedes: event.event_id,
  }
}

export type FieldKey = 'observed_at' | 'station' | 'event_type' | 'severity' | 'note' | 'reporter' | 'source' | MeasurementKey

/** Client checks in plain Vietnamese; the server re-validates everything. */
export function checkDraft(draft: Draft, now = nowVnInput()): { errors: Partial<Record<FieldKey, string>>; payload: FieldEventInput | null } {
  const errors: Partial<Record<FieldKey, string>> = {}
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(draft.observed_at)) errors.observed_at = 'Chọn ngày và giờ quan sát'
  else if (draft.observed_at > addMinutes(now, 15)) errors.observed_at = 'Thời điểm đang ở tương lai'
  else if (draft.observed_at < '2025-01-01T00:00') errors.observed_at = 'Thời điểm quá cũ (trước 2025)'
  if (!draft.station_id) errors.station = 'Chọn điểm nuôi'
  else if (draft.station_id === OTHER_STATION && !draft.station_other.trim()) errors.station = 'Ghi tên điểm nuôi'
  else if (draft.station_other.trim().length > SHORT_TEXT_MAX) errors.station = `Tối đa ${SHORT_TEXT_MAX} ký tự`
  if (!draft.event_type) errors.event_type = 'Chọn loại sự kiện'
  if (!draft.severity) errors.severity = 'Chọn mức độ'
  if (!draft.source) errors.source = 'Chọn nguồn tin'
  const measurements: Partial<Record<MeasurementKey, number>> = {}
  for (const spec of MEASUREMENTS) {
    const value = parseDecimal(draft.measurements[spec.key])
    if (value === null) continue
    if (Number.isNaN(value)) errors[spec.key] = 'Chỉ nhập số, ví dụ 5,2'
    else if (value < spec.min || value > spec.max) errors[spec.key] = `Ngoài khoảng hợp lý ${formatNumber(spec.min)}–${formatNumber(spec.max)} ${spec.unit}`
    else measurements[spec.key] = value
  }
  if (draft.event_type === 'do_tay' && !Object.keys(measurements).length && !MEASUREMENTS.some(spec => errors[spec.key])) {
    errors.do_mg_l = 'Đo tay: nhập ít nhất một số đo'
  }
  const note = draft.note.trim()
  if (note.length > NOTE_MAX) errors.note = `Tối đa ${NOTE_MAX} ký tự`
  else if (draft.event_type === 'khac' && !note) errors.note = 'Loại "Khác": mô tả sự kiện trong ghi chú'
  if (draft.reporter.trim().length > SHORT_TEXT_MAX) errors.reporter = `Tối đa ${SHORT_TEXT_MAX} ký tự`
  if (Object.keys(errors).length || !draft.event_type || !draft.severity || !draft.source) return { errors, payload: null }
  return {
    errors,
    payload: {
      observed_at: draft.observed_at,
      station_id: draft.station_id,
      station_other: draft.station_id === OTHER_STATION ? draft.station_other.trim() : null,
      event_type: draft.event_type,
      severity: draft.severity,
      measurements,
      note: note || null,
      reporter: draft.reporter.trim() || null,
      source: draft.source,
      supersedes: draft.supersedes,
    },
  }
}

function addMinutes(local: string, minutes: number): string {
  const [day, time] = local.split('T')
  const [y, m, d] = day.split('-').map(Number)
  const [hh, mm] = time.split(':').map(Number)
  const shifted = new Date(Date.UTC(y, m - 1, d, hh, mm + minutes))
  return shifted.toISOString().slice(0, 16)
}

const FIELD_VI: Record<string, string> = {
  observed_at: 'Thời điểm', station_id: 'Điểm nuôi', station_other: 'Tên điểm nuôi', event_type: 'Loại sự kiện', severity: 'Mức độ',
  measurements: 'Số đo', note: 'Ghi chú', reporter: 'Người báo', source: 'Nguồn', supersedes: 'Bản sửa', body: 'Dữ liệu',
  ...Object.fromEntries(MEASUREMENTS.map(spec => [`measurements.${spec.key}`, spec.label])),
}

/** Server messages are `field: english text`; show the field in Vietnamese and keep the detail. */
export function describeServerError(message: string): string {
  const at = message.indexOf(':')
  if (at < 0) return message
  const field = message.slice(0, at)
  const detail = message.slice(at + 1).trim()
    .replace(/^required.*/, 'bắt buộc')
    .replace(/^in the future$/, 'đang ở tương lai')
    .replace(/^outside plausible range /, 'ngoài khoảng hợp lý ')
    .replace(/^unknown station.*/, 'trạm không có trong danh sách')
    .replace(/^station registry unavailable$/, 'máy chủ chưa đọc được danh sách trạm')
    .replace(/^at most (\d+) characters$/, 'tối đa $1 ký tự')
  return `${FIELD_VI[field] ?? field}: ${detail}`
}

export const REJECT_REASON_VI: Record<string, string> = {
  already_superseded: 'Sự kiện này đã có bản sửa. Tải lại danh sách và sửa bản mới nhất.',
  supersedes_not_found: 'Không tìm thấy sự kiện gốc để sửa.',
  events_dir_not_writable: 'Máy chủ không ghi được thư mục nhật ký (runtime/events). Sự kiện CHƯA được lưu.',
  events_dir_not_readable: 'Máy chủ không đọc được thư mục nhật ký (runtime/events).',
  station_registry_unavailable: 'Máy chủ chưa đọc được danh sách trạm. Chọn "Khác" và ghi tên điểm nuôi.',
}
