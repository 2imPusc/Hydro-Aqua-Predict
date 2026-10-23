import { memo, useMemo, useState } from 'react'
import { ChevronDown, Palette } from 'lucide-react'
import type { EtopoManifest, Layer } from '../../types/monitor'
import type { Theme } from '../../hooks/useTheme'
import { DEPTH_BAND_LABELS, depthBandColor, FLAG_STYLE } from '../../components/map/overlays/EtopoDepthOverlay'
import { scalarColor } from '../../components/map/overlays/ScalarGridOverlay'
import { GradientLegend, SwatchLegend } from '../../components/ui'
import { HSI_CLASSES, HSI_LEGACY_LABEL } from '../../components/map/overlays/HsiZonesOverlay'
import { SEVERITY_STYLE, STALE_STYLE } from '../../components/map/overlays/StationMarkers'
import { EXPOSURE_INK } from '../../components/map/overlays/SiteExposureOverlay'
import { wedgePath, type SiteExposure } from '../../components/map/siteExposure'
import type { EnabledLayers } from './useMonitorData'
import { isCompactScreen, LEFT_PANEL_WIDTH, SCROLL_FADE } from './LayerControl'

const SCALAR_TITLE: Record<string, string> = { rain: 'Mưa', sea_level: 'Mực nước', mixed_layer_depth: 'Mixed-layer depth' }

/** Smooth scalar field legend; states the model grid so the smoothness is not read as fine detail. */
function ScalarLegend({ layer }: { layer: Layer }) {
  const range = useMemo(() => {
    const values = layer.geojson?.features.map(feature => Number(feature.properties?.value)).filter(Number.isFinite) ?? []
    return values.length ? [Math.min(...values), Math.max(...values)] : null
  }, [layer])
  if (!range) return null
  const unit = String(layer.geojson?.features[0]?.properties?.unit ?? '')
  const grid = layer.provenance?.source_grid_resolution ?? layer.provenance?.grid_resolution
  return <GradientLegend title={SCALAR_TITLE[layer.layer] ?? layer.layer} gradient={`linear-gradient(90deg, ${scalarColor(0)}, ${scalarColor(1)})`}
    ticks={[`${range[0].toFixed(2)} ${unit}`, `${range[1].toFixed(2)} ${unit}`]}
    note={`Nội suy mượt giữa điểm mẫu${grid ? ` · lưới nguồn ${grid}` : ''}`} />
}

/** Stepped (one colour per band) depth legend; hard stops match the isobands. */
function DepthLegend({ theme, etopo }: { theme: Theme; etopo: EtopoManifest | null }) {
  const n = DEPTH_BAND_LABELS.length
  const stops = DEPTH_BAND_LABELS.map((_, i) => `${depthBandColor(i, theme)} ${(i / n) * 100}% ${((i + 1) / n) * 100}%`).join(', ')
  return <div className="space-y-2">
    <div>
      <div className="text-[11.5px] font-semibold text-fg">Độ sâu (m)</div>
      <div className="mt-1.5 h-2.5 rounded-sm ring-1 ring-inset ring-black/5" style={{ background: `linear-gradient(90deg, ${stops})` }} />
      <div className="mt-1 grid text-[10px] text-fg-subtle tabular" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}>{DEPTH_BAND_LABELS.map(label => <span key={label} className="text-center">{label}</span>)}</div>
      <div className="mt-1 text-[10.5px] text-fg-subtle">ETOPO 2022, lưới {etopo?.source_resolution ?? '~460 m'} · so với mực nước TB, không phải số 0 hải đồ · không dùng cho hàng hải</div>
    </div>
    <SwatchLegend title="Độ tin cậy" items={[{ color: FLAG_STYLE.coarse.color, label: FLAG_STYLE.coarse.label, shape: 'dash' }, { color: FLAG_STYLE.suspect.color, label: FLAG_STYLE.suspect.label, shape: 'dash' }]} />
  </div>
}

/** Exposure: wedge = wind direction (from), length = Hs at cấp 10, ink weight = Hs band; pill = exposure class. */
function ExposureLegend({ theme, exposure }: { theme: Theme; exposure: SiteExposure | null }) {
  const ink = EXPOSURE_INK[theme]
  const wedge = (opacity: number) => <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden className="flex-none"><path d={wedgePath(2, 14, 0, 14, 45, 14)} fill={ink} fillOpacity={opacity} /></svg>
  return <div>
    <div className="flex items-center gap-1.5 text-[11.5px] font-semibold text-fg">Phơi nhiễm sóng gió <span className="rounded-[4px] bg-info-bg px-1 text-[10px] font-semibold text-info">lý thuyết</span></div>
    <ul className="m-0 mt-1.5 grid list-none gap-y-1 p-0 text-[11px] text-fg-muted">
      <li className="flex items-center gap-2">{wedge(0.92)}Hướng gió cho sóng Hs ≥ 2 m (nguy hiểm)</li>
      <li className="flex items-center gap-2">{wedge(0.42)}Hs 1–2 m (cần chú ý); dài hơn = sóng lớn hơn</li>
      <li className="flex items-center gap-2"><span className="flex-none rounded-[4px] border border-line-strong bg-surface px-1 text-[10px] font-semibold text-fg">hở</span>Lớp: hở / bán kín / kín (Hs lớn nhất ở gió cấp 8)</li>
    </ul>
    <div className="mt-1 text-[10.5px] text-fg-subtle">Gió ngoài khơi cấp 10 (24,5 m/s); đà gió + che chắn địa hình + SPM 1984. Chưa kiểm chứng, không dùng cho cảnh báo.{exposure?.run_name ? ` Run ${exposure.run_name}.` : ''}</div>
  </div>
}

