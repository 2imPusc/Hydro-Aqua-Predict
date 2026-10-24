import { useCallback, useEffect } from 'react'
import { SYNC_EVENT } from '../../app/useSync'
import { getAquacultureMap, getBathymetryContours, getBathymetryDepthBands, getBathymetryManifest, getContextDomain, getContextRegion, getEtopoLayer, getEtopoManifest, getGebcoLayer, getGebcoManifest, getSeabedShade, getHsiZones, getStationNetwork, getStations } from '../../api/monitor'
import { usePolling } from '../../hooks/usePolling'
import { getReliabilityVn } from '../../api/research'
import { getSiteExposure } from '../../components/map/siteExposure'
import type { DataMode } from '../../types/monitor'
import type { Lod } from '../../components/map/mapConfig'

export type LayerKey =
  | 'hsi_zones' | 'context_buffer' | 'station_network'
  | 'flow_streamlines' | 'wind_particles'
  | 'rain' | 'wave' | 'sea_level' | 'mixed_layer_depth' | 'advisory_forecast'
  | 'depth_isobands' | 'depth_isobaths' | 'depth_etopo' | 'depth_slope'
  | 'bathymetry_bands' | 'bathymetry_contours' | 'bathymetry_slope'
  | 'site_exposure' | 'reliability_zones'
export type EnabledLayers = Record<LayerKey, boolean>

export const DEFAULT_LAYERS: EnabledLayers = {
  // Legacy HSI is off by default: HP salinity/temperature behind it are model-gridded
  // (CMEMS/GLORYS), not measured (RL-25), so it is not validated evidence.
  hsi_zones: false, context_buffer: true, station_network: true,
  flow_streamlines: false, wind_particles: false,
  rain: false, wave: false, sea_level: false, mixed_layer_depth: false, advisory_forecast: false,
  // GEBCO 2024 depth (with TID confidence) covers Cat Ba / Ha Long / Bai Tu Long; Copernicus SDB only the HP tidal flats.
  // ETOPO 2022 is kept as an optional comparison layer, off by default.
  // Default view = reliability zones + farming status (owner 2026-10-24); depth stays as thin isobaths only.
  reliability_zones: true,
  depth_isobands: false, depth_isobaths: true, depth_etopo: false, depth_slope: false,
  bathymetry_bands: false, bathymetry_contours: false, bathymetry_slope: false,
  // Theory-only wind/wave exposure per station (site-exposure run): an analysis aid, not a core monitoring
  // layer, so it starts off (owner decision 2026-10-24); labelled "lý thuyết" everywhere.
  site_exposure: false,
}
/** Scalar/vector environmental layers are mutually exclusive to keep the map legible. */
/** Colour-field layers: one at a time (Windy-style), so the map never stacks two colour scales. */
export const ENVIRONMENT_LAYERS = ['rain', 'wave', 'sea_level', 'mixed_layer_depth', 'advisory_forecast', 'wind_particles', 'flow_streamlines'] as const

const ONE_SHOT = { keepPreviousData: true, maxErrorRetries: 6, retryBaseMs: 5_000 } as const

