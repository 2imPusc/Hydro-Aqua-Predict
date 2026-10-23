/** Shared alert contracts (docs/superpowers/plans/2026-10-23-phase1-parallel.md, C1–C3). Owner: Track B. */
export type Tier = 0 | 1 | 2 | 3 | 4
export type HazardId = 'storm_wind' | 'wave_height' | 'storm_watch' | 'heat' | 'cold' | 'disease_env'
export type ExposureClass = 'sheltered' | 'semi' | 'exposed'

export type HazardConfig = {
  label_vi: string
  metric: string
  unit: string
  direction: 'ge' | 'le'
  thresholds: Record<string, number>
  persistence_days?: Record<string, number>
  actions_vi: Record<string, string>
  guardrails?: { min?: Record<string, number>; max?: Record<string, number> }
  evidence?: string[]
}

/** Only these hazard fields may be changed by the admin UI (C1/C3); everything else is server-rejected. */
export type EditableField = 'thresholds' | 'actions_vi' | 'persistence_days'
export type HazardOverride = Partial<Pick<HazardConfig, EditableField>>
export type ScopeOverrides = Record<string, HazardOverride>

export type AlertConfigChange = { path: string; old: unknown; new: unknown }

export type AlertConfig = {
  schema_version: number
  config_version: string
  note_vi?: string
  tiers: Array<{ tier: Tier; label_vi: string; color: string }>
  hazards: Record<string, HazardConfig>
  scopes: { exposure_class: Partial<Record<ExposureClass, ScopeOverrides>>; station: Record<string, ScopeOverrides> }
  /** Present on runtime versions (after the first save). */
  parent_version?: string | null
  changes?: AlertConfigChange[]
}

/** A saved runtime version file: full config + provenance. */
export type AlertConfigVersionDetail = AlertConfig & { changed_at?: string; changed_by?: string; reason_vi?: string }

export type AlertConfigResponse = { status: 'ready' | 'unavailable'; reason?: string; effective?: AlertConfig; config_version?: string; source?: 'default' | 'runtime' }
export type AlertConfigVersion = { config_version: string; changed_at: string; changed_by: string; reason_vi: string; n_changes: number }
export type AlertConfigVersionsResponse = { status: 'ready' | 'unavailable'; reason?: string; versions?: AlertConfigVersion[] }
export type AlertConfigVersionResponse = { status: 'ready' | 'unavailable'; reason?: string; version?: AlertConfigVersionDetail }
/** 422 body of save/preview. */
export type AlertConfigInvalid = { status: 'invalid'; errors: string[] }
export type AlertConfigSaved = { status: 'ready'; config_version: string }
export type TierExample = { hazard: string; value: number; tier: Tier | null }
export type AlertConfigPreview = { status: 'ready' | 'invalid'; errors: string[]; tier_examples?: TierExample[] }

export type ActiveStorm = {
  id: string; name: string; run_time: string; members: number
  p_within_500km_120h: number; p_within_200km_120h: number
  closest_approach_km_median: number | null; eta_hours_median: number | null
  track_median: Array<[number, number, string]>
}
export type ActiveStormsResponse = { status: 'ready' | 'unavailable'; reason?: string; fetched_at?: string; source?: string; storms?: ActiveStorm[] }

export type StationHazard = {
  hazard: HazardId; tier: Tier | null; value: number | null; action_vi?: string
  /** Additive (Track G): per-hazard provenance from the C2 ledger. */
  label_vi?: string | null; unit?: string | null; data_status?: DataStatus; skip_reason?: string
  lead_hours?: number; valid_from?: string; valid_to?: string; inputs?: Record<string, unknown>
}
export type DataStatus = 'fresh' | 'stale' | 'unavailable'
export type StationOutlookDay = {
  date: string; max_tier: Tier | null; hazards: StationHazard[]
  /** Additive (Track G): 24 h lead block this day covers (72–120 h window fills days 4–5). */
  data_status?: DataStatus; lead_from_h?: number; lead_to_h?: number; block_from?: string; block_to?: string
}
export type StationStormWatch = {
  source: 'ledger' | 'storms_active'; p_within_500km_120h: number | null; tier: Tier | null; threshold: number | null
  storm_id?: string | null; storm_name?: string | null; run_time?: string | null; issued_at?: string; file?: string
  data_status: DataStatus; action_vi?: string | null; model?: string | null; skip_reason?: string; site_note?: string
}
export type StationAlerts = {
  id: string; name: string; lat: number; lon: number; exposure_class: ExposureClass | null
  current: StationHazard[]; outlook: StationOutlookDay[]
  data_status: DataStatus
  /** Additive (Track G). max_tier counts only fresh, evaluated hazards; null otherwise. */
  issued_at?: string | null; age_hours?: number | null; max_tier?: Tier | null; storm_watch?: StationStormWatch | null
  reason?: string | null; config_version?: string | null; inputs_sources?: string[]; inputs_models?: string[]
  replay?: boolean; replay_labels?: string[]
  used_by_alerts?: false; notification_eligible?: false; basis?: string
}
export type StationHazardsResponse = {
  status: 'ready' | 'unavailable'; reason?: string; issued_at?: string; config_version?: string; stations?: StationAlerts[]
  /** Additive (Track G). */
  generated_at?: string; config_versions?: string[]; tiers?: AlertConfig['tiers']; stale_after_hours?: number
  ledger_files?: string[]; replay?: boolean
}
