import { useRef } from 'react'
import { useMapEvents } from 'react-leaflet'
import { lodForZoom, MAP_ZOOM, type Lod } from '../mapConfig'

/** Emits only when the zoom crosses an LOD bucket, so state is not churned on every zoom step. */
export function LodListener({ onLod }: { onLod: (lod: Lod) => void }) {
  const last = useRef<Lod>(lodForZoom(MAP_ZOOM))
  useMapEvents({
    zoomend: event => {
      const lod = lodForZoom(event.target.getZoom())
      if (lod !== last.current) { last.current = lod; onLod(lod) }
    },
  })
  return null
}