/** Bottom-left legends for whatever is switched on. */
export const MapLegends = memo(function MapLegends({ enabled, environmentLayers, mockMode, theme, etopo, advisoryStale, exposure }: { enabled: EnabledLayers; environmentLayers: Layer[]; mockMode: boolean; theme: Theme; etopo: EtopoManifest | null; advisoryStale: boolean; exposure: SiteExposure | null }) {
  const [open, setOpen] = useState(() => !isCompactScreen())
  const scalar = environmentLayers.find(layer => layer.kind === 'scalar_grid' && enabled[layer.layer as keyof EnabledLayers])
  const bathyBands = enabled.bathymetry_bands && !enabled.bathymetry_slope
  return (
    <section aria-label="Chú giải" className={`glass pointer-events-auto ${LEFT_PANEL_WIDTH} flex-none overflow-hidden rounded-[var(--radius-lg)]`}>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="flex w-full items-center gap-2 px-3.5 py-2 text-left">
        <Palette size={14} className="text-fg-subtle" />
        <span className="flex-1 text-[12px] font-semibold text-fg">Chú giải</span>
        <ChevronDown size={15} className={`text-fg-subtle transition-transform duration-200 ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && (
        <div className="scroll-thin max-h-[34vh] space-y-3 overflow-y-auto border-t border-line px-3.5 pb-5 pt-2.5" style={SCROLL_FADE}>
          <SwatchLegend title="Trạng thái trạm" items={[
            ...(['NORMAL', 'WATCH', 'WARNING', 'UNKNOWN'] as const).map(key => ({ color: SEVERITY_STYLE[key].color, label: SEVERITY_STYLE[key].label, shape: 'dot' as const })),
            { color: STALE_STYLE.pattern, label: STALE_STYLE.label, shape: 'dot' as const },
          ]} columns={2}
            note={<>{advisoryStale && <b className="font-semibold text-fg">Khuyến nghị đang cũ: trạm hiện sọc xám, không theo mức. </b>}{mockMode ? 'Viền tím nét đứt = điểm mô phỏng.' : 'Một cảm biến vật lý (06M26042804); các điểm khác dùng chung số đo của trạm này.'}</>} />
          {enabled.site_exposure && exposure?.status === 'ready' && <ExposureLegend theme={theme} exposure={exposure} />}
          {enabled.hsi_zones && <SwatchLegend title="HSI lịch sử" note={HSI_LEGACY_LABEL} items={HSI_CLASSES.map(item => ({ color: item.color, label: item.label }))} columns={2} />}
          {(enabled.depth_isobands || enabled.depth_isobaths) && <DepthLegend theme={theme} etopo={etopo} />}
          {scalar && <ScalarLegend layer={scalar} />}
          {enabled.flow_streamlines && <SwatchLegend title="Tia dòng chảy" items={[{ color: '#0b5fc1', label: 'Tia nội suy theo nước (+ hạt minh hoạ)', shape: 'line' }, { color: '#ea580c', label: 'Tương thích dòng–trạm (research only)', shape: 'line' }]} />}
          {enabled.wind_particles && <SwatchLegend title="Vệt gió (10 m)" items={[{ color: 'var(--fg-subtle)', label: 'Hạt canvas một màu — chỉ hướng, không mã hoá tốc độ', shape: 'line' }]} note="Chỉ quan sát · không kích hoạt cảnh báo" />}
          {bathyBands && <GradientLegend title="Bãi triều (SDB vệ tinh ~100 m)" gradient="linear-gradient(to right, hsl(195 78% 76%), hsl(210 78% 55%), hsl(225 78% 33%))" ticks={['0 m', '0.6 m', '≥ 1.2 m']} note="Chỉ nghiên cứu; không dùng cho hàng hải" />}
          {enabled.bathymetry_slope && <SwatchLegend title="Độ dốc đáy" items={[{ color: '#0ea5e9', label: '< 4°' }, { color: '#facc15', label: '4–9°' }, { color: '#ea580c', label: '9–18°' }, { color: '#991b1b', label: '≥ 18°' }]} columns={2} />}
          {enabled.station_network && <SwatchLegend title="Mạng trạm" items={[{ color: '#64748b', label: 'Kết nối mặt nước tĩnh (không phải hướng dòng)', shape: 'dash' }]} />}
          {enabled.context_buffer && <SwatchLegend title="Phạm vi" items={[{ color: '#38bdf8', label: 'Context 5 km trên mặt nước' }, { color: '#2563eb', label: 'Biên buffer', shape: 'dash' }]} />}
        </div>
      )}
    </section>
  )
})
