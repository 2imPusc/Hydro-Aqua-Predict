/**
 * Research API contract (`/api/v1/research`), see
 * docs/superpowers/plans/2026-10-17-research-map-redesign.md. Every response
 * carries `status` and `export_version`; when `status` is `unavailable` the
 * payload fields may be absent and `reason` explains why.
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
  model_variant: string
  bundle_role: string
  issued_at: string
  valid_at: string
  value: number
  pi80: Interval | null
  pi90: Interval | null
  ph_input_status: string
  sensor_status: string
}
export type LongForecastSkip = { target: string; horizon_min: number; feature_set: string; reason: string; at: string }
export type LongForecastWithdrawn = { target: string; feature_set: string; horizon_min: number; reason: string }
export type LongForecastScore = { target: string; horizon_min: number; model_variant: string; n: number; mae: number | null; persistence_mae: number | null; coverage80: number | null; coverage90: number | null }
/** Live read of the shadow long ledger (no export_version requirement). */
export type LongForecast = Payload<{
  station: string
  ledger_state: 'empty' | 'active' | 'missing'
  latest_issued_at: string | null
  items: LongForecastItem[]
  skips: LongForecastSkip[]
  withdrawn: LongForecastWithdrawn[]
  scoring: LongForecastScore[]
}>

export type BenchmarkRow = { horizon_min: number; feature_set: string; skill: number | null; folds_won: number | string | null; dm_p: number | null; gate: string | boolean | null }
export type ConformalRow = { method: string; horizon_min: number; level: number; coverage: number | null; coverage_late: number | null; width: number | null; winkler: number | null }
export type ForecastBenchmark = Payload<{ temperature: BenchmarkRow[]; ph_clean: BenchmarkRow[]; conformal: ConformalRow[] }>

/* H2 -------------------------------------------------------------------- */
export type WeatherHour = { hour: string; captured: boolean }
export type WeatherStatus = Payload<{
  coverage_24h: number | null
  coverage_7d: number | null
  health: 'healthy' | 'degraded' | 'unavailable'
  last_captured_at: string | null
  hourly: WeatherHour[]
  note: 'observation-only' | string
}>

/* H3 -------------------------------------------------------------------- */
export type SuitabilityVariant = 'A_W_SUM' | 'N1_W_SUM'
export type SuitabilityRegion = 'vn' | 'hk'
export type Suitability = Payload<{
  variant: SuitabilityVariant
  region: SuitabilityRegion
  cells: GeoJSON.FeatureCollection
  farms: GeoJSON.FeatureCollection
  auc: number | null
  notes: string[]
}>

/* H4 -------------------------------------------------------------------- */
export type BBox = [number, number, number, number]
export type ForeignDataset = {
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
  bbox: BBox
  scales: string[]
}
export type ForeignIndex = Payload<{ datasets: ForeignDataset[] }>

export type ReliabilityPair = {
  anchor: string
  target: string
  km: number
  same_regime: boolean
  dsal: number | null
  share: number | null
  ci_low: number | null
  gate80: boolean | null
  gate90: boolean | null
  gate95: boolean | null
  lon1: number
  lat1: number
  lon2: number
  lat2: number
}
export type ReliabilityRadius = { var: string; regime: string; transfer: string; scale: string; gate: string | number; radius_km: number | null }
export type ForeignDetail = Payload<{
  id: string
  stations: GeoJSON.FeatureCollection<GeoJSON.Point, { station: string; habitat?: string; regime_class: string; wet_sal_median: number | null }>
  pairs: ReliabilityPair[]
  radius: ReliabilityRadius[]
  findings: string[]
  available: { vars: string[]; scales: string[]; transfers: string[] }
}>
export type ForeignQuery = { var?: string; scale?: string; transfer?: string }

export type ReliabilityVn = Payload<{
  stations: GeoJSON.FeatureCollection
  layer: GeoJSON.FeatureCollection | null
  nb1_regime: string | null
  pass_counts: Record<string, number>
  notes: string[]
}>
