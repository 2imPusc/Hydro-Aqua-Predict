/** Field event log ("Nhật ký sự kiện"). Contract: backend app/events.py + core/field_events.py. */
export type EventType =
  | 'ca_chet' | 'ca_bo_an' | 'ca_lo_do_noi_dau' | 'nuoc_duc_doi_mau' | 'tao_no_hoa'
  | 'mua_lon' | 'gio_manh_bao' | 'hu_hong_long' | 'do_tay' | 'khac'
export type EventSource = 'nguoi_nuoi' | 'can_bo' | 'nghien_cuu'
export type MeasurementKey = 'do_mg_l' | 'salinity_psu' | 'water_temp_c' | 'secchi_m'
export type Severity = 1 | 2 | 3

export type FieldEventInput = {
  /** Local Vietnam time `YYYY-MM-DDTHH:MM`; the server stores it with +07:00. */
  observed_at: string
  station_id: string
  station_other?: string | null
  event_type: EventType
  severity: Severity
  measurements?: Partial<Record<MeasurementKey, number>>
  note?: string | null
  reporter?: string | null
  source: EventSource
  supersedes?: string | null
}

export type FieldEvent = {
  event_id: string
  schema_version: number
  created_at: string
  /** ISO with +07:00. */
  observed_at: string
  station_id: string
  station_other: string | null
  event_type: EventType
  severity: Severity
  measurements: Partial<Record<MeasurementKey, number>>
  note: string | null
  reporter: string | null
  source: EventSource
  supersedes: string | null
  /** Derived by the server: id of the correction that replaced this event. */
  superseded_by: string | null
}

export type FieldEventList = {
  status: 'ready'
  events: FieldEvent[]
  count: number
  total_active: number
  total_superseded: number
  min_events_for_calibration: number
}

export type EventCreated = { status: 'ready'; event: FieldEvent }
export type EventInvalid = { status: 'invalid'; errors: string[] }
export type EventRejected = { status: 'conflict' | 'unavailable'; reason: string }
