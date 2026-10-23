import 'leaflet/dist/leaflet.css'
import { memo } from 'react'
import { MapContainer, TileLayer, ZoomControl } from 'react-leaflet'
import type { AquacultureMap, BathymetryVectorLayer, ContextDomain, ContextRegion, FlowArtifact, HsiZones, Layer, StationNetwork, Stations } from '../../types/monitor'
import { basemapTiles, ESRI_ATTRIBUTION, MAP_BOUNDS, MAP_CENTER, MAP_ZOOM, type BasemapId, type Lod } from '../../components/map/mapConfig'
import { BathymetryOverlay } from '../../components/map/overlays/BathymetryOverlay'
import { EtopoDepthOverlay } from '../../components/map/overlays/EtopoDepthOverlay'
import { GebcoSlopeOverlay } from '../../components/map/overlays/GebcoSlopeOverlay'
import { ContextDomainOverlay } from '../../components/map/overlays/ContextDomainOverlay'
import { FlowArtifactOverlay } from '../../components/map/overlays/FlowArtifactOverlay'
import { HsiZonesOverlay } from '../../components/map/overlays/HsiZonesOverlay'
import { LodListener } from '../../components/map/overlays/LodListener'
import { StationMarkers } from '../../components/map/overlays/StationMarkers'
import { SiteExposureOverlay } from '../../components/map/overlays/SiteExposureOverlay'
import type { SiteExposure } from '../../components/map/siteExposure'
import { StationNetworkOverlay } from '../../components/map/overlays/StationNetworkOverlay'
import type { Theme } from '../../hooks/useTheme'
import type { EnabledLayers } from './useMonitorData'
import { RegionalFields, activeField } from './RegionalFields'

type Props = {
  theme: Theme
  basemap: BasemapId
  enabled: EnabledLayers
  snapshotId: string | null
  /** Every layer of the latest context snapshot (regional fields pick theirs by name). */
  allLayers: Layer[]
  flow: FlowArtifact | null
  stations: Stations | null
  aquacultureMap: AquacultureMap | null
  /** Live advisory older than 90 min → neutral hatched markers. */
  advisoryStale: boolean
  advisoryAgeSeconds: number | null
  exposure: SiteExposure | null
  domain: ContextDomain | null
  /** Regional environment grid extent + water polygon. */
  region: ContextRegion | null
  network: StationNetwork | null
  zones: HsiZones | null
  bands: BathymetryVectorLayer | null
  contours: BathymetryVectorLayer | null
  isobands: BathymetryVectorLayer | null
  isobaths: BathymetryVectorLayer | null
  depthFlags: BathymetryVectorLayer | null
  /** GEBCO-derived bottom-slope classes (whole region). */
  depthSlope: BathymetryVectorLayer | null
  /** ETOPO 2022 comparison bands + flags (optional). */
  etopoBands: BathymetryVectorLayer | null
  etopoFlags: BathymetryVectorLayer | null
  lod: Lod
  onLod: (lod: Lod) => void
  onSample: (latitude: number, longitude: number) => void
}

/**
 * The Leaflet map and every overlay. Memoized: inspector/legend/panel state in
 * the parent never re-renders this subtree unless map inputs change.
 */
export const MonitorMap = memo(function MonitorMap(props: Props) {
  const { theme, basemap, enabled, snapshotId, allLayers, flow, stations, aquacultureMap, advisoryStale, advisoryAgeSeconds, exposure, domain, region, network, zones, bands, contours, isobands, isobaths, depthFlags, depthSlope, etopoBands, etopoFlags, lod, onLod, onSample } = props
  const tiles = basemapTiles(basemap, theme)

  return (
    <MapContainer preferCanvas center={MAP_CENTER} zoom={MAP_ZOOM} minZoom={10} maxZoom={17} maxBounds={MAP_BOUNDS} maxBoundsViscosity={0.22}
      scrollWheelZoom zoomControl={false} worldCopyJump className="absolute inset-0 z-0">
      <ZoomControl position="bottomright" zoomInTitle="Phóng to" zoomOutTitle="Thu nhỏ" />
      <LodListener onLod={onLod} />
      <TileLayer key={tiles.base} attribution={ESRI_ATTRIBUTION} url={tiles.base} />
      {tiles.labels && <TileLayer key={tiles.labels} url={tiles.labels} className="basemap-labels" zIndex={2} />}

      {enabled.depth_etopo && <EtopoDepthOverlay source="etopo" underlay theme={theme} lod={lod} isobands={etopoBands} isobaths={null} flags={etopoFlags} showBands showIsobaths={false} onSample={onSample} />}
      <EtopoDepthOverlay source="gebco" theme={theme} lod={lod} isobands={isobands} isobaths={isobaths} flags={depthFlags} showBands={enabled.depth_isobands} showIsobaths={enabled.depth_isobaths} onSample={onSample} />
      {enabled.context_buffer && domain && <ContextDomainOverlay domain={domain} dataKey={`domain-${domain.features.length}`} outlineOnly={enabled.depth_isobands || activeField(enabled) !== null} />}
      {enabled.hsi_zones && zones && zones.status !== 'building' && <HsiZonesOverlay zones={zones} />}
      {enabled.depth_slope && <GebcoSlopeOverlay slope={depthSlope} />}
      <BathymetryOverlay bands={bands} contours={contours} showBands={enabled.bathymetry_bands} showContours={enabled.bathymetry_bands && enabled.bathymetry_contours} showSlope={false} onSample={onSample} />

      <RegionalFields enabled={enabled} layers={allLayers} region={region} dataKey={snapshotId ?? 'none'} />

      {enabled.station_network && network && <StationNetworkOverlay network={network} dataKey={`${network.network_status}-${network.edge_count}-${network.features.length}`} />}
      {enabled.flow_streamlines && flow && <FlowArtifactOverlay artifact={flow} lod={lod} />}
      {/* The street basemap is always light, so the rose ink follows the basemap, not the UI theme. */}
      {enabled.site_exposure && <SiteExposureOverlay exposure={exposure} stations={stations} theme={basemap === 'street' ? 'light' : theme} />}
      {stations && <StationMarkers stations={stations} aquacultureMap={aquacultureMap} stale={advisoryStale} staleAgeSeconds={advisoryAgeSeconds} exposure={exposure} theme={theme} />}

    </MapContainer>
  )
})
