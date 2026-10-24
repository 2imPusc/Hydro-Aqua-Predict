import { memo, useEffect } from 'react'
import L from 'leaflet'
import { useMap } from 'react-leaflet'

export type SeabedShade = {
  status: 'ready' | 'building' | 'unavailable'
  width: number
  height: number
  bbox: [number, number, number, number]
  exaggeration: number
  dark_b64: string
  light_b64: string
}

const decode = (b64: string) => Uint8Array.from(atob(b64), c => c.charCodeAt(0))

/**
 * GEBCO seabed relief shading drawn over the depth bands: dark = slope facing away from the light (NW),
 * light = facing it. Depth is exaggerated server-side (legend says by how much); one image, smoothed by the browser.
 */
export const SeabedShadeOverlay = memo(function SeabedShadeOverlay({ shade, theme }: { shade: SeabedShade | null; theme: 'light' | 'dark' }) {
  const map = useMap()
  useEffect(() => {
    if (!shade || shade.status !== 'ready') return undefined
    const { width, height, bbox } = shade
    const dark = decode(shade.dark_b64), light = decode(shade.light_b64)
    const image = document.createElement('canvas')
    image.width = width; image.height = height
    const ictx = image.getContext('2d')!
    const pixels = ictx.createImageData(width, height)
    const shadow = theme === 'dark' ? [0, 0, 0] : [12, 30, 70]
    for (let i = 0; i < width * height; i++) {
      const o = i * 4
      if (dark[i] >= light[i]) {
        pixels.data[o] = shadow[0]; pixels.data[o + 1] = shadow[1]; pixels.data[o + 2] = shadow[2]
        pixels.data[o + 3] = Math.round(dark[i] * 0.6)
      } else {
        pixels.data[o] = 255; pixels.data[o + 1] = 255; pixels.data[o + 2] = 255
        pixels.data[o + 3] = Math.round(light[i] * 0.4)
      }
    }
    ictx.putImageData(pixels, 0, 0)
    const pane = 'seabed-shade'
    if (!map.getPane(pane)) { const el = map.createPane(pane); el.style.zIndex = '405'; el.style.pointerEvents = 'none' }
    const canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide') as HTMLCanvasElement
    canvas.style.pointerEvents = 'none'
    map.getPane(pane)!.appendChild(canvas)
    const [west, south, east, north] = bbox
    const cellLon = (east - west) / Math.max(1, width - 1), cellLat = (north - south) / Math.max(1, height - 1)
    const draw = () => {
      const size = map.getSize(), ratio = window.devicePixelRatio || 1
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))
      canvas.width = size.x * ratio; canvas.height = size.y * ratio
      canvas.style.width = `${size.x}px`; canvas.style.height = `${size.y}px`
      const ctx = canvas.getContext('2d')!
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      ctx.clearRect(0, 0, size.x, size.y)
      const nw = map.latLngToContainerPoint([north + cellLat / 2, west - cellLon / 2])
      const se = map.latLngToContainerPoint([south - cellLat / 2, east + cellLon / 2])
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(image, nw.x, nw.y, se.x - nw.x, se.y - nw.y)
    }
    draw()
    map.on('moveend zoomend resize viewreset', draw)
    return () => { map.off('moveend zoomend resize viewreset', draw); canvas.remove() }
  }, [map, shade, theme])
  return null
})