/** Monitor-only feeds (the snapshot and sensor feeds live in LiveDataContext). */
export function useMonitorData({ enabled, lod, mode, scenario }: { enabled: EnabledLayers; lod: Lod; mode: DataMode; scenario: string }) {
  const stations = usePolling(getStations, ONE_SHOT)
  const domain = usePolling(getContextDomain, ONE_SHOT)
  const region = usePolling(getContextRegion, ONE_SHOT)
  const reliability = usePolling(getReliabilityVn, { ...ONE_SHOT, enabled: enabled.reliability_zones })
  const network = usePolling(getStationNetwork, { ...ONE_SHOT, isBuilding: value => value.network_status === 'building', buildingIntervalMs: 8_000, maxBuildingRetries: 60 })
  const zones = usePolling(getHsiZones, { ...ONE_SHOT, enabled: enabled.hsi_zones, isBuilding: value => value.status === 'building', buildingIntervalMs: 10_000, maxBuildingRetries: 30 })
  // Read-only research artifact (no Postgres); fetched once so the inspector can show it even when the layer is off.
  const exposure = usePolling(getSiteExposure, ONE_SHOT)
  const bathymetry = usePolling(getBathymetryManifest, { ...ONE_SHOT, isBuilding: value => value.status === 'building', buildingIntervalMs: 10_000, maxBuildingRetries: 60 })

  const bathymetryReady = bathymetry.data?.status === 'ready'
  const bathymetryOn = enabled.bathymetry_bands || enabled.bathymetry_contours
  const bands = usePolling(signal => getBathymetryDepthBands(lod, signal), { enabled: bathymetryOn && bathymetryReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })
  const contours = usePolling(signal => getBathymetryContours(lod, signal), { enabled: enabled.bathymetry_contours && bathymetryReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })

  // Default depth layer: GEBCO 2024 + TID confidence. (isobands/isobaths/depthFlags below are GEBCO.)
  const gebco = usePolling(getGebcoManifest, { ...ONE_SHOT, isBuilding: value => value.status === 'building', buildingIntervalMs: 15_000, maxBuildingRetries: 40 })
  const gebcoReady = gebco.data?.status === 'ready'
  const depthOn = enabled.depth_isobands || enabled.depth_isobaths
  const isobands = usePolling(signal => getGebcoLayer('isobands', lod, signal), { enabled: enabled.depth_isobands && gebcoReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })
  const isobaths = usePolling(signal => getGebcoLayer('isobaths', lod, signal), { enabled: enabled.depth_isobaths && gebcoReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })
  const depthFlags = usePolling(signal => getGebcoLayer('flags', lod, signal), { enabled: depthOn && gebcoReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })
  const seabedShade = usePolling(getSeabedShade, { ...ONE_SHOT, enabled: enabled.depth_slope && gebcoReady })

  // ETOPO 2022: optional comparison only; nothing is fetched until the toggle is on.
  const etopo = usePolling(getEtopoManifest, { ...ONE_SHOT, enabled: enabled.depth_etopo, isBuilding: value => value.status === 'building', buildingIntervalMs: 15_000, maxBuildingRetries: 40 })
  const etopoReady = etopo.data?.status === 'ready'
  const etopoBands = usePolling(signal => getEtopoLayer('isobands', lod, signal), { enabled: enabled.depth_etopo && etopoReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })
  const etopoFlags = usePolling(signal => getEtopoLayer('flags', lod, signal), { enabled: enabled.depth_etopo && etopoReady, deps: [lod], keepPreviousData: true, maxErrorRetries: 2 })

  // Mode/scenario changes reset the map so a live advisory is never shown under a mock label (or vice versa).
  const aquaculture = usePolling(signal => getAquacultureMap(mode, scenario, signal), {
    deps: [mode, scenario], intervalMs: mode === 'live' ? 60_000 : 300_000,
    isBuilding: value => value.status === 'building', buildingIntervalMs: 2_000, maxBuildingRetries: 30,
    clearOnError: true, retryBaseMs: 5_000,
  })

  const refreshAll = useCallback(() => {
    for (const feed of [stations, domain, network, zones, bathymetry, gebco, aquaculture, exposure]) feed.refresh()
  }, [stations, domain, network, zones, bathymetry, gebco, aquaculture, exposure])

  useEffect(() => {
    window.addEventListener(SYNC_EVENT, refreshAll)
    return () => window.removeEventListener(SYNC_EVENT, refreshAll)
  }, [refreshAll])

  return { stations, exposure, domain, region, reliability, network, zones, bathymetry, bands, contours, gebco, etopo, isobands, isobaths, depthFlags, seabedShade, etopoBands, etopoFlags, aquaculture, refreshAll }
}
