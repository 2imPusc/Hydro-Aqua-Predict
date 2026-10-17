import { useEffect } from 'react'
import { useMap } from 'react-leaflet'
import type { FlowArtifact } from '../../../types/monitor'
import { fitCanvas, startVisibleLoop } from './particleLoop'

/** Particles that travel along precomputed flow rays. Not mounted by the monitor view; kept for reuse. */
export function PrecomputedFlowParticleOverlay({ artifact, enabled }: { artifact: FlowArtifact; enabled: boolean }) {
  const map = useMap()

  useEffect(() => {
    if (!enabled) return undefined
    const container = map.getContainer()
    const canvas = document.createElement('canvas')
    canvas.className = 'flow-particle-canvas'
    container.appendChild(canvas)
    const context = canvas.getContext('2d')
    if (!context) { canvas.remove(); return undefined }
    type ScreenPoint = { x: number; y: number }
    type Particle = { path: ScreenPoint[]; progress: number; speed: number }
    let particles: Particle[] = []

    const rebuild = () => {
      fitCanvas(canvas, context, container)
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
    const stop = startVisibleLoop((_time, dt) => {
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
    })
    return () => {
      map.off('zoomend moveend resize', rebuild)
      stop()
      canvas.remove()
    }
  }, [artifact, enabled, map])
  return null
}
