import { memo, useState } from 'react'
import { ChevronDown, Compass, Layers, MapPin, Mountain, Waves, Wind } from 'lucide-react'
import type { BathymetryManifest, EtopoManifest, GebcoManifest, FlowArtifact, HsiZones, Layer, StationNetwork } from '../../types/monitor'
import type { BasemapId, Lod } from '../../components/map/mapConfig'
import { Chip, SectionLabel, Segmented, StateChip, Toggle } from '../../components/ui'
import { HSI_LEGACY_LABEL } from '../../components/map/overlays/HsiZonesOverlay'
import { ENVIRONMENT_LAYERS, type EnabledLayers, type LayerKey } from './useMonitorData'
import { layerReason } from '../../lib/format'
import type { SiteExposure } from '../../components/map/siteExposure'

/**
 * Phones and tablets (≤ 1024 px): the left panels start collapsed so the map stays ≥ 70 % visible.
 * Read once for the initial state; the user's toggle wins afterwards.
 */
export const isCompactScreen = () => typeof window !== 'undefined' && window.matchMedia('(max-width: 1024px)').matches
/** Left-column width: 296 px on desktop, 256 px on tablets, never wider than the map minus the rail gap. */
export const LEFT_PANEL_WIDTH = 'w-[min(296px,calc(100vw-72px))] max-[1024px]:w-[min(256px,calc(100vw-72px))]'
/** Fades rows into the panel edge instead of cutting a line in half at the scroll boundary. */
export const SCROLL_FADE = { maskImage: 'linear-gradient(to bottom, transparent 0, #000 10px, #000 calc(100% - 18px), transparent 100%)', WebkitMaskImage: 'linear-gradient(to bottom, transparent 0, #000 10px, #000 calc(100% - 18px), transparent 100%)' }

type Props = {
  enabled: EnabledLayers
  onToggle: (key: LayerKey, value: boolean) => void
  environmentLayers: Layer[]
  snapshotLoaded: boolean
  flow: FlowArtifact | null
  currentLayer?: Layer
  windLayer?: Layer
  network: StationNetwork | null
  zones: HsiZones | null
  bathymetry: BathymetryManifest | null
  bathymetryError: string | null
  gebco: GebcoManifest | null
  etopo: EtopoManifest | null
  exposure: SiteExposure | null
  exposureError: string | null
  lod: Lod
  basemap: BasemapId
  onBasemap: (basemap: BasemapId) => void
}

/** One colour field at a time (Windy-style); the hint says what colour and particles mean. */
const FIELD_TOGGLES: Array<{ key: LayerKey; layer: string; label: string; hint: string }> = [
  { key: 'rain', layer: 'rain', label: 'Mưa', hint: 'màu = mưa giờ hiện tại' },
  { key: 'advisory_forecast', layer: 'advisory_forecast', label: 'Mưa & gió 6 giờ tới', hint: 'đầu vào của khuyến nghị nuôi; vòng cam = vượt ngưỡng cá giò' },
  { key: 'wind_particles', layer: 'wind', label: 'Gió', hint: 'màu = tốc độ · hạt trắng = hướng' },
  { key: 'wave', layer: 'wave', label: 'Sóng', hint: 'màu = độ cao · hạt trắng = hướng' },
  { key: 'sea_level', layer: 'sea_level', label: 'Mực nước', hint: 'so với mực nước trung bình' },
  { key: 'flow_streamlines', layer: 'current', label: 'Dòng chảy', hint: 'màu = tốc độ · hạt = hướng · tia quanh trạm' },
]

const LOD_LABEL: Record<Lod, string> = { low: 'Chi tiết thấp', medium: 'Chi tiết vừa', high: 'Chi tiết cao' }

