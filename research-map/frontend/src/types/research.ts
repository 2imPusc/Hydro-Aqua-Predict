/**
 * Research API contract (`/api/v1/research`), see
 * docs/superpowers/plans/2026-10-17-research-map-redesign.md and the router in
 * research-map/backend-fastapi/app/research.py. Every response carries
 * `status` and (for export-backed endpoints) `export_version`; when `status`
 * is `unavailable` the payload fields may be absent and `reason` explains why.
 */

export type ResearchStatus = 'ready' | 'unavailable'
export type ResearchEnvelope = { status: ResearchStatus; export_version: string | null; reason?: string }
/** Payload fields are only guaranteed when status === 'ready'. */
type Payload<T> = ResearchEnvelope & Partial<T>

export type DirectionId = 'H1' | 'H2' | 'H3' | 'H4'
export type Direction = {
  id: DirectionId
  title: string
  stage: string
  headline: string
  findings: string[]
  limitations: string[]
  research_log: string[]
  next: string[]
}
export type ResearchOverview = Payload<{ generated_at: string; directions: Direction[] }>

/* H1 -------------------------------------------------------------------- */
export type Interval = [number, number]
export type LongForecastItem = {
  target: string
  horizon_min: number
  feature_set: string
  model_variant: string | null
  bundle_role: string | null
  issued_at: string
  valid_at: string
  value: number | null
  current: number | null
  pi80: Interval | null
  pi90: Interval | null
  pi_method: string | null
  ph_input_status: string | null
  sensor_status: string | null
  model_version: string | null
  data_source: string | null
}
export type LongForecastSkip = { target: string; horizon_min: number; feature_set: string; reason: string; at: string | null }
export type LongForecastWithdrawn = { target: string; feature_set: string; horizon_min: number; reason: string | null; withdrawn_at: string | null }
export type LongForecastScore = {
  target: string
  horizon_min: number
  model_variant: string | null
  feature_set: string
  n: number
  n_excluded: number
  mae: number | null
  persistence_mae: number | null
  coverage80: number | null
  coverage90: number | null
}
/** Configured bundle lineup from the model manifest (active + withdrawn). */
export type LongForecastBundle = {
  target: string
  horizon_min: number
  feature_set: string
  variant: string | null
  role: string | null
  pi_method: string | null
  status: string
  withdrawn_reason: string | null
  model_version: string | null
}
/** Live read of the shadow long ledger (no export_version requirement). */
export type LongForecast = Payload<{
  station: string
  mode: string
  used_by_alerts: boolean
  window: string
  ledger_state: 'empty' | 'active' | 'missing'
  latest_issued_at: string | null
  latest_age_minutes: number | null
  items: LongForecastItem[]
  skips: LongForecastSkip[]
  withdrawn: LongForecastWithdrawn[]
  bundles: LongForecastBundle[]
  scoring: LongForecastScore[]
}>

export type Gate = 'pass' | 'fail' | null
export type BenchmarkRow = {
  target: string
  horizon_min: number
  feature_set: string
  /** with_pH | nopH | pH_target */
  variant: string
  skill: number | null
  rolling_skill: number | null
  folds_won: string | null
  dm_p: number | null
  gate: Gate
  lock_mae: number | null
  persistence_mae: number | null
  /** H1.2 | A1 | A3 */
  source: string
  source_run: string
}
export type ConformalRow = {
  target: string
  feature_set: string
  method: string
  horizon_min: number
  level: number
  coverage: number | null
  coverage_late: number | null
  width: number | null
  winkler: number | null
  frac_infinite: number | null
  gate: Gate
  source_run: string
  /** e.g. `invalidated_ph_probe_drift_RL-13`: such rows are not results. */
  validity: string | null
}
export type ForecastBenchmark = Payload<{
  gate_rule: string
  temperature: BenchmarkRow[]
  ph_clean: BenchmarkRow[]
  conformal: ConformalRow[]
  missing_runs: string[]
  notes: string[]
}>

/* H2 -------------------------------------------------------------------- */
export type WeatherHour = { hour: string; captured: boolean }
export type WeatherStatus = Payload<{
  station: string
  source: string
  coverage_24h: number | null
  coverage_7d: number | null
  health: 'healthy' | 'degraded' | 'unavailable'
  last_captured_at: string | null
  age_hours: number | null
  captures_24h: number
  captures_7d: number
  min_coverage: number
  /** 168 UTC hours ending at the current hour. */
  hourly: WeatherHour[]
  note: string
  used_by_alerts: boolean
}>

/* H3 -------------------------------------------------------------------- */
export type SuitabilityVariant = 'A_W_SUM' | 'N1_W_SUM'
export type SuitabilityRegion = 'vn' | 'hk'
export type SuitabilityCellProps = { id: string; score: number | null; percentile: number | null; layers: Record<string, number | null> }
export type Suitability = Payload<{
  variant: SuitabilityVariant
  region: SuitabilityRegion
  source_run: string
  scope: string
  cells: GeoJSON.FeatureCollection<GeoJSON.Point, SuitabilityCellProps> & { cell_size_deg?: number }
  farms: GeoJSON.FeatureCollection
  farms_available: boolean
  auc: number | null
  auc_ci: Interval | null
  notes: string[]
}>

