import { memo, useState } from 'react'
import { ChevronDown, Compass, Layers, MapPin, Mountain, Waves, Wind } from 'lucide-react'
import type { BathymetryManifest, EtopoManifest, FlowArtifact, HsiZones, Layer, StationNetwork } from '../../types/monitor'
import { LABEL, type BasemapId, type Lod } from '../../components/map/mapConfig'
import { Chip, SectionLabel, Segmented, StateChip, Toggle } from '../../components/ui'
import { HSI_LEGACY_LABEL } from '../../components/map/overlays/HsiZonesOverlay'
import { ENVIRONMENT_LAYERS, type EnabledLayers, type LayerKey } from './useMonitorData'
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
  etopo: EtopoManifest | null
  exposure: SiteExposure | null
  exposureError: string | null
  lod: Lod
  basemap: BasemapId
  onBasemap: (basemap: BasemapId) => void
}

const LOD_LABEL: Record<Lod, string> = { low: 'LOD thấp', medium: 'LOD vừa', high: 'LOD cao' }

/** Floating, grouped layer control (Bối cảnh · Dòng chảy & gió · Độ sâu · Mạng trạm · Bản đồ nền). */
export const LayerControl = memo(function LayerControl(props: Props) {
  const { enabled, onToggle, environmentLayers, snapshotLoaded, flow, currentLayer, windLayer, network, zones, bathymetry, bathymetryError, etopo, exposure, exposureError, lod, basemap, onBasemap } = props
  // Phones and tablets: start collapsed so the map stays usable; the header still names the area and layer count.
  const [open, setOpen] = useState(() => !isCompactScreen())
  const bathyReady = bathymetry?.status === 'ready'
  const bathyHint = bathyReady
    ? `${bathymetry?.source_resolution ?? 'Copernicus SDB'} · ${LOD_LABEL[lod]}`
    : bathymetry?.reason_code ?? (bathymetry?.status === 'building' ? 'đang dựng artifact…' : bathymetryError ? 'không tải được manifest' : 'đang tải…')
  const etopoReady = etopo?.status === 'ready'
  const etopoHint = etopoReady ? `ETOPO 2022 · lưới ${etopo?.source_resolution ?? '~460 m'}` : etopo?.reason_code ?? 'đang tải…'
  const exposureReady = exposure?.status === 'ready'
  const exposureHint = exposureReady
    ? `${exposure?.stations?.length ?? 0} trạm · hoa hướng sóng gió cấp 10 · ${exposure?.run_name ?? ''}`
    : exposure?.reason ?? (exposureError ? 'không tải được' : 'đang tải…')
  const activeCount = Object.values(enabled).filter(Boolean).length

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
          <SectionLabel icon={<MapPin size={12} />}>Bối cảnh</SectionLabel>
          <Toggle checked={enabled.hsi_zones} onChange={value => onToggle('hsi_zones', value)} label="Vùng HSI lịch sử"
            description={`${HSI_LEGACY_LABEL}${enabled.hsi_zones && !zones ? ' · đang tải…' : ''}`} badge={<StateChip size="xs" state="legacy" title={HSI_LEGACY_LABEL} />} />
          <Toggle checked={enabled.context_buffer} onChange={value => onToggle('context_buffer', value)} label="Phạm vi context 5 km" description="buffer quanh mạng trạm · cắt theo mặt nước" />
          {environmentLayers.map(layer => {
            const unavailable = layer.status === 'unavailable'
            const description = unavailable ? (layer.reason_code ?? 'không khả dụng') : `${layer.kind} · ${layer.geojson?.features.length ?? 0} ${layer.kind === 'scalar_grid' ? 'ô' : 'vector'}${layer.provenance?.provider ? ` · ${layer.provenance.provider}` : ''}`
            return <Toggle key={layer.layer} checked={!!enabled[layer.layer as LayerKey]} disabled={unavailable} onChange={value => onToggle(layer.layer as LayerKey, value)}
              label={LABEL[layer.layer]} description={description} badge={layer.status === 'stale' ? <StateChip size="xs" state="stale" /> : undefined} />
          })}
          {!environmentLayers.length && <p className="m-0 px-2 py-1 text-[11.5px] text-fg-subtle">{snapshotLoaded ? 'Snapshot không có lớp mưa/sóng/mực nước.' : 'Chưa có snapshot context — lớp mưa, sóng, mực nước sẽ hiện khi backend phản hồi.'}</p>}

          <SectionLabel icon={<Compass size={12} />}>Phơi nhiễm sóng gió</SectionLabel>
          <Toggle checked={enabled.site_exposure} disabled={!exposureReady} onChange={value => onToggle('site_exposure', value)} label="Lớp hở / bán kín / kín"
            description={exposureHint} badge={<Chip size="xs" tone="info" title="Lý thuyết, chưa kiểm chứng hiện trường; không dùng cho cảnh báo">lý thuyết</Chip>} />

          <SectionLabel icon={<Wind size={12} />}>Dòng chảy & gió</SectionLabel>
          <Toggle checked={enabled.flow_streamlines} onChange={value => onToggle('flow_streamlines', value)} disabled={!flow && !currentLayer}
            label="Tia & hạt dòng chảy" description={flow ? `nội suy theo nước · ${flow.ray_count ?? 0} tia${currentLayer ? ' · hạt canvas' : ''}` : currentLayer ? 'chỉ hạt canvas · chưa có artifact tia' : 'chưa có artifact dòng chảy'} />
          <Toggle checked={enabled.wind_particles} onChange={value => onToggle('wind_particles', value)} disabled={!windLayer || windLayer.status === 'unavailable'}
            label="Vệt gió" description={windLayer ? `${windLayer.provenance?.provider ?? 'provider'} · hạt canvas (quan sát)` : 'chưa có lớp gió'} />

          <SectionLabel icon={<Mountain size={12} />} trailing={bathyReady ? <Chip size="xs" tone="neutral">{LOD_LABEL[lod]}</Chip> : undefined}>Độ sâu</SectionLabel>
          <Toggle checked={enabled.depth_isobands} disabled={!etopoReady} onChange={value => onToggle('depth_isobands', value)} label="Độ sâu vùng biển" description={etopoHint} />
          <Toggle checked={enabled.depth_isobaths} disabled={!etopoReady} onChange={value => onToggle('depth_isobaths', value)} label="Đường đẳng sâu" description="2 / 5 / 10 / 20 / 30 m" />
          <Toggle checked={enabled.bathymetry_bands} disabled={!bathyReady} onChange={value => onToggle('bathymetry_bands', value)} label="Bãi triều (SDB vệ tinh)" description={bathyHint} />
          <Toggle checked={enabled.bathymetry_contours} disabled={!bathyReady} onChange={value => onToggle('bathymetry_contours', value)} label="Đường đồng mức đáy" description="0,25 / 0,5 / 0,75 / 1 m; mức sâu hơn khi có" />
          <Toggle checked={enabled.bathymetry_slope} disabled={!bathyReady} onChange={value => onToggle('bathymetry_slope', value)} label="Độ dốc đáy" description="tính từ depth đã qua quality mask" />

          <SectionLabel icon={<Waves size={12} />}>Mạng trạm</SectionLabel>
          <Toggle checked={enabled.station_network} onChange={value => onToggle('station_network', value)} label="Kết nối mặt nước giữa các trạm"
            description={network?.network_status === 'building' ? 'đang dựng water-path…' : network ? `tĩnh · ${network.edge_count} cạnh · không biểu diễn hướng dòng chảy` : 'đang tải…'} />

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
