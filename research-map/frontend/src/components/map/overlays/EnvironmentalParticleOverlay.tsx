import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'
import type { Layer } from '../../../types/monitor'
import { fitCanvas, startVisibleLoop } from './particleLoop'

type FlowSample = { x: number; y: number; u: number; v: number; speed: number }
type Particle = { x: number; y: number; age: number; maxAge: number }
type WaterGeometry = GeoJSON.Geometry | null | undefined

/** Default stroke colours per field; the monitor view passes theme-aware ones. */
export const PARTICLE_COLORS = {
  light: { flow: 'rgba(0, 50, 150, 0.95)', wind: 'rgba(90, 100, 120, 0.7)', wave: 'rgba(255, 255, 255, 0.9)' },
  dark: { flow: 'rgba(125, 211, 252, 0.9)', wind: 'rgba(210, 214, 222, 0.75)', wave: 'rgba(255, 255, 255, 0.85)' },
} as const
/** Windy-style white trails, used when a colour field is drawn underneath. */
export const PARTICLE_ON_FIELD = 'rgba(255, 255, 255, 0.95)'

type ParticleType = 'flow' | 'wind' | 'wave'
/** Visual-only time scale (s of motion per frame), trail length, count and fade per field. */
/**
 * `screen`: [min, max] px per frame and the magnitude that reaches max. Waves and currents are far too slow to
 * read at physical speed (Hs 0.05–0.4 m, currents < 0.2 m/s turned into still dots), so they move at a steady
 * on-screen speed that only grows with the magnitude; wind keeps its physical (scaled) speed.
 */
const STYLE: Record<ParticleType, { secondsPerFrame: number; trail: number; multiplier: number; max: number; fade: string; minAge: number; width: number; screen?: [number, number, number]; crest?: boolean }> = {
  flow: { secondsPerFrame: 55, trail: 7, multiplier: 7, max: 2000, fade: 'rgba(0,0,0,.04)', minAge: 50, width: 1.3, screen: [0.35, 1.6, 0.5] },
  wind: { secondsPerFrame: 6, trail: 7, multiplier: 8, max: 2200, fade: 'rgba(0,0,0,.04)', minAge: 40, width: 1.4 },
  // Wave u/v are the travel direction scaled by Hs (m), not a velocity: the speed only separates calm from rough.
  // Windy-style swell: short crest arcs across the travel direction drifting slowly forward (no streaks).
  wave: { secondsPerFrame: 70, trail: 1, multiplier: 4, max: 1100, fade: 'rgba(0,0,0,.22)', minAge: 70, width: 1.6, screen: [0.25, 0.8, 2], crest: true },
}

/**
 * Canvas particle advection over provider-sampled u/v vectors (current or wind).
 * The canvas exists only while `enabled`; the animation pauses while the tab is hidden.
 */