/* H4 -------------------------------------------------------------------- */
export type RegimeClass = 'fresh' | 'estuarine_brackish' | 'transitional' | 'marine' | 'unknown'
export type BBox = [number, number, number, number]
export type ForeignCard = {
  id: string
  name: string
  region: string
  country: string
  cadence: string
  n_stations: number
  n_pairs: number
  period: string
  climate: string
  licence: string
  credit: string
  redistributable: boolean
  headline: string
  research_log?: string
  source_run?: string
}
export type ForeignDataset = ForeignCard & { bbox: BBox; scales: string[] }
export type ForeignIndex = Payload<{ datasets: ForeignDataset[] }>

export type PairGate = 'pass' | 'fail' | null
export type ReliabilityPair = {
  anchor: string
  target: string
  var: string
  transfer: string
  scale: string
  km: number
  /** null for Jobos (habitat-classified) */
  same_regime: boolean | null
  same_habitat?: boolean | null
  dsal: number | null
  share: number | null
  ci_low: number | null
  n_days?: number | null
  gate80: PairGate
  gate90: PairGate
  gate95: PairGate
  lon1: number | null
  lat1: number | null
  lon2: number | null
  lat2: number | null
}
export type ReliabilityRadius = {
  var: string
  regime: string
  transfer: string
  scale: string
  gate: string
  radius_km: number | null
  radius_label?: string | null
  stop?: string | null
  source_run?: string
  group?: string
  metric?: string
}
export type ForeignStationProps = { station: string; name?: string; habitat?: string; group?: string; regime_class: RegimeClass; wet_sal_median: number | null }
export type ForeignDetail = Payload<ForeignCard & {
  stations: GeoJSON.FeatureCollection<GeoJSON.Point, ForeignStationProps> & { regime_class_rule?: string }
  pairs: ReliabilityPair[]
  radius: ReliabilityRadius[]
  findings: string[]
  notes: string[]
  available: { vars: string[]; scales: string[]; transfers: string[] }
  selected: { var: string | null; scale: string | null; transfer: string | null }
}>
export type ForeignQuery = { var?: string; scale?: string; transfer?: string }

export type SummaryRow = { var: string; regime: string; scale: string; radius_km: number | null; radius_label: string | null; stop: string | null }
export type SummaryDataset = { id: string; name: string; cadence: string; scales: string[]; n_stations: number; research_log?: string; headline: string; detail_available: boolean; rows: SummaryRow[] }
export type ReliabilitySummary = Payload<{ gate: string; transfer: string; regime_rule: string; datasets: SummaryDataset[] }>

export type VnStationProps = { region: string; station: string; salinity_source: string; wet_median_sal: number | null; dry_median_sal: number | null; regime_class: RegimeClass; coordinate_suspect: boolean }
export type VnCellProps = { regime_class: RegimeClass; regime_basis: string; nearest_obs_station: string; nearest_obs_km: number; nearest_obs_wet_median_sal: number | null; idw_obs_wet_median_sal: number | null; idw_obs_regime_class: RegimeClass }
export type VnNearestStation = { region: string; station: string; distance_km: number; wet_median_sal: number | null; dry_median_sal: number | null; regime_class: RegimeClass }
export type VnNb1Regime = {
  scope: string
  not_for_runtime: boolean
  used_by_alerts: boolean
  nb1_lat: number
  nb1_lon: number
  nb1_model_derived_wet_median_sal: number | null
  nb1_model_derived_class: RegimeClass
  nearest_observed_stations: VnNearestStation[]
  nb1_observed_regime_class_by_nearest: RegimeClass
  hp_stations_sharing_model_regime: string[]
  qn_observed_same_regime_as_nb1_nearest: number
  nearest8_within_2psu_of_nearest: string[]
}
export type VnPassCount = {
  region: string
  protocol: string
  variable: string
  regime_relation: string
  coverage: number
  n_cells: number
  n_pass_strict: number
  n_insufficient_strict: number | null
  n_relaxed_diagnostic_pass: number | null
  model_derived: boolean
}
export type ReliabilityVn = Payload<{
  source_run: string
  stations: GeoJSON.FeatureCollection<GeoJSON.Point, VnStationProps>
  layer: (GeoJSON.FeatureCollection<GeoJSON.Point, VnCellProps> & { grid_step_m?: number; n_unassigned_omitted?: number }) | null
  nb1_regime: VnNb1Regime | null
  pass_counts: VnPassCount[]
  notes: string[]
}>

/* Shell ------------------------------------------------------------------ */
export type FreshState = 'fresh' | 'stale' | 'unavailable'
export type ApiStatus = {
  status: 'ok' | 'degraded'
  generated_at: string
  context: { status: FreshState; reason?: string; snapshot_id?: string; retrieved_at?: string; age_seconds?: number }
  sensor: { status: FreshState; reason?: string; station_serial: string; latest_observed_at?: string; age_seconds?: number }
  research: { status: ResearchStatus; export_version: string | null }
}
