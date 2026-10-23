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

export type AlertConfig = {
  schema_version: number
  config_version: string
  note_vi?: string
  tiers: Array<{ tier: Tier; label_vi: string; color: string }>
  hazards: Record<string, HazardConfig>
  scopes: { exposure_class: Partial<Record<ExposureClass, Record<string, Partial<HazardConfig>>>>; station: Record<string, Record<string, Partial<HazardConfig>>> }
}

export type AlertConfigResponse = { status: 'ready' | 'unavailable'; reason?: string; effective?: AlertConfig; config_version?: string; source?: 'default' | 'runtime' }
export type AlertConfigVersion = { config_version: string; changed_at: string; changed_by: string; reason_vi: string; n_changes: number }

export type ActiveStorm = {
  id: string; name: string; run_time: string; members: number
  p_within_500km_120h: number; p_within_200km_120h: number
  closest_approach_km_median: number | null; eta_hours_median: number | null
  track_median: Array<[number, number, string]>
}
export type ActiveStormsResponse = { status: 'ready' | 'unavailable'; reason?: string; fetched_at?: string; source?: string; storms?: ActiveStorm[] }

export type StationHazard = { hazard: HazardId; tier: Tier | null; value: number | null; action_vi?: string }
export type StationAlerts = {
  id: string; name: string; lat: number; lon: number; exposure_class: ExposureClass | null
  current: StationHazard[]; outlook: Array<{ date: string; max_tier: Tier | null; hazards: StationHazard[] }>
  data_status: 'fresh' | 'stale' | 'unavailable'
}
export type StationHazardsResponse = { status: 'ready' | 'unavailable'; reason?: string; issued_at?: string; config_version?: string; stations?: StationAlerts[] }
