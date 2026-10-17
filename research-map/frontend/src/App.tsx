import { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer, GeoJSON } from 'react-leaflet'
import { getAquacultureMap, getBathymetryContours, getBathymetryDepthBands, getBathymetryManifest, getBathymetrySample, getContextDomain, getFlowArtifact, getHsiZones, getLatestContext, getSensorLatest, getStationNetwork, getStations } from './api'
import type { AquacultureMap, BathymetryManifest, BathymetrySample, BathymetryVectorLayer, ContextDomain, FlowArtifact, HsiZones, SensorLatest, Snapshot, StationNetwork, Stations } from './types'

import { Header } from './components/layout/Header'
import { SidebarLeft } from './components/layout/SidebarLeft'
import { SidebarRight } from './components/layout/SidebarRight'
import { ContextDomainOverlay, StationMarkers, BathymetryOverlay, ContextMarkers, ScalarGridOverlay, StationNetworkOverlay, FlowArtifactOverlay, EnvironmentalParticleOverlay, ZoomListener } from './components/map/MapOverlays'

// Start from the Hai Phong–Cat Ba regional view. Users can zoom into the
// sensor/cage area, but the initial map no longer crops the surrounding bay.
const MAP_CENTER: [number, number] = [20.78, 107.03]
const MAP_BOUNDS: [[number, number], [number, number]] = [[20.58, 106.78], [20.98, 107.28]]

