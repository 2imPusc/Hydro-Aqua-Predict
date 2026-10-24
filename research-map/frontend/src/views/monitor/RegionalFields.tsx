import { memo, useMemo } from 'react'
import { CircleMarker, Tooltip } from 'react-leaflet'
import type { ContextRegion, Layer } from '../../types/monitor'
import { FieldOverlay, type FieldNode } from '../../components/map/overlays/FieldOverlay'
import { EnvironmentalParticleOverlay, PARTICLE_ON_FIELD } from '../../components/map/overlays/EnvironmentalParticleOverlay'
import { PALETTES, type FieldId } from '../../components/map/fieldPalettes'
import { providerLabel } from '../../lib/format'
import type { EnabledLayers } from './useMonitorData'

/**
 * Cobia limits of the "Khuyến nghị nuôi trồng" weather check (backend AQUACULTURE_THRESHOLDS): 6 h rain sum and
 * peak wind. Oyster uses 8 mm / 30 km/h; the legend says so.
 */
export const ADVISORY_RAIN_MM = 15
export const ADVISORY_WIND_KMH = 40

type AdvisoryPoint = { lon: number; lat: number; rain_6h_mm: number | null; wind_6h_kmh: number | null; series_complete?: boolean }

const nodesOf = (layer?: Layer): FieldNode[] => (layer?.geojson?.features ?? []).flatMap(feature => {
  const p = feature.properties ?? {}
  const lon = Number(p.requested_lon ?? (feature.geometry.type === 'Point' ? feature.geometry.coordinates[0] : NaN))
  const lat = Number(p.requested_lat ?? (feature.geometry.type === 'Point' ? feature.geometry.coordinates[1] : NaN))
  const value = Number(p.value)
  return Number.isFinite(lon) && Number.isFinite(lat) ? [{ lon, lat, value: Number.isFinite(value) ? value : null }] : []
})

