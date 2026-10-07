import 'leaflet/dist/leaflet.css'
import L from 'leaflet'
import { useEffect, useRef } from 'react'
import { CircleMarker, GeoJSON, Marker, Popup, useMap, useMapEvents } from 'react-leaflet'
import type { AquacultureMap, BathymetrySample, BathymetryVectorLayer, ContextDomain, FlowArtifact, Layer, LayerName, StationNetwork, Stations } from '../../types'

const MAP_CENTER: [number, number] = [20.77, 107.03]
export const LABEL: Record<LayerName, string> = {
  wind: 'Gió', rain: 'Mưa', wave: 'Sóng', current: 'Dòng chảy',
  sea_level: 'Mực nước / SSH', mixed_layer_depth: 'Mixed-layer depth', bathymetry: 'Bathymetry & slope',
  advisory_forecast: 'Dự báo khuyến nghị',
}

export function arrowIcon(bearing: number, color: string, speed = 0, animated = false) {
  const size = Math.max(17, Math.min(28, 17 + speed * 5))
  // The arrow glyph points east at 0 CSS degrees; provider bearings are from
  // north, so rotate by bearing - 90 to preserve the published convention.
  return L.divIcon({ className: `context-arrow${animated ? ' wind-arrow' : ''}`, html: `<span style="display:block;color:${color};font-size:${size}px;transform:rotate(${bearing - 90}deg)">➜</span>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2] })
}

export function ContextMarkers({ layer }: { layer: Layer }) {
  const color = layer.layer === 'wind' ? '#0ea5e9' : layer.layer === 'rain' ? '#3b82f6' : layer.layer === 'wave' ? '#7c3aed' : '#f97316'
  return <>{layer.geojson?.features.map((feature, index) => {
    if (feature.geometry.type !== 'Point') return null
    const [longitude, latitude] = feature.geometry.coordinates as [number, number]
    const props = (feature.properties ?? {}) as Record<string, string | number | null>
    const isCalm = layer.layer === 'current' && Number(props.speed_m_s ?? 0) < .35
    const hasDirection = !isCalm && props.display_bearing_degrees !== undefined && props.display_bearing_degrees !== null
    const bearing = Number(props.display_bearing_degrees ?? 0)
    const speed = Number(props.speed_m_s ?? props.height_m ?? 0)
    if (!hasDirection) return <CircleMarker key={`${layer.layer}-${index}`} center={[latitude, longitude]} radius={isCalm ? 4 : 6} pathOptions={{ color, fillColor: color, fillOpacity: isCalm ? .25 : .55 }}><Popup><b>{LABEL[layer.layer]}</b>{isCalm && <div>Dòng yếu / hướng không ổn định</div>}{Object.entries(props).map(([key, value]) => <div key={key}>{key}: {String(value)}</div>)}<hr />{layer.provenance?.source}<br />valid: {layer.provenance?.valid_at}</Popup></CircleMarker>
    return <Marker key={`${layer.layer}-${index}`} position={[latitude, longitude]} icon={arrowIcon(bearing, color, speed, layer.layer === 'wind')}>
      <Popup><b>{LABEL[layer.layer]}</b>{Object.entries(props).map(([key, value]) => <div key={key}>{key}: {String(value)}</div>)}<hr />{layer.provenance?.source}<br />valid: {layer.provenance?.valid_at}</Popup>
    </Marker>
  })}</>
}

export function ScalarGridOverlay({ layer }: { layer: Layer }) {
  const values = layer.geojson?.features.map(feature => Number(feature.properties?.value)).filter(Number.isFinite) ?? []
  const minimum = values.length ? Math.min(...values) : 0
  const maximum = values.length ? Math.max(...values) : 1
  return <>{layer.geojson?.features.map((feature, index) => {
    if (feature.geometry.type !== 'Point' && feature.geometry.type !== 'Polygon') return null
    const coordinates = feature.geometry.type === 'Point'
      ? [feature.geometry.coordinates as [number, number]]
      : (feature.geometry.coordinates as number[][][])[0].map(([longitude, latitude]) => [longitude, latitude] as [number, number])
    const value = Number(feature.properties?.value)
    const ratio = maximum > minimum ? (value - minimum) / (maximum - minimum) : .5
    // Blue/cyan scale avoids the previous dominant green fill for rain.
    const color = `hsl(${215 - ratio * 35} 78% 52%)`
    const popup = <Popup><b>{LABEL[layer.layer]}</b><br />{String(feature.properties?.variable)}: {value.toFixed(3)} {String(feature.properties?.unit ?? '')}<hr />{layer.provenance?.source}<br />valid: {layer.provenance?.valid_at}</Popup>
    if (feature.geometry.type === 'Point') {
      const [longitude, latitude] = coordinates[0]
      return <CircleMarker key={`${layer.layer}-scalar-${index}`} center={[latitude, longitude]} radius={6} pathOptions={{ color, fillColor: color, fillOpacity: .3, weight: 1 }}>{popup}</CircleMarker>
    }
    return <GeoJSON key={`${layer.layer}-cell-${index}`} data={feature as GeoJSON.Feature<GeoJSON.Polygon>} style={{ color, fillColor: color, fillOpacity: .3, weight: .4 }}>{popup}</GeoJSON>
  })}</>
}

export function RainLegend({ layer }: { layer: Layer }) {
  const values = layer.geojson?.features.map(feature => Number(feature.properties?.value)).filter(Number.isFinite) ?? []
  if (!values.length) return null
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  return <div className="rain-legend"><b>Thang mưa</b><div className="rain-gradient" /><div className="rain-legend-labels"><span>{minimum.toFixed(1)} mm</span><span>{maximum.toFixed(1)} mm</span></div></div>
}

export function FlowLegend() {
  return <div className="rain-legend flow-legend"><b>Vận tốc dòng chảy</b><div className="rain-gradient" style={{ background: 'linear-gradient(to right, hsla(190, 90%, 55%, 0.95), hsla(102.5, 90%, 55%, 0.95), hsla(15, 90%, 55%, 0.95))' }} /><div className="rain-legend-labels"><span>0.05 m/s</span><span>0.35 m/s</span><span>0.6+ m/s</span></div><div style={{ fontSize: '10px', color: '#64748b', marginTop: '4px' }}>Vận tốc chuẩn hóa (m/s)</div></div>
}

export function WindLegend() {
  return <div className="rain-legend flow-legend"><b>Tốc độ gió</b><div className="rain-gradient" style={{ background: 'linear-gradient(to right, hsla(280, 90%, 80%, 0.95), hsla(240, 90%, 70%, 0.95), hsla(200, 90%, 60%, 0.95))' }} /><div className="rain-legend-labels"><span>0-2</span><span>2-5</span><span>5-10</span><span>10+ m/s</span></div><div style={{ fontSize: '10px', color: '#64748b', marginTop: '4px' }}>Tại độ cao 10m</div></div>
}

export function StationMarkers({ stations, aquacultureMap }: { stations: Stations; aquacultureMap?: AquacultureMap | null }) {
  const advisories = aquacultureMap?.features ?? []
  return <>{stations.features.map((feature, index) => {
    if (feature.geometry?.type !== 'Point') return null
    const [longitude, latitude] = feature.geometry.coordinates as [number, number]
    const properties = feature.properties ?? {}
    // The pilot has one physical sensor. Its advisory is the regional status;
    // mock mode may still provide per-point variants for demonstrations.
    const advisory = advisories.find(item => String(item.properties?.station_serial ?? '') === String(properties.station ?? ''))
      ?? (aquacultureMap?.mode === 'mock' ? advisories[index % Math.max(1, advisories.length)] : advisories[0])
    const severity = String(advisory?.properties?.severity ?? 'UNKNOWN').toUpperCase()
    const status = severity === 'WARNING' ? { color: '#dc2626', label: 'Cảnh báo' }
      : severity === 'WATCH' ? { color: '#f59e0b', label: 'Cần theo dõi' }
      : severity === 'UNKNOWN' ? { color: '#94a3b8', label: 'Không rõ' }
        : { color: '#16a34a', label: 'Bình thường' }
    const icon = L.divIcon({
      className: 'station-marker',
      html: `<span style="display:flex;width:14px;height:14px;border-radius:999px;background:${status.color};border:2px solid #fff;box-shadow:0 1px 5px rgba(15,23,42,.45)"></span>`,
      iconSize: [14, 14], iconAnchor: [7, 7],
    })
    return <Marker key={`station-${index}`} position={[latitude, longitude]} icon={icon}>
      <Popup><b>{String(properties.station ?? 'Trạm')}</b><br />{String(properties.name ?? '')}<br /><b style={{ color: status.color }}>{status.label}</b>{advisory?.properties?.drivers?.length ? <><hr />Yếu tố: {advisory.properties.drivers.map((item: any) => `${item.metric}=${item.value} ${item.unit}`).join(', ')}</> : null}</Popup>
    </Marker>
  })}</>
}

export function AquacultureAdvisoryOverlay({ artifact }: { artifact: AquacultureMap | null }) {
  if (!artifact || artifact.status !== 'ready') return null
  return <>{artifact.features.map((feature, index) => {
    if (feature.geometry?.type !== 'Point') return null
    const [longitude, latitude] = feature.geometry.coordinates as [number, number]
    const props = feature.properties as Record<string, any>
    const watch = props.severity === 'WATCH'
    const warning = props.severity === 'WARNING'
    const color = warning ? '#dc2626' : (watch ? '#ea580c' : '#0f766e')
    const metrics = props.metrics ?? {}
    const weather = props.weather ?? {}
    const drivers = props.drivers ?? []
    return <CircleMarker key={`aquaculture-${index}`} center={[latitude, longitude]} radius={warning ? 22 : (watch ? 18 : 14)} pathOptions={{ color, weight: 3, fillColor: color, fillOpacity: warning ? .5 : .28 }}>
      <Popup><b>{artifact.mode === 'mock' ? `MOCK | ${props.scenario}` : 'LIVE | sensor advisory'}</b><br />
        Mức: {props.severity}<br />NH4: {metrics.NH4 ?? '—'} · NH3 quy đổi: {props.nh3_derived_mg_l ?? '—'} mg/L<br />
        Nhiệt độ: {metrics.Temperature ?? '—'} °C · pH: {metrics.pH ?? '—'}<br />
        Mưa 6h: {weather.rain_6h_mm ?? '—'} mm · Gió 6h: {weather.wind_6h_kmh ?? '—'} km/h<br />
        {drivers.length ? <><hr />Yếu tố: {drivers.map((item: any) => `${item.metric}=${item.value} ${item.unit}`).join(', ')}</> : <><hr />Chưa có yếu tố cần theo dõi.</>}
        <hr /><small>Advisory theo điểm sensor; không thay đổi phân loại nuôi trồng.</small>
      </Popup>
    </CircleMarker>
  })}</>
}

export function ContextDomainOverlay({ domain }: { domain: ContextDomain }) {
  const visibleFeatures = domain.features.filter(feature => feature.properties?.kind !== 'station_network_hull')
  return <GeoJSON data={{ ...domain, features: visibleFeatures } as GeoJSON.FeatureCollection} style={(feature) => feature?.properties?.kind === 'context_domain_boundary'
      ? { color: '#2563eb', weight: 1, dashArray: '3 4', fillOpacity: 0 }
      : { color: '#0284c7', weight: 1, fillColor: '#38bdf8', fillOpacity: .13 }}
    onEachFeature={(feature, layer) => layer.bindTooltip(feature.properties?.kind === 'station_network_hull'
      ? `Network hull · ${feature.properties?.station_count} trạm`
      : `Phạm vi context ${feature.properties?.water_clipped ? 'trên mặt nước' : ''} · buffer ${feature.properties?.buffer_m / 1000} km`)}/>
}

export function StationNetworkOverlay({ network }: { network: StationNetwork }) {
  // Station routes are static water connectivity only: never draw a current
  // direction arrow here.  Dynamic flow is rendered from FlowArtifactOverlay.
  return <GeoJSON data={network} style={() => ({ color: '#64748b', weight: 1.35, opacity: .68, dashArray: '3 4' })} onEachFeature={(feature, layer) => layer.bindTooltip(`Static water connectivity: ${feature.properties?.station_a} <-> ${feature.properties?.station_b} · ${feature.properties?.water_distance_km} km`)}/>
  /* Legacy request-time streamline and route-arrow renderer intentionally
     removed. It stays commented only to make the visual responsibility split
     explicit while this experimental map evolves.
  const streamlineFeatures = network.features.filter(feature => feature.properties?.kind === 'flow_streamline')
  const streamlineStride = zoom < 12 ? 5 : zoom < 14 ? 2 : 1
  const visibleStreamlines = showStreamlines ? streamlineFeatures.filter((_feature, index) => index % streamlineStride === 0) : []
  const visibleFeatures = network.features.filter(feature => feature.properties?.kind !== 'flow_streamline').concat(visibleStreamlines)
  const stationEdges = network.features.filter(feature => feature.properties?.kind === 'water_path_station_edge')
  const arrowMarkers = stationEdges.map((feature, index) => {
    const coordinates = feature.geometry.type === 'LineString' ? feature.geometry.coordinates as [number, number][] : []
    if (coordinates.length < 2) return null
    const reverse = Number(feature.properties?.forward_alignment) < 0
    const [from, to] = reverse
      ? [coordinates[1], coordinates[0]]
      : [coordinates[coordinates.length - 2], coordinates[coordinates.length - 1]]
    const bearing = (Math.atan2(to[0] - from[0], to[1] - from[1]) * 180 / Math.PI + 360) % 360
    const color = feature.properties?.forward_alignment != null ? '#ea580c' : '#475569'
    return <Marker key={`station-flow-arrow-${index}`} position={[to[1], to[0]]} icon={arrowIcon(bearing, color, 0)} />
  })
  
  const streamlineArrows = visibleStreamlines.map((feature, index) => {
    const coordinates = feature.geometry.type === 'LineString' ? feature.geometry.coordinates as [number, number][] : []
    if (coordinates.length < 4) return null
    const midIndex = Math.floor(coordinates.length / 2)
    const [from, to] = [coordinates[midIndex - 1], coordinates[midIndex]]
    const bearing = (Math.atan2(to[0] - from[0], to[1] - from[1]) * 180 / Math.PI + 360) % 360
    return <Marker key={`streamline-arrow-${index}`} position={[to[1], to[0]]} icon={arrowIcon(bearing, '#e11d48', 0)} />
  })
  return <><GeoJSON data={{ ...network, features: visibleFeatures } as GeoJSON.FeatureCollection} style={(feature) => feature?.properties?.kind === 'flow_streamline'
    ? { color: '#e11d48', weight: 2.4, opacity: .88 }
    : { color: feature?.properties?.influence_status === 'exploratory' ? '#ea580c' : '#475569', weight: feature?.properties?.influence_status === 'exploratory' ? 3 : 1.5, opacity: .8 }} onEachFeature={(feature, layer) => layer.bindTooltip(
      feature.properties?.kind === 'flow_streamline'
        ? `Streamline dòng chảy · ${feature.properties?.source ?? 'vector grid'}`
        : `${feature.properties?.station_a} → ${feature.properties?.station_b} · ${feature.properties?.water_distance_km} km${feature.properties?.forward_alignment != null ? ` · alignment ${feature.properties.forward_alignment} · ${feature.properties?.route_type ?? 'flow diagnostic'}` : ''}`,
    )}/>{arrowMarkers}{streamlineArrows}</> */
}

export function FlowArtifactOverlay({ artifact, zoom }: { artifact: FlowArtifact; zoom: number }) {
  const rays = artifact.features.filter(feature => feature.properties?.kind === 'flow_ray')
  const visible = artifact.features.filter(feature => feature.properties?.kind === 'current_supported_station_edge').concat(rays)
  const arrows = visible.map((feature, index) => {
    if (feature.properties?.kind === 'flow_ray') return null
    if (feature.geometry.type !== 'LineString') return null
    const coordinates = feature.geometry.coordinates as [number, number][]
    if (coordinates.length < 3) return null
    const middle = Math.floor(coordinates.length / 2)
    const [from, to] = [coordinates[middle - 1], coordinates[middle]]
    const bearing = (Math.atan2(to[0] - from[0], to[1] - from[1]) * 180 / Math.PI + 360) % 360
    const color = feature.properties?.kind === 'flow_streamline' ? '#005fcc' : '#ea580c'
    return <Marker key={`precomputed-flow-arrow-${index}`} position={[to[1], to[0]]} icon={arrowIcon(bearing, color, 0)} />
  })
  return <><GeoJSON data={{ ...artifact, features: visible } as GeoJSON.FeatureCollection} style={(feature) => feature?.properties?.kind === 'flow_ray'
    ? { color: '#0b5fc1', weight: zoom >= 13 ? 1.5 : 1.25, opacity: .82 }
    : { color: '#ea580c', weight: 2.8, opacity: .95 }} onEachFeature={(feature, layer) => layer.bindTooltip(
      feature.properties?.kind === 'flow_ray'
        ? `Tia dòng chảy nội suy theo nước · snapshot ${artifact.snapshot_id.slice(0, 8)}`
        : `Current compatibility (research only) · ${feature.properties?.station_a} -> ${feature.properties?.station_b}`,
    )}/>{arrows}</>
}

export function PrecomputedFlowParticleOverlay({ artifact, enabled }: { artifact: FlowArtifact; enabled: boolean }) {
  const map = useMap()
  const frameRef = useRef<number | null>(null)

  useEffect(() => {
    if (!enabled) return undefined
    const container = map.getContainer()
    const canvas = document.createElement('canvas')
    canvas.className = 'flow-particle-canvas'
    container.appendChild(canvas)
    const context = canvas.getContext('2d')
    if (!context) return undefined
    type ScreenPoint = { x: number; y: number }
    type Particle = { path: ScreenPoint[]; progress: number; speed: number }
    let particles: Particle[] = []

    const rebuild = () => {
      const ratio = Math.min(2, window.devicePixelRatio || 1)
      canvas.width = Math.max(1, Math.floor(container.clientWidth * ratio))
      canvas.height = Math.max(1, Math.floor(container.clientHeight * ratio))
      canvas.style.width = `${container.clientWidth}px`
      canvas.style.height = `${container.clientHeight}px`
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      const paths = artifact.features.flatMap(feature => {
        if (feature.properties?.kind !== 'flow_ray' || feature.geometry.type !== 'LineString') return []
        return [(feature.geometry as GeoJSON.LineString).coordinates.map(([longitude, latitude]) => map.latLngToContainerPoint([latitude, longitude]))]
      }).filter(path => path.length >= 2)
      // Fixed, bounded count: no raw-grid lookup, geometry operation, or DOM
      // marker work occurs during animation frames.
      particles = Array.from({ length: Math.min(900, paths.length) }, (_item, index) => ({
        // Slow visual playback: direction comes from the snapshot field, but
        // this is not a literal real-time ocean-speed simulation.
        path: paths[index], progress: Math.random(), speed: .00008 + Math.random() * .00016,
      }))
    }
    const pointAt = (path: ScreenPoint[], progress: number) => {
      const scaled = progress * (path.length - 1)
      const index = Math.min(path.length - 2, Math.floor(scaled))
      const fraction = scaled - index
      const start = path[index], end = path[index + 1]
      return { x: start.x + (end.x - start.x) * fraction, y: start.y + (end.y - start.y) * fraction }
    }
    rebuild()
    map.on('zoomend moveend resize', rebuild)
    let lastTime = performance.now()
    const animate = (time: number) => {
      const dt = time - lastTime
      lastTime = time
      const delta = Math.min(dt, 50) / 16.66
      
      context.clearRect(0, 0, container.clientWidth, container.clientHeight)
      context.strokeStyle = 'rgba(220, 245, 255, .92)'
      context.lineWidth = 1.25
      for (const particle of particles) {
        const previous = pointAt(particle.path, particle.progress)
        particle.progress = (particle.progress + particle.speed * delta) % 1
        const next = pointAt(particle.path, particle.progress)
        context.beginPath()
        context.moveTo(previous.x, previous.y)
        context.lineTo(next.x, next.y)
        context.stroke()
      }
      frameRef.current = requestAnimationFrame(animate)
    }
    frameRef.current = requestAnimationFrame(animate)
    return () => {
      map.off('zoomend moveend resize', rebuild)
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      canvas.remove()
    }
  }, [artifact, enabled, map])
  return null
}

export function ZoomListener({ onZoom }: { onZoom: (zoom: number) => void }) {
  useMapEvents({ zoomend: event => onZoom(event.target.getZoom()) })
  return null
}

export function BathymetryOverlay({ bands, contours, showBands, showContours, showSlope, onSample }: { bands: BathymetryVectorLayer | null; contours: BathymetryVectorLayer | null; showBands: boolean; showContours: boolean; showSlope: boolean; onSample: (latitude: number, longitude: number) => void }) {
  const color = (feature?: GeoJSON.Feature) => {
    const value = Number(feature?.properties?.depth_m ?? 0)
    const slope = Number(feature?.properties?.slope_degrees ?? 0)
    if (showSlope) return slope >= 18 ? '#991b1b' : slope >= 9 ? '#ea580c' : slope >= 4 ? '#facc15' : '#0ea5e9'
    // Continuous bathymetry colour ramp preserves the subtle 0–1.2 m
    // variation in this shallow SDB scene rather than collapsing it all into
    // a single “< 1 m” categorical colour.
    const ratio = Math.max(0, Math.min(1, value / 1.2))
    return `hsl(${195 + ratio * 30} 78% ${76 - ratio * 43}%)`
  }
  const popup = (feature: GeoJSON.Feature) => {
    const p = feature.properties ?? {}
    return `<b>Copernicus SDB ~100 m</b><br/>Độ sâu: ${p.depth_m ?? '—'} m<br/>Dốc đáy: ${p.slope_degrees ?? '—'}°<br/>Quality: ${p.quality_indicator ?? '—'} · SDB type: ${p.sdb_type ?? '—'}<br/><small>Research only; not for navigation.</small>`
  }
  return <>
    {showBands && bands?.status === 'ready' && <GeoJSON data={bands} style={feature => ({ color: color(feature), fillColor: color(feature), weight: .15, opacity: .45, fillOpacity: showSlope ? .38 : .48 })} onEachFeature={(feature, layer) => {
      layer.bindPopup(popup(feature))
      layer.on('click', event => onSample(event.latlng.lat, event.latlng.lng))
    }} />}
    {showContours && contours?.status === 'ready' && <GeoJSON data={contours} style={feature => ({ color: Number(feature?.properties?.depth_m) >= 5 ? '#1e3a8a' : '#334155', weight: .8, opacity: .72 })} onEachFeature={(feature, layer) => layer.bindTooltip(`${feature.properties?.depth_m} m contour`)} />}
  </>
}

type FlowSample = { x: number; y: number; u: number; v: number; speed: number }
type WaterGeometry = GeoJSON.Geometry | null | undefined

export function EnvironmentalParticleOverlay({ layer, type, enabled, waterGeometry }: { layer?: Layer; type: 'flow' | 'wind'; enabled: boolean; waterGeometry: WaterGeometry }) {
  const map = useMap()
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const frameRef = useRef<number | null>(null)
  const particlesRef = useRef<Array<{ x: number; y: number; age: number; maxAge: number }>>([])
  const samplesRef = useRef<FlowSample[]>([])
  const binsRef = useRef<Map<string, FlowSample[]>>(new Map())

  useEffect(() => {
    if (!enabled || !layer?.geojson?.features.length) return undefined
    const container = map.getContainer()
    const canvas = document.createElement('canvas')
    canvas.className = 'flow-particle-canvas'
    canvas.width = container.clientWidth
    canvas.height = container.clientHeight
    container.appendChild(canvas)
    canvasRef.current = canvas
    const context = canvas.getContext('2d')
    if (!context) return undefined
    let waterPath = new Path2D()
    const addRing = (ring: number[][]) => {
      ring.forEach(([longitude, latitude], index) => {
        const point = map.latLngToContainerPoint([latitude, longitude])
        if (index === 0) waterPath.moveTo(point.x, point.y)
        else waterPath.lineTo(point.x, point.y)
      })
      waterPath.closePath()
    }
    const rebuildWaterPath = () => {
      waterPath = new Path2D()
      if (waterGeometry?.type === 'Polygon') waterGeometry.coordinates.forEach(addRing)
      if (waterGeometry?.type === 'MultiPolygon') waterGeometry.coordinates.forEach(polygon => polygon.forEach(addRing))
    }
    const isWaterPoint = (x: number, y: number) => !waterGeometry || context.isPointInPath(waterPath, x, y, 'evenodd')
    const randomWaterPoint = () => {
      for (let attempt = 0; attempt < 120; attempt++) {
        const x = Math.random() * container.clientWidth
        const y = Math.random() * container.clientHeight
        if (isWaterPoint(x, y)) return { x, y }
      }
      const fallback = samplesRef.current[0]
      return fallback ? { x: fallback.x, y: fallback.y } : { x: container.clientWidth / 2, y: container.clientHeight / 2 }
    }

    const rebuildSamples = () => {
      const pixelRatio = Math.min(2, window.devicePixelRatio || 1)
      canvas.width = Math.max(1, Math.floor(container.clientWidth * pixelRatio))
      canvas.height = Math.max(1, Math.floor(container.clientHeight * pixelRatio))
      canvas.style.width = `${container.clientWidth}px`
      canvas.style.height = `${container.clientHeight}px`
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
      rebuildWaterPath()
      samplesRef.current = layer.geojson?.features.flatMap(feature => {
        if (feature.geometry.type !== 'Point') return []
        const [longitude, latitude] = feature.geometry.coordinates as [number, number]
        const props = feature.properties ?? {}
        const u = Number(props.u_m_s)
        const v = Number(props.v_m_s)
        // Calm is a display classification at 0.35 m/s, but low-speed
        // vectors still belong to the visual field.  Dropping them entirely
        // made the particle layer disappear for this coastal snapshot.
        if (!Number.isFinite(u) || !Number.isFinite(v) || Math.hypot(u, v) < .05) return []
        const point = map.latLngToContainerPoint([latitude, longitude])
        return [{ x: point.x, y: point.y, u, v, speed: Math.hypot(u, v) }]
      }) ?? []
      const bins = new Map<string, FlowSample[]>()
      const binSize = 120
      for (const sample of samplesRef.current) {
        const key = `${Math.floor(sample.x / binSize)},${Math.floor(sample.y / binSize)}`
        const bucket = bins.get(key)
        if (bucket) bucket.push(sample)
        else bins.set(key, [sample])
      }
      binsRef.current = bins
      const countMultiplier = type === 'wind' ? 8 : 1.8
      const countMax = type === 'wind' ? 2200 : 900
      const particleCount = Math.min(countMax, Math.max(500, samplesRef.current.length * countMultiplier))
      particlesRef.current = Array.from({ length: particleCount }, (_, index) => {
        const sample = samplesRef.current[index % Math.max(1, samplesRef.current.length)]
        const maxAge = type === 'wind' ? 40 + Math.random() * 60 : 30 + Math.random() * 60
        const start = randomWaterPoint()
        return sample
          ? { x: start.x, y: start.y, age: Math.random() * 60, maxAge }
          : { x: start.x, y: start.y, age: 0, maxAge }
      })
    }
    rebuildSamples()
    const redraw = () => rebuildSamples()
    map.on('zoomend moveend resize', redraw)

    const respawn = (particle: { x: number; y: number; age: number; maxAge: number }) => {
      const start = randomWaterPoint()
      particle.x = start.x
      particle.y = start.y
      particle.age = 0
      particle.maxAge = type === 'wind' ? 40 + Math.random() * 60 : 30 + Math.random() * 60 // Giảm tuổi thọ hạt để chúng xuất hiện/biến mất nhanh
    }
    const interpolate = (x: number, y: number) => {
      const binSize = 120
      const bx = Math.floor(x / binSize), by = Math.floor(y / binSize)
      const candidates: FlowSample[] = []
      for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) {
        candidates.push(...(binsRef.current.get(`${bx + dx},${by + dy}`) ?? []))
      }
      const nearest = candidates.map(sample => ({ sample, distance: Math.hypot(sample.x - x, sample.y - y) })).sort((a, b) => a.distance - b.distance).slice(0, 4)
      const maxDistance = type === 'wind' ? 180 : 140 // Nới lỏng bán kính nội suy để các hạt phủ đều hơn
      const effectiveMaxDistance = Math.max(maxDistance, 360)
      if (!nearest.length || nearest[0].distance > effectiveMaxDistance) return null
      const weights = nearest.map(item => 1 / Math.max(item.distance, 4))
      const total = weights.reduce((sum, weight) => sum + weight, 0)
      return {
        u: nearest.reduce((sum, item, index) => sum + item.sample.u * weights[index], 0) / total,
        v: nearest.reduce((sum, item, index) => sum + item.sample.v * weights[index], 0) / total,
        speed: nearest.reduce((sum, item, index) => sum + item.sample.speed * weights[index], 0) / total,
      }
    }
    const animate = () => {
      // Fade only the particle canvas.  Painting translucent white would
      // accumulate over frames and eventually hide the Leaflet basemap.
      context.globalCompositeOperation = 'destination-out'
      context.fillStyle = type === 'wind' ? 'rgba(0,0,0,.03)' : 'rgba(0,0,0,.08)' // Tăng độ phai màu của hải lưu để đuôi ngắn hơn
      context.fillRect(0, 0, container.clientWidth, container.clientHeight)
      context.globalCompositeOperation = 'source-over'
      context.save()
      if (waterGeometry) context.clip(waterPath, 'evenodd')
      const centerLatitude = map.getCenter().lat * Math.PI / 180
      const metersPerPixel = 40075016.686 * Math.cos(centerLatitude) / (256 * 2 ** map.getZoom())
      for (const particle of particlesRef.current) {
        const vector = interpolate(particle.x, particle.y)
        if (!vector) { respawn(particle); continue }
        const oldX = particle.x, oldY = particle.y
      // Physical currents move only fractions of a screen pixel per frame at
      // this zoom.  Apply a visualization-only time scale so direction and
      // topology are visible; source speed and provenance remain unchanged.
      let step = 0;
      if (type === 'wind') {
        step = Math.max(.05, Math.min(1.5, vector.speed * 15 / Math.max(metersPerPixel, .1)));
      } else {
        step = Math.max(.3, Math.min(6.5, vector.speed * 250 / Math.max(metersPerPixel, .1))); // Tăng tốc độ chạy hải lưu
      }
      // Euler advection, with m/s converted to pixels at the current zoom.
      // Moderate visual time scale so sub-pixel Euler motion is observable.
      const visualSecondsPerFrame = type === 'wind' ? 2.5 : 55
      particle.x += vector.u / Math.max(metersPerPixel, .1) * visualSecondsPerFrame
      particle.y -= vector.v / Math.max(metersPerPixel, .1) * visualSecondsPerFrame
        particle.age += 1
        if (particle.age > particle.maxAge || particle.x < 0 || particle.y < 0 || particle.x > container.clientWidth || particle.y > container.clientHeight || !isWaterPoint(particle.x, particle.y)) { respawn(particle); continue }
        if (type === 'wind') {
          context.strokeStyle = `rgba(200, 200, 200, 0.8)` // Màu xám cho gió
          context.lineWidth = 1.0
        } else {
          context.strokeStyle = `rgba(0, 50, 150, 0.95)` // Màu xanh nước biển đậm cho dòng chảy
          context.lineWidth = 1.0 // Giảm độ rộng của vệt
        }
        // Elongate only the visual streak, not the Euler step: the particle
        // remains slow while its direction is legible.  The water-path clip
        // above prevents this longer tail from appearing over land/islands.
        const trailFactor = type === 'wind' ? 7 : 12
        const trailX = oldX - (particle.x - oldX) * (trailFactor - 1)
        const trailY = oldY - (particle.y - oldY) * (trailFactor - 1)
        context.beginPath(); context.moveTo(trailX, trailY); context.lineTo(particle.x, particle.y); context.stroke()
      }
      context.restore()
      frameRef.current = requestAnimationFrame(animate)
    }
    frameRef.current = requestAnimationFrame(animate)
    return () => {
      map.off('zoomend moveend resize', redraw)
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      canvas.remove()
      canvasRef.current = null
    }
  }, [enabled, layer, map, waterGeometry])
  return null
}

