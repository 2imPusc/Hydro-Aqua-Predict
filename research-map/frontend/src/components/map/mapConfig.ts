import L from 'leaflet'
import type { LayerName } from '../../types/monitor'

// Start from the Hai Phong–Cat Ba regional view. Users can zoom into the
// sensor/cage area, but the initial map does not crop the surrounding bay.
export const MAP_CENTER: [number, number] = [20.78, 107.03]
// Pan limits include Ha Long / Bai Tu Long (Quang Ninh), where the GEBCO / ETOPO depth layers extend.
export const MAP_BOUNDS: [[number, number], [number, number]] = [[20.40, 106.55], [21.45, 107.95]]
export const MAP_ZOOM = 11

export type Lod = 'low' | 'medium' | 'high'
export const lodForZoom = (zoom: number): Lod => (zoom >= 13 ? 'high' : zoom >= 11 ? 'medium' : 'low')

export const LABEL: Record<LayerName, string> = {
  wind: 'Gió', rain: 'Mưa', wave: 'Sóng', current: 'Dòng chảy',
  sea_level: 'Mực nước / SSH', mixed_layer_depth: 'Mixed-layer depth', bathymetry: 'Bathymetry & slope',
  advisory_forecast: 'Dự báo khuyến nghị',
}

export type BasemapId = 'canvas' | 'street'
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services'
export const ESRI_ATTRIBUTION = 'Tiles © Esri · Map data © OpenStreetMap contributors'

/** Basemap tile URLs. `canvas` follows the UI theme (light/dark gray). */
export function basemapTiles(id: BasemapId, theme: 'light' | 'dark'): { base: string; labels?: string } {
  if (id === 'street') return { base: `${ESRI}/World_Street_Map/MapServer/tile/{z}/{y}/{x}` }
  const tone = theme === 'dark' ? 'Dark' : 'Light'
  return {
    base: `${ESRI}/Canvas/World_${tone}_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    labels: `${ESRI}/Canvas/World_${tone}_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  }
}

/** Bearing (degrees from north) between two [lon, lat] points. */
export function bearingBetween(from: [number, number], to: [number, number]): number {
  return (Math.atan2(to[0] - from[0], to[1] - from[1]) * 180 / Math.PI + 360) % 360
}

export function arrowIcon(bearing: number, color: string, speed = 0, animated = false) {
  const size = Math.max(17, Math.min(28, 17 + speed * 5))
  // The arrow glyph points east at 0 CSS degrees; provider bearings are from
  // north, so rotate by bearing - 90 to preserve the published convention.
  return L.divIcon({ className: `context-arrow${animated ? ' wind-arrow' : ''}`, html: `<span style="display:block;color:${color};font-size:${size}px;transform:rotate(${bearing - 90}deg)">➜</span>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2] })
}

export const escapeHtml = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!))