export function EnvironmentalParticleOverlay({ layer, type, enabled, waterGeometry, color, gridStepDeg }: { layer?: Layer; type: ParticleType; enabled: boolean; waterGeometry: WaterGeometry; color: string; gridStepDeg?: number }) {
  const map = useMap()
  const particlesRef = useRef<Particle[]>([])
  const samplesRef = useRef<FlowSample[]>([])
  const binsRef = useRef<Map<string, FlowSample[]>>(new Map())
  const binSizeRef = useRef(120)
  const colorRef = useRef(color)
  colorRef.current = color

  useEffect(() => {
    if (!enabled || !layer?.geojson?.features.length) return undefined
    const container = map.getContainer()
    const canvas = document.createElement('canvas')
    canvas.className = 'flow-particle-canvas'
    container.appendChild(canvas)
    const context = canvas.getContext('2d')
    if (!context) { canvas.remove(); return undefined }
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
      fitCanvas(canvas, context, container)
      rebuildWaterPath()
      samplesRef.current = layer.geojson?.features.flatMap(feature => {
        if (feature.geometry.type !== 'Point') return []
        const [longitude, latitude] = feature.geometry.coordinates as [number, number]
        const props = feature.properties ?? {}
        const u = Number(props.u_m_s)
        const v = Number(props.v_m_s)
        // Calm is a display classification at 0.35 m/s, but low-speed vectors
        // still belong to the visual field; dropping them made the particle
        // layer disappear for this coastal snapshot.
        if (!Number.isFinite(u) || !Number.isFinite(v) || Math.hypot(u, v) < .05) return []
        const point = map.latLngToContainerPoint([latitude, longitude])
        return [{ x: point.x, y: point.y, u, v, speed: Math.hypot(u, v) }]
      }) ?? []
      const bins = new Map<string, FlowSample[]>()
      // Neighbour search scales with the model grid on screen: a fixed 120 px search lost every sample
      // once the ~13 km regional grid was zoomed in, and the particles silently vanished.
      const center = map.getCenter()
      const stepPx = gridStepDeg ? Math.abs(map.latLngToContainerPoint([center.lat, center.lng + gridStepDeg]).x - map.latLngToContainerPoint(center).x) : 0
      const binSize = Math.max(120, stepPx)
      binSizeRef.current = binSize
      for (const sample of samplesRef.current) {
        const key = `${Math.floor(sample.x / binSize)},${Math.floor(sample.y / binSize)}`
        const bucket = bins.get(key)
        if (bucket) bucket.push(sample)
        else bins.set(key, [sample])
      }
      binsRef.current = bins
      const particleCount = Math.min(STYLE[type].max, Math.max(500, samplesRef.current.length * STYLE[type].multiplier))
      particlesRef.current = Array.from({ length: particleCount }, (_, index) => {
        const sample = samplesRef.current[index % Math.max(1, samplesRef.current.length)]
        const maxAge = STYLE[type].minAge + Math.random() * 60
        const start = randomWaterPoint()
        return sample ? { x: start.x, y: start.y, age: Math.random() * 60, maxAge } : { x: start.x, y: start.y, age: 0, maxAge }
      })
    }
    rebuildSamples()
    map.on('zoomend moveend resize', rebuildSamples)

    const respawn = (particle: Particle) => {
      const start = randomWaterPoint()
      particle.x = start.x
      particle.y = start.y
      particle.age = 0
      particle.maxAge = STYLE[type].minAge + Math.random() * 60
    }
    const interpolate = (x: number, y: number) => {
      const binSize = binSizeRef.current
      const bx = Math.floor(x / binSize), by = Math.floor(y / binSize)
      const candidates: FlowSample[] = []
      for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) {
        const bucket = binsRef.current.get(`${bx + dx},${by + dy}`)
        if (bucket) candidates.push(...bucket)
      }
      const nearest = candidates.map(sample => ({ sample, distance: Math.hypot(sample.x - x, sample.y - y) })).sort((a, b) => a.distance - b.distance).slice(0, 4)
      const effectiveMaxDistance = Math.max(360, binSize * 1.6)
      if (!nearest.length || nearest[0].distance > effectiveMaxDistance) return null
      const weights = nearest.map(item => 1 / Math.max(item.distance, 4))
      const total = weights.reduce((sum, weight) => sum + weight, 0)
      return {
        u: nearest.reduce((sum, item, index) => sum + item.sample.u * weights[index], 0) / total,
        v: nearest.reduce((sum, item, index) => sum + item.sample.v * weights[index], 0) / total,
        speed: nearest.reduce((sum, item, index) => sum + item.sample.speed * weights[index], 0) / total,
      }
    }
    const stop = startVisibleLoop(() => {
      // Fade only the particle canvas. Painting translucent white would
      // accumulate over frames and eventually hide the Leaflet basemap.
      context.globalCompositeOperation = 'destination-out'
      context.fillStyle = STYLE[type].fade
      context.fillRect(0, 0, container.clientWidth, container.clientHeight)
      context.globalCompositeOperation = 'source-over'
      context.save()
      if (waterGeometry) context.clip(waterPath, 'evenodd')
      const centerLatitude = map.getCenter().lat * Math.PI / 180
      const metersPerPixel = 40075016.686 * Math.cos(centerLatitude) / (256 * 2 ** map.getZoom())
      // Physical currents move only fractions of a pixel per frame at this
      // zoom; a visualization-only time scale makes direction and topology
      // visible. Source speed and provenance remain unchanged.
      const visualSecondsPerFrame = STYLE[type].secondsPerFrame
      const trailFactor = STYLE[type].trail
      context.strokeStyle = colorRef.current
      context.lineWidth = STYLE[type].width
      for (const particle of particlesRef.current) {
        const vector = interpolate(particle.x, particle.y)
        if (!vector) { respawn(particle); continue }
        const oldX = particle.x, oldY = particle.y
        const screen = STYLE[type].screen
        if (screen) {
          // Direction from u/v, on-screen speed from the magnitude (see STYLE).
          const magnitude = Math.hypot(vector.u, vector.v) || 1e-9
          const pixels = screen[0] + (screen[1] - screen[0]) * Math.min(1, magnitude / screen[2])
          particle.x += vector.u / magnitude * pixels
          particle.y -= vector.v / magnitude * pixels
        } else {
          // Euler advection, m/s converted to pixels at the current zoom.
          particle.x += vector.u / Math.max(metersPerPixel, .1) * visualSecondsPerFrame
          particle.y -= vector.v / Math.max(metersPerPixel, .1) * visualSecondsPerFrame
        }
        particle.age += 1
        if (particle.age > particle.maxAge || particle.x < 0 || particle.y < 0 || particle.x > container.clientWidth || particle.y > container.clientHeight || !isWaterPoint(particle.x, particle.y)) { respawn(particle); continue }
        if (STYLE[type].crest) {
          // Crest = short arc perpendicular to travel, bulging forward; longer for higher waves.
          const dx = particle.x - oldX, dy = particle.y - oldY, step = Math.hypot(dx, dy) || 1
          const ux = dx / step, uy = dy / step, half = 3 + 5 * Math.min(1, Math.hypot(vector.u, vector.v) / 1.5)
          context.beginPath()
          context.moveTo(particle.x - uy * half, particle.y + ux * half)
          context.quadraticCurveTo(particle.x + ux * half * 0.55, particle.y + uy * half * 0.55, particle.x + uy * half, particle.y - ux * half)
          context.stroke()
          continue
        }
        // Elongate only the visual streak, not the Euler step. The water clip
        // above keeps the longer tail off land/islands.
        const trailX = oldX - (particle.x - oldX) * (trailFactor - 1)
        const trailY = oldY - (particle.y - oldY) * (trailFactor - 1)
        context.beginPath(); context.moveTo(trailX, trailY); context.lineTo(particle.x, particle.y); context.stroke()
      }
      context.restore()
    })
    return () => {
      map.off('zoomend moveend resize', rebuildSamples)
      stop()
      canvas.remove()
    }
  }, [enabled, layer, map, type, waterGeometry, gridStepDeg])
  return null
}
