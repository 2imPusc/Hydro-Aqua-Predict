export type LayerName = 'wind' | 'rain' | 'wave' | 'current' | 'sea_level' | 'mixed_layer_depth' | 'bathymetry' | 'advisory_forecast'
export type Layer = { layer: LayerName; status: 'fresh' | 'stale' | 'unavailable'; kind: string; reason_code?: string; provenance?: { source: string; provider: string; product_id?: string; grid_resolution: string; display_grid_resolution?: string; source_grid_resolution?: string; temporal_mode?: string; valid_at?: string; retrieved_at: string; direction_convention?: string }; geojson?: GeoJSON.FeatureCollection; raster?: Record<string, unknown>; data?: unknown }
export type Snapshot = { snapshot_id: string; status: 'fresh' | 'stale' | 'unavailable'; retrieved_at: string; age_seconds: number; bbox: number[]; domain_id?: string; geometry_hash?: string; layers: Layer[] }
export type HsiZones = { observed_at: string | null; mode: string; status?: 'building' | 'ready'; features: GeoJSON.Feature[] }
export type Stations = GeoJSON.FeatureCollection
export type ContextDomain = GeoJSON.FeatureCollection
export type StationNetwork = GeoJSON.FeatureCollection & { edge_count: number; flow_streamline_count?: number; network_status: 'ready' | 'building'; influence_status: 'exploratory' | 'unavailable'; influence_reason?: string; influenced_edge_count?: number }
export type FlowArtifact = GeoJSON.FeatureCollection & { artifact_id: string; algorithm_version: string; snapshot_id: string; payload_hash: string; geometry_hash?: string; retrieved_at: string; valid_at?: string | null; status: 'fresh' | 'stale' | 'unavailable'; provenance?: Record<string, unknown>; mode: string; streamline_count: number; ray_count?: number; current_supported_station_edge_count: number }
export type FlowLatest = { flow_id?: string; status: 'fresh' | 'stale' | 'unavailable'; mode: string; streamline_count: number; station_route_count: number; geometry_hash?: string; provenance?: Record<string, unknown> }
export type FlowScenarios = { scenarios: Array<{ id: string; label: string; available: boolean; mode: string }>; source?: string }
export type SensorObservation = { observation_id: string; station_serial: string; metric: string; value: number; unit: string; observed_at: string; ingested_at: string; source_type: string; qc_status: string; qc_reason?: string | null; provenance?: Record<string, unknown> }
export type SensorLatest = { station_serial: string; status: 'fresh' | 'stale' | 'unavailable'; latest_observed_at?: string | null; age_seconds?: number | null; observations: SensorObservation[]; reason_code?: string | null }
export type AquacultureMap = GeoJSON.FeatureCollection & { status: 'ready' | 'building' | 'unavailable'; artifact_version: string; mode: 'live' | 'mock'; scenario: string; generated_at?: string; source?: Record<string, string>; disclaimer?: string }
export type BathymetryManifest = { status: 'ready' | 'building' | 'unavailable'; artifact_version?: string; source?: string; source_resolution?: string; quality_rule?: string; coverage_fraction?: number; valid_pixel_count?: number; depth_source?: string; disclaimer?: string; reason_code?: string }
export type BathymetryVectorLayer = GeoJSON.FeatureCollection & { status: 'ready' | 'building' | 'unavailable'; lod?: string; artifact_version?: string; depth_source?: string; reason_code?: string }
export type BathymetrySample = { status: 'available' | 'unavailable'; copernicus_depth_m?: number; quality_indicator?: number; sdb_type?: number; slope_degrees?: number | null; depth_source?: string; disclaimer?: string; reason_code?: string; etopo?: EtopoSample; gebco?: GebcoSample }
export type EtopoSample = { status: 'available' | 'unavailable'; etopo_depth_m?: number; nearest_cell_is_sea?: boolean; suspect?: boolean; source_resolution?: string; vertical_datum?: string; reason_code?: string }
export type TidConfidence = 'direct' | 'indirect' | 'unknown'
export type GebcoSample = { status: 'available' | 'unavailable'; gebco_depth_m?: number; nearest_cell_is_sea?: boolean; suspect?: boolean; tid?: number; tid_confidence?: TidConfidence; source_resolution?: string; vertical_datum?: string; reason_code?: string }
export type GebcoManifest = EtopoManifest & { direct_cell_count?: number; indirect_cell_count?: number; unknown_cell_count?: number; depth_cell_count?: number; confidence_classes?: Record<string, string> }
export type EtopoManifest = { status: 'ready' | 'building' | 'unavailable'; artifact_version?: string; source?: string; citation?: string; source_resolution?: string; vertical_datum?: string; band_edges_m?: number[]; isobaths_m?: number[]; coarse_cell_count?: number; suspect_cell_count?: number; water_cell_count?: number; disclaimer?: string; reason_code?: string }

export type DataMode = 'live' | 'mock'
/** Freshness / provenance states shown by status chips across every view. */
export type DataState = 'live' | 'fresh' | 'stale' | 'cache' | 'mock' | 'research_only' | 'withdrawn' | 'unavailable' | 'building' | 'loading' | 'exploratory' | 'legacy'
