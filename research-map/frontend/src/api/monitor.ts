/// <reference types="vite/client" />
import type { AquacultureMap, BathymetryManifest, BathymetrySample, BathymetryVectorLayer, ContextDomain, FlowArtifact, FlowLatest, FlowScenarios, HsiZones, SensorLatest, Snapshot, StationNetwork, Stations } from './types'

const API = import.meta.env.VITE_CONTEXT_API_URL || 'http://localhost:8010/api/v1'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`)
  if (!response.ok) throw new Error(`api_${response.status}`)
  return response.json() as Promise<T>
}

export const getLatestContext = () => get<Snapshot>('/context/latest')
export const getHsiZones = () => get<HsiZones>('/hsi-zones')
export const getStations = () => get<Stations>('/stations')
export const getContextDomain = () => get<ContextDomain>('/context-domain')
export const getStationNetwork = () => get<StationNetwork>('/station-network')
export const getFlowArtifact = (snapshotId: string) => get<FlowArtifact>(`/flow/${encodeURIComponent(snapshotId)}/artifact`)
export const getFlowLatest = () => get<FlowLatest>('/flow/latest')
export const getFlowScenarios = () => get<FlowScenarios>('/flow/scenarios')
export const getSensorLatest = (station: string) => get<SensorLatest>(`/stations/${encodeURIComponent(station)}/latest`)
export const getBathymetryManifest = () => get<BathymetryManifest>('/bathymetry/manifest')
export const getBathymetryDepthBands = (lod: string) => get<BathymetryVectorLayer>(`/bathymetry/depth-bands?lod=${encodeURIComponent(lod)}`)
export const getBathymetryContours = (lod: string) => get<BathymetryVectorLayer>(`/bathymetry/contours?lod=${encodeURIComponent(lod)}`)
export const getBathymetrySample = (longitude: number, latitude: number) => get<BathymetrySample>(`/bathymetry/sample?lon=${encodeURIComponent(longitude)}&lat=${encodeURIComponent(latitude)}`)
export const getAquacultureMap = (mode: 'live' | 'mock', scenario: string) => get<AquacultureMap>(`/aquaculture-map?mode=${mode}&scenario=${encodeURIComponent(scenario)}`)
