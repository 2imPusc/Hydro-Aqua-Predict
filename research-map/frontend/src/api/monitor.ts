import { getJson } from './client'
import type { SeabedShade } from '../components/map/overlays/SeabedShadeOverlay'
import type { AquacultureMap, BathymetryManifest, BathymetrySample, BathymetryVectorLayer, ContextDomain, ContextRegion, EtopoManifest, GebcoManifest, DataMode, FlowArtifact, FlowLatest, FlowScenarios, HsiZones, SensorLatest, Snapshot, StationNetwork, Stations } from '../types/monitor'

type Signal = AbortSignal | undefined
const q = encodeURIComponent

export const getLatestContext = (signal?: Signal) => getJson<Snapshot>('/context/latest', signal)
export const getHsiZones = (signal?: Signal) => getJson<HsiZones>('/hsi-zones', signal)
export const getStations = (signal?: Signal) => getJson<Stations>('/stations', signal)
export const getContextDomain = (signal?: Signal) => getJson<ContextDomain>('/context-domain', signal)
/** Regional environment grid extent + simplified water polygon (clips the marine fields). */
export const getContextRegion = (signal?: Signal) => getJson<ContextRegion>('/context-region', signal)
export const getStationNetwork = (signal?: Signal) => getJson<StationNetwork>('/station-network', signal)
export const getFlowArtifact = (snapshotId: string, signal?: Signal) => getJson<FlowArtifact>(`/flow/${q(snapshotId)}/artifact`, signal)
export const getFlowLatest = (signal?: Signal) => getJson<FlowLatest>('/flow/latest', signal)
export const getFlowScenarios = (signal?: Signal) => getJson<FlowScenarios>('/flow/scenarios', signal)
export const getSensorLatest = (station: string, signal?: Signal) => getJson<SensorLatest>(`/stations/${q(station)}/latest`, signal)
export const getBathymetryManifest = (signal?: Signal) => getJson<BathymetryManifest>('/bathymetry/manifest', signal)
export const getBathymetryDepthBands = (lod: string, signal?: Signal) => getJson<BathymetryVectorLayer>(`/bathymetry/depth-bands?lod=${q(lod)}`, signal)
export const getBathymetryContours = (lod: string, signal?: Signal) => getJson<BathymetryVectorLayer>(`/bathymetry/contours?lod=${q(lod)}`, signal)
export const getGebcoManifest = (signal?: Signal) => getJson<GebcoManifest>('/bathymetry/gebco/manifest', signal)
export const getSeabedShade = (signal?: Signal) => getJson<SeabedShade>('/bathymetry/gebco/hillshade', signal)
export const getGebcoLayer = (kind: 'isobands' | 'isobaths' | 'flags' | 'slope', lod: string, signal?: Signal) => getJson<BathymetryVectorLayer>(`/bathymetry/gebco/${kind}?lod=${q(lod)}`, signal)
export const getEtopoManifest = (signal?: Signal) => getJson<EtopoManifest>('/bathymetry/etopo/manifest', signal)
export const getEtopoLayer = (kind: 'isobands' | 'isobaths' | 'flags', lod: string, signal?: Signal) => getJson<BathymetryVectorLayer>(`/bathymetry/etopo/${kind}?lod=${q(lod)}`, signal)
export const getBathymetrySample = (longitude: number, latitude: number, signal?: Signal) => getJson<BathymetrySample>(`/bathymetry/sample?lon=${q(longitude)}&lat=${q(latitude)}`, signal)
export const getAquacultureMap = (mode: DataMode, scenario: string, signal?: Signal) => getJson<AquacultureMap>(`/aquaculture-map?mode=${mode}&scenario=${q(scenario)}`, signal)