export default function App() {
  const pilotStation = import.meta.env.VITE_SENSOR_STATION_SERIAL || '06M26042804'
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [sensorLatest, setSensorLatest] = useState<SensorLatest | null>(null)
  const [zones, setZones] = useState<HsiZones | null>(null)
  const [stations, setStations] = useState<Stations | null>(null)
  const [contextDomain, setContextDomain] = useState<ContextDomain | null>(null)
  const [stationNetwork, setStationNetwork] = useState<StationNetwork | null>(null)
  const [flowArtifact, setFlowArtifact] = useState<FlowArtifact | null>(null)
  const [bathymetry, setBathymetry] = useState<BathymetryManifest | null>(null)
  const [bathymetryBands, setBathymetryBands] = useState<BathymetryVectorLayer | null>(null)
  const [bathymetryContours, setBathymetryContours] = useState<BathymetryVectorLayer | null>(null)
  const [bathymetrySample, setBathymetrySample] = useState<BathymetrySample | null>(null)
  const [aquacultureMap, setAquacultureMap] = useState<AquacultureMap | null>(null)
  const [mapDataMode, setMapDataMode] = useState<'live' | 'mock'>('live')
  const [mockScenario, setMockScenario] = useState('normal')
  const [enabled, setEnabled] = useState<Record<string, boolean>>({ context_buffer: true, station_network: true, flow_streamlines: false, flow_particles: false, wind_particles: false, rain: false, wave: false, sea_level: false, mixed_layer_depth: false, bathymetry_bands: false, bathymetry_contours: false, bathymetry_slope: false })
  const [zoom, setZoom] = useState(11)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const loadContextAndFlow = async () => {
      try {
        const nextSnapshot = await getLatestContext()
        setSnapshot(nextSnapshot)
        try {
          const artifact = await getFlowArtifact(nextSnapshot.snapshot_id)
          if (artifact.snapshot_id === nextSnapshot.snapshot_id) setFlowArtifact(artifact)
        } catch {
          setFlowArtifact(null)
        }
        setError(null)
      } catch (err) {
        setError((err as Error).message)
      }
    }
    loadContextAndFlow()
    const contextTimer = window.setInterval(loadContextAndFlow, 20_000)
    getStations().then(setStations).catch(() => undefined)
    getContextDomain().then(setContextDomain).catch(() => undefined)
    
    let bathymetryTimer: number | undefined
    let bathymetryAttempts = 0
    const loadBathymetry = () => getBathymetryManifest().then(result => {
      setBathymetry(result)
      if (result.status === 'building' && bathymetryAttempts++ < 60) bathymetryTimer = window.setTimeout(loadBathymetry, 10_000)
    }).catch(() => {
      if (bathymetryAttempts++ < 60) bathymetryTimer = window.setTimeout(loadBathymetry, 5_000)
    })
    loadBathymetry()

    let networkTimer: number | undefined
    const loadNetwork = () => getStationNetwork().then(network => {
      setStationNetwork(network)
      if (network.network_status === 'building') networkTimer = window.setTimeout(loadNetwork, 8_000)
    }).catch(() => undefined)
    loadNetwork()

    let hsiTimer: number | undefined
    let hsiAttempts = 0
    const loadHsi = () => getHsiZones().then(result => {
      if (result.status === 'building' && hsiAttempts++ < 30) hsiTimer = window.setTimeout(loadHsi, 10_000)
      else setZones(result)
    }).catch(() => undefined)
    loadHsi()

    let sensorTimer: number | undefined
    const loadSensor = () => getSensorLatest(pilotStation).then(setSensorLatest).catch(() => undefined)
    loadSensor()
    sensorTimer = window.setInterval(loadSensor, 60_000)

    return () => { window.clearInterval(contextTimer); if (networkTimer !== undefined) window.clearTimeout(networkTimer); if (bathymetryTimer !== undefined) window.clearTimeout(bathymetryTimer); if (hsiTimer !== undefined) window.clearTimeout(hsiTimer); if (sensorTimer !== undefined) window.clearInterval(sensorTimer) }
  }, [pilotStation])

  useEffect(() => {
    let cancelled = false
    let attempts = 0
    const load = () => getAquacultureMap(mapDataMode, mockScenario).then(value => {
      if (cancelled) return
      setAquacultureMap(value)
      if (value.status === 'building' && attempts++ < 30) window.setTimeout(load, 2000)
    }).catch(() => { if (!cancelled) setAquacultureMap(null) })
    load()
    const timer = window.setInterval(load, mapDataMode === 'live' ? 60_000 : 300_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [mapDataMode, mockScenario])

  const allLayers = useMemo(() => snapshot?.layers ?? [], [snapshot])
  const available = useMemo(() => allLayers.filter(layer => layer.layer !== 'wind' && layer.layer !== 'current' && layer.layer !== 'bathymetry'), [allLayers])
  const currentLayer = allLayers.find(layer => layer.layer === 'current')
  const windLayer = allLayers.find(layer => layer.layer === 'wind')
  const bathymetryLod = zoom >= 13 ? 'high' : zoom >= 11 ? 'medium' : 'low'
  const bathymetryEnabled = enabled.bathymetry_bands || enabled.bathymetry_contours || enabled.bathymetry_slope

  useEffect(() => {
    if (!bathymetryEnabled || bathymetry?.status !== 'ready') return
    getBathymetryDepthBands(bathymetryLod).then(setBathymetryBands).catch(() => undefined)
    if (enabled.bathymetry_contours) getBathymetryContours(bathymetryLod).then(setBathymetryContours).catch(() => undefined)
    else setBathymetryContours(null)
  }, [bathymetry?.status, bathymetryEnabled, bathymetryLod, enabled.bathymetry_contours])

  const selectBathymetrySample = (latitude: number, longitude: number) => getBathymetrySample(longitude, latitude).then(setBathymetrySample).catch(() => setBathymetrySample({ status: 'unavailable', reason_code: 'sample_request_failed' }))

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-slate-100 font-sans">
      <Header snapshot={snapshot} mapDataMode={mapDataMode} />
      
      {error && <div className="absolute top-20 left-1/2 -translate-x-1/2 bg-red-100 text-red-800 px-4 py-2 rounded-lg shadow-lg z-50 font-medium">Không tải được API context: {error}</div>}
      
      <main className="flex-1 relative flex">
        <SidebarLeft 
          mapDataMode={mapDataMode} setMapDataMode={setMapDataMode}
          mockScenario={mockScenario} setMockScenario={setMockScenario}
          enabled={enabled} setEnabled={setEnabled}
          stationNetwork={stationNetwork} flowArtifact={flowArtifact}
          available={available} bathymetry={bathymetry} bathymetryLod={bathymetryLod}
        />

        <div className="map-shell flex-1 relative">
          <div className="map-scope-chip absolute top-4 left-4 z-[500] pointer-events-none">
            <span className="map-scope-kicker">KHU VỰC GIÁM SÁT</span>
            <strong>Hải Phòng · Cát Bà · Lạch Huyện</strong>
            <span>Nền bản đồ khu vực · context dữ liệu 5 km</span>
          </div>
          <MapContainer preferCanvas center={MAP_CENTER} zoom={11} minZoom={10} maxZoom={17} maxBounds={MAP_BOUNDS} maxBoundsViscosity={0.22} scrollWheelZoom worldCopyJump className="absolute inset-0 z-0 outline-none">
            <ZoomListener onZoom={setZoom} />
            <TileLayer attribution="Tiles © Esri · Map data © OpenStreetMap contributors" url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}" />
            
            {enabled.context_buffer && contextDomain && <ContextDomainOverlay domain={contextDomain} />}
            {stations && <StationMarkers stations={stations} aquacultureMap={aquacultureMap} />}
            <BathymetryOverlay bands={bathymetryBands} contours={bathymetryContours} showBands={enabled.bathymetry_bands || enabled.bathymetry_slope} showContours={enabled.bathymetry_contours} showSlope={enabled.bathymetry_slope} onSample={selectBathymetrySample} />
            
            {zones && <GeoJSON key={zones.observed_at || 'zones'} data={{ type: 'FeatureCollection', features: zones.features } as GeoJSON.FeatureCollection} style={(feature: any) => {
              const label = feature?.properties?.hsi_label
              if (label === 'very_suitable') return { color: '#16a34a', weight: 1.5, fillColor: '#22c55e', fillOpacity: 0.3 }
              if (label === 'suitable') return { color: '#ca8a04', weight: 1.5, fillColor: '#eab308', fillOpacity: 0.3 }
              if (label === 'less_suitable' || label === 'not_suitable') return { color: '#dc2626', weight: 1.5, fillColor: '#ef4444', fillOpacity: 0.3 }
              return { color: '#0f766e', weight: 1.5, fillColor: '#2dd4bf', fillOpacity: 0.18 }
            }} onEachFeature={(feature, layer) => {
              const lbl = feature.properties?.hsi_label
              const displayLabel = lbl === 'very_suitable' ? 'Rất phù hợp' : lbl === 'suitable' ? 'Phù hợp' : lbl === 'less_suitable' ? 'Kém phù hợp' : lbl === 'not_suitable' ? 'Không phù hợp' : 'Không xác định'
              layer.bindTooltip(`<b>Phân loại: ${displayLabel}</b><br/>Điểm HSI: ${feature.properties?.hsi ?? '-'}<br/>Trạm gốc: ${feature.properties?.anchor_station ?? ''}`)
            }} />}
            
            {available.filter(layer => enabled[layer.layer] && layer.status !== 'unavailable' && layer.layer !== 'current' && layer.layer !== 'wind').map(layer => layer.kind === 'scalar_grid' ? <ScalarGridOverlay key={layer.layer} layer={layer} /> : <ContextMarkers key={layer.layer} layer={layer} />)}
            
            {enabled.station_network && stationNetwork && <StationNetworkOverlay network={stationNetwork} />}
            {enabled.flow_streamlines && flowArtifact && <FlowArtifactOverlay artifact={flowArtifact} zoom={zoom} />}
            
            <EnvironmentalParticleOverlay type="flow" layer={currentLayer} enabled={enabled.flow_streamlines} waterGeometry={contextDomain?.features.find(feature => feature.properties?.kind === 'context_domain_water')?.geometry} />
            <EnvironmentalParticleOverlay type="wind" layer={windLayer} enabled={enabled.wind_particles} waterGeometry={undefined} />
          </MapContainer>
          
          <div className="absolute inset-y-0 right-0 z-10 flex pointer-events-none">
            <SidebarRight 
              snapshot={snapshot} sensorLatest={sensorLatest} pilotStation={pilotStation} stations={stations}
              aquacultureMap={aquacultureMap} bathymetrySample={bathymetrySample}
              enabled={enabled} available={available} mapDataMode={mapDataMode}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