const stepOf = (layer: Layer | undefined, region: ContextRegion | null) => Number((layer?.raster as { step_deg?: number } | undefined)?.step_deg ?? region?.step_deg ?? 0.125)
const sourceOf = (layer?: Layer) => `${providerLabel(layer?.provenance?.provider)}${layer?.provenance?.valid_at ? ` · ${new Date(layer.provenance.valid_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}` : ''}`

/** Which colour field is on (the toggles are mutually exclusive, one field at a time like Windy). */
export function activeField(enabled: EnabledLayers): FieldId | null {
  if (enabled.rain) return 'rain'
  if (enabled.wave) return 'wave'
  if (enabled.sea_level) return 'sea_level'
  if (enabled.advisory_forecast) return 'rain6h'
  if (enabled.wind_particles) return 'wind'
  if (enabled.flow_streamlines) return 'current'
  return null
}

type Props = { enabled: EnabledLayers; layers: Layer[]; region: ContextRegion | null; dataKey: string }

/**
 * Regional weather / ocean fields over the whole Hải Phòng – Cát Bà – Hạ Long extent: one smooth colour
 * field (fixed Windy-style scale) plus white particles for the direction of wind, waves and current.
 * Marine fields are clipped to water; rain and wind are real over land and are not.
 */
export const RegionalFields = memo(function RegionalFields({ enabled, layers, region, dataKey }: Props) {
  const water = useMemo(() => region?.features.find(feature => feature.properties?.kind === 'region_water')?.geometry ?? null, [region])
  const byName = useMemo(() => new Map(layers.map(layer => [layer.layer, layer])), [layers])
  const field = activeField(enabled)
  const rain = byName.get('rain'), wave = byName.get('wave'), sea = byName.get('sea_level'), wind = byName.get('wind'), current = byName.get('current'), advisory = byName.get('advisory_forecast')
  const advisoryPoints = useMemo(() => (Array.isArray(advisory?.data) ? advisory!.data as AdvisoryPoint[] : []), [advisory])
  const advisoryNodes = useMemo<FieldNode[]>(() => advisoryPoints.map(p => ({ lon: p.lon, lat: p.lat, value: p.rain_6h_mm,
    label: p.wind_6h_kmh != null ? `Gió mạnh nhất 6 giờ tới: ${Math.round(p.wind_6h_kmh)} km/h` : 'Thiếu chuỗi 6 giờ' })), [advisoryPoints])
  const usable = (layer?: Layer) => layer && layer.status !== 'unavailable' && (layer.geojson?.features.length ?? 0) > 0

  return <>
    {field === 'rain' && usable(rain) && <FieldOverlay nodes={nodesOf(rain)} step={stepOf(rain, region)} palette={PALETTES.rain} source={sourceOf(rain)} dataKey={`${dataKey}-rain`} />}
    {field === 'sea_level' && usable(sea) && <FieldOverlay nodes={nodesOf(sea)} step={stepOf(sea, region)} palette={PALETTES.sea_level} clip={water} source={sourceOf(sea)} dataKey={`${dataKey}-sea`} />}
    {field === 'wave' && usable(wave) && <>
      <FieldOverlay nodes={nodesOf(wave)} step={stepOf(wave, region)} palette={PALETTES.wave} clip={water} source={sourceOf(wave)} dataKey={`${dataKey}-wave`} />
      <EnvironmentalParticleOverlay type="wave" layer={wave} enabled waterGeometry={water} color={PARTICLE_ON_FIELD} gridStepDeg={stepOf(wave, region)} />
    </>}
    {field === 'wind' && usable(wind) && <>
      <FieldOverlay nodes={nodesOf(wind)} step={stepOf(wind, region)} palette={PALETTES.wind} source={sourceOf(wind)} dataKey={`${dataKey}-wind`} opacity={0.85} />
      <EnvironmentalParticleOverlay type="wind" layer={wind} enabled waterGeometry={undefined} color={PARTICLE_ON_FIELD} gridStepDeg={stepOf(wind, region)} />
    </>}
    {field === 'current' && usable(current) && <>
      <FieldOverlay nodes={nodesOf(current)} step={stepOf(current, region)} palette={PALETTES.current} clip={water} source={sourceOf(current)} dataKey={`${dataKey}-current`} />
      <EnvironmentalParticleOverlay type="flow" layer={current} enabled waterGeometry={water} color={PARTICLE_ON_FIELD} gridStepDeg={stepOf(current, region)} />
    </>}
    {field === 'rain6h' && advisoryNodes.length > 0 && <>
      <FieldOverlay nodes={advisoryNodes} step={stepOf(advisory, region)} palette={PALETTES.rain6h} source={sourceOf(advisory)} dataKey={`${dataKey}-adv`} />
      {/* Nodes that would trip the cobia rule: ring = rain ≥ 15 mm / 6 h, filled = peak wind ≥ 40 km/h. */}
      {advisoryPoints.filter(p => (p.rain_6h_mm ?? 0) >= ADVISORY_RAIN_MM || (p.wind_6h_kmh ?? 0) >= ADVISORY_WIND_KMH).map(p => {
        const windy = (p.wind_6h_kmh ?? 0) >= ADVISORY_WIND_KMH, wet = (p.rain_6h_mm ?? 0) >= ADVISORY_RAIN_MM
        return (
          <CircleMarker key={`${p.lon}-${p.lat}`} center={[p.lat, p.lon]} radius={7} pathOptions={{ color: '#b45309', weight: 2, fillColor: '#f59e0b', fillOpacity: windy ? 0.75 : 0 }}>
            <Tooltip>{[wet && `Mưa 6 giờ tới ${(p.rain_6h_mm ?? 0).toFixed(1).replace('.', ',')} mm ≥ ${ADVISORY_RAIN_MM}`, windy && `Gió mạnh nhất ${Math.round(p.wind_6h_kmh ?? 0)} km/h ≥ ${ADVISORY_WIND_KMH}`].filter(Boolean).join(' · ')}</Tooltip>
          </CircleMarker>
        )
      })}
    </>}
  </>
})