/** Floating, grouped layer control (Bối cảnh · Dòng chảy & gió · Độ sâu · Mạng trạm · Bản đồ nền). */
export const LayerControl = memo(function LayerControl(props: Props) {
  const { enabled, onToggle, environmentLayers, snapshotLoaded, flow, currentLayer, windLayer, network, zones, bathymetry, bathymetryError, gebco, etopo, exposure, exposureError, lod, basemap, onBasemap } = props
  // Phones and tablets: start collapsed so the map stays usable; the header still names the area and layer count.
  const [open, setOpen] = useState(() => !isCompactScreen())
  const bathyReady = bathymetry?.status === 'ready'
  const bathyHint = bathyReady
    ? `${bathymetry?.source_resolution ?? 'Copernicus SDB'} · ${LOD_LABEL[lod]}`
    : bathymetry?.reason_code ? layerReason(bathymetry.reason_code) : bathymetry?.status === 'building' ? 'đang dựng lớp…' : bathymetryError ? 'không tải được' : 'đang tải…'
  const gebcoReady = gebco?.status === 'ready'
  const gebcoHint = gebcoReady ? `GEBCO 2024 · lưới ${gebco?.source_resolution ?? '~460 m'} · ~97 % nội suy` : gebco?.reason_code ? layerReason(gebco.reason_code) : 'đang tải…'
  const etopoReady = etopo?.status === 'ready'
  const etopoHint = !enabled.depth_etopo ? 'bật để so sánh với GEBCO' : etopoReady ? `ETOPO 2022 · ${etopo?.source_resolution ?? '~460 m'} · hố sâu giả ở Cửa Lục / Vân Đồn` : etopo?.reason_code ? layerReason(etopo.reason_code) : 'đang tải…'
  const exposureReady = exposure?.status === 'ready'
  const exposureHint = exposureReady
    ? `${exposure?.stations?.length ?? 0} trạm · hướng sóng lớn khi gió cấp 10`
    : exposure?.reason ? layerReason(exposure.reason) : exposureError ? 'không tải được' : 'đang tải…'
  const activeCount = Object.values(enabled).filter(Boolean).length
  const byName = new Map([...environmentLayers, ...(currentLayer ? [currentLayer] : []), ...(windLayer ? [windLayer] : [])].map(layer => [layer.layer as string, layer]))

  return (
    <section aria-label="Lớp bản đồ" className={`glass panel-enter pointer-events-auto flex min-h-0 ${LEFT_PANEL_WIDTH} flex-col overflow-hidden rounded-[var(--radius-lg)]`}>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3.5 py-3 text-left">
        <span className="grid size-8 flex-none place-items-center rounded-[var(--radius-sm)] bg-accent-soft text-accent"><Layers size={16} /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] font-semibold text-accent">Khu vực giám sát</span>
          <span className="block text-[13px] font-semibold leading-snug text-fg">Hải Phòng · Cát Bà · Lạch Huyện</span>
        </span>
        <Chip size="xs" tone="neutral" title="Số lớp đang bật">{activeCount}</Chip>
        <ChevronDown size={16} className={`flex-none text-fg-subtle transition-transform duration-200 ${open ? '' : '-rotate-90'}`} />
      </button>

      {open && (
        <div className="scroll-thin min-h-0 overflow-y-auto border-t border-line px-2 pb-5 pt-2" style={SCROLL_FADE}>
          <SectionLabel icon={<Wind size={12} />} trailing={<Chip size="xs" tone="neutral" title="Lưới dự báo phủ cả Hải Phòng, Cát Bà, Hạ Long; một lớp màu mỗi lúc">toàn vùng</Chip>}>Thời tiết & biển</SectionLabel>
          {FIELD_TOGGLES.map(item => {
            const layer = byName.get(item.layer)
            const ready = item.key === 'flow_streamlines' ? !!layer || !!flow : !!layer && layer.status !== 'unavailable'
            const step = Number((layer?.raster as { step_deg?: number } | undefined)?.step_deg)
            const grid = Number.isFinite(step) ? ` · điểm lưới ~${Math.round(step * 111)} km` : ''
            const description = !layer ? (snapshotLoaded ? 'bản tin hiện tại không có lớp này' : 'đang tải…') : layer.status === 'unavailable' ? layerReason(layer.reason_code) : `${item.hint}${grid}`
            return <Toggle key={item.key} checked={!!enabled[item.key]} disabled={!ready} onChange={value => onToggle(item.key, value)}
              label={item.label} description={description} badge={layer?.status === 'stale' ? <StateChip size="xs" state="stale" /> : undefined} />
          })}

          <SectionLabel icon={<Mountain size={12} />} trailing={bathyReady ? <Chip size="xs" tone="neutral">{LOD_LABEL[lod]}</Chip> : undefined}>Độ sâu</SectionLabel>
          <Toggle checked={enabled.depth_isobands} disabled={!gebcoReady} onChange={value => onToggle('depth_isobands', value)} label="Độ sâu vùng biển (GEBCO)" description={gebcoHint} />
          <Toggle checked={enabled.depth_isobaths} disabled={!gebcoReady} onChange={value => onToggle('depth_isobaths', value)} label="Đường đẳng sâu" description="2 / 5 / 10 / 20 / 30 m (từ GEBCO)" />
          <Toggle checked={enabled.depth_slope} disabled={!gebcoReady || !gebco?.files?.slope_medium} onChange={value => onToggle('depth_slope', value)} label="Độ dốc đáy"
            description={gebco?.files?.slope_medium ? 'tính từ GEBCO (~460 m) · chỉ thấy dốc lớn, không thấy rãnh hẹp' : 'đang dựng lớp…'} />
          <Toggle checked={enabled.bathymetry_bands} disabled={!bathyReady} onChange={value => onToggle('bathymetry_bands', value)} label="Bãi triều chi tiết (vệ tinh SDB)"
            description={bathyReady ? 'chỉ có ở bãi triều ven bờ Hải Phòng · không có ở Cát Bà, Hạ Long' : bathyHint} />
          {enabled.bathymetry_bands && <Toggle checked={enabled.bathymetry_contours} disabled={!bathyReady} onChange={value => onToggle('bathymetry_contours', value)} label="Đường mức bãi triều" description="0,25 / 0,5 / 0,75 / 1 m (cùng nguồn SDB)" />}
          <Toggle checked={enabled.depth_etopo} disabled={etopo?.status === 'unavailable'} onChange={value => onToggle('depth_etopo', value)} label="So sánh: ETOPO 2022" description={etopoHint} />

          <SectionLabel icon={<Compass size={12} />}>Phân tích (lý thuyết)</SectionLabel>
          <Toggle checked={enabled.site_exposure} disabled={!exposureReady} onChange={value => onToggle('site_exposure', value)} label="Phơi nhiễm sóng gió từng điểm nuôi"
            description={exposureHint} badge={<Chip size="xs" tone="info" title="Lý thuyết, chưa kiểm chứng hiện trường; không dùng cho cảnh báo">lý thuyết</Chip>} />

          <SectionLabel icon={<MapPin size={12} />}>Bối cảnh</SectionLabel>
          <Toggle checked={enabled.context_buffer} onChange={value => onToggle('context_buffer', value)} label="Vùng quanh trạm (5 km)" description="chỉ tính phần mặt nước" />
          <Toggle checked={enabled.hsi_zones} onChange={value => onToggle('hsi_zones', value)} label="Vùng HSI lịch sử"
            description={`${HSI_LEGACY_LABEL}${enabled.hsi_zones && !zones ? ' · đang tải…' : ''}`} badge={<StateChip size="xs" state="legacy" title={HSI_LEGACY_LABEL} />} />

          <SectionLabel icon={<Waves size={12} />}>Mạng trạm</SectionLabel>
          <Toggle checked={enabled.station_network} onChange={value => onToggle('station_network', value)} label="Kết nối mặt nước giữa các trạm"
            description={network?.network_status === 'building' ? 'đang dựng…' : network ? `${network.edge_count} đường nối · không phải hướng dòng chảy` : 'đang tải…'} />

          <SectionLabel>Bản đồ nền</SectionLabel>
          <div className="px-2">
            <Segmented label="Bản đồ nền" size="xs" value={basemap} onChange={onBasemap} options={[{ value: 'canvas', label: 'Tối giản' }, { value: 'street', label: 'Đường phố' }]} />
          </div>
        </div>
      )}
    </section>
  )
})

export const isEnvironmentLayer = (key: string) => (ENVIRONMENT_LAYERS as readonly string[]).includes(key)
