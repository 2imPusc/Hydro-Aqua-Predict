import { useCallback } from 'react'
import { getAquacultureMap, getBathymetryContours, getBathymetryDepthBands, getBathymetryManifest, getContextDomain, getHsiZones, getStationNetwork, getStations } from '../../api/monitor'
import { usePolling } from '../../hooks/usePolling'
import type { DataMode } from '../../types/monitor'
import type { Lod } from '../../components/map/mapConfig'

export type LayerKey =
  | 'hsi_zones' | 'context_buffer' | 'station_network'
  | 'flow_streamlines' | 'wind_particles'
  | 'rain' | 'wave' | 'sea_level' | 'mixed_layer_depth'
  | 'bathymetry_bands' | 'bathymetry_contours' | 'bathymetry_slope'
export type EnabledLayers = Record<LayerKey, boolean>

export const DEFAULT_LAYERS: EnabledLayers = {
  // Legacy HSI is off by default: HP salinity/temperature behind it are model-gridded
  // (CMEMS/GLORYS), not measured (RL-25), so it is not validated evidence.
  hsi_zones: false, context_buffer: true, station_network: true,
  flow_streamlines: false, wind_particles: false,
  rain: false, wave: false, sea_level: false, mixed_layer_depth: false,
  bathymetry_bands: false, bathymetry_contours: false, bathymetry_slope: false,
}
/** Scalar/vector environmental layers are mutually exclusive to keep the map legible. */
export const ENVIRONMENT_LAYERS = ['rain', 'wave', 'sea_level', 'mixed_layer_depth'] as const

const ONE_SHOT = { keepPreviousData: true, maxErrorRetries: 6, retryBaseMs: 5_000 } as const

/** Monitor-only feeds (the snapshot and sensor feeds live in LiveDataContext). */
export function useMonitorData({ enabled, lod, mode, scenario }: { enabled: EnabledLayers; lod: Lod; mode: DataMode; scenario: string }) {
  const stations = usePolling(getStations, ONE_SHOT)
  const domain = usePolling(getContextDomain, ONE_SHOT)
  const network = usePolling(getStationNetwork, { ...ONE_SHOT, isBuilding: value => value.network_status === 'building', buildingIntervalMs: 8_000, maxBuildingRetries: 60 })
  const zones = usePolling(getHsiZones, { ...ONE_SHOT, enabled: enabled.hsi_zones, isBuilding: value => value.status === 'building', buildingIntervalMs: 10_000, maxBuildingRetries: 30 })
  const bathymetry = usePolling(getBathymetryManifest, { ...ONE_SHOT, isBuilding: value => value.status === 'building', buildingIntervalMs: 10_000, maxBuildingRetries: 60 })

  const bathymetryReady = bathymetry.data?.status === 'ready'
  const bathymetryOn = enabled.bathymetry_bands || enabled.bathymetry_contours || enabled.bathymetry_slope
  const bands = usePolling(signal => getBathymetryDepthBands(lod, signal), { enabled: bathymetryOn && bathymetryReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })
  const contours = usePolling(signal => getBathymetryContours(lod, signal), { enabled: enabled.bathymetry_contours && bathymetryReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })

  // Mode/scenario changes reset the map so a live advisory is never shown under a mock label (or vice versa).
  const aquaculture = usePolling(signal => getAquacultureMap(mode, scenario, signal), {
    deps: [mode, scenario], intervalMs: mode === 'live' ? 60_000 : 300_000,
    isBuilding: value => value.status === 'building', buildingIntervalMs: 2_000, maxBuildingRetries: 30,
    clearOnError: true, retryBaseMs: 5_000,
  })

  const refreshAll = useCallback(() => {
    for (const feed of [stations, domain, network, zones, bathymetry, aquaculture]) feed.refresh()
  }, [stations, domain, network, zones, bathymetry, aquaculture])

  return { stations, domain, network, zones, bathymetry, bands, contours, aquaculture, refreshAll }
}
