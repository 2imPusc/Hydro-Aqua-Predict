import { memo, useState } from 'react'
import { ChevronDown, Palette } from 'lucide-react'
import type { EtopoManifest, GebcoManifest, Layer } from '../../types/monitor'
import type { Theme } from '../../hooks/useTheme'
import { DEPTH_BAND_LABELS, depthBandColor, FLAG_STYLE } from '../../components/map/overlays/EtopoDepthOverlay'
import { GradientLegend, SwatchLegend } from '../../components/ui'
import { HSI_CLASSES, HSI_LEGACY_LABEL } from '../../components/map/overlays/HsiZonesOverlay'
import { SEVERITY_STYLE, STALE_STYLE } from '../../components/map/overlays/StationMarkers'
import { EXPOSURE_INK } from '../../components/map/overlays/SiteExposureOverlay'
import { wedgePath, type SiteExposure } from '../../components/map/siteExposure'
import type { EnabledLayers } from './useMonitorData'
import { PALETTES, paletteGradient } from '../../components/map/fieldPalettes'
import { GEBCO_SLOPE_CLASSES } from '../../components/map/overlays/GebcoSlopeOverlay'
import { activeField, ADVISORY_RAIN_MM, ADVISORY_WIND_KMH } from './RegionalFields'
import { num } from '../../lib/format'
import { isCompactScreen, LEFT_PANEL_WIDTH, SCROLL_FADE } from './LayerControl'

/** Fixed-scale colour key of the active regional field; states the model grid so smoothness is not read as detail. */
function FieldLegend({ id, layer }: { id: keyof typeof PALETTES; layer?: Layer }) {
  const palette = PALETTES[id]
  const step = Number((layer?.raster as { step_deg?: number } | undefined)?.step_deg)
  const grid = Number.isFinite(step) ? `điểm lưới ~${Math.round(step * 111)} km` : 'lưới mô hình'
  const notes: Record<string, string> = {
    rain: 'Màu trong suốt = không mưa.',
    rain6h: `Vòng cam: mưa ≥ ${ADVISORY_RAIN_MM} mm hoặc (tô kín) gió ≥ ${ADVISORY_WIND_KMH} km/h trong 6 giờ tới — ngưỡng cá giò của khuyến nghị nuôi (hàu: 8 mm, 30 km/h).`,
    wind: 'Hạt trắng chạy theo hướng gió.',
    wave: 'Hạt trắng chạy theo hướng sóng; chỉ trên mặt nước.',
    current: 'Hạt trắng theo hướng dòng; mô hình ~8 km không thấy dòng siết ở luồng hẹp.',
    sea_level: 'Dương = cao hơn mực nước trung bình (triều + nước dâng).',
  }
  return <GradientLegend title={`${palette.title} (${palette.unit})`} gradient={paletteGradient(palette)}
    ticks={palette.ticks.map(v => num(v, 2).replace(/,00$/, '').replace(/(,\d)0$/, '$1'))}
    note={`${notes[id]} Open-Meteo, ${grid}; tô mượt giữa các điểm, không thêm chi tiết.`} />
}

/** Stepped (one colour per band) depth legend; hard stops match the isobands. */
function DepthLegend({ theme, gebco, showEtopo }: { theme: Theme; gebco: GebcoManifest | null; showEtopo: boolean }) {
  const n = DEPTH_BAND_LABELS.length
  const stops = DEPTH_BAND_LABELS.map((_, i) => `${depthBandColor(i, theme)} ${(i / n) * 100}% ${((i + 1) / n) * 100}%`).join(', ')
  return <div className="space-y-2">
    <div>
      <div className="text-[11.5px] font-semibold text-fg">Độ sâu (m)</div>
      <div className="mt-1.5 h-2.5 rounded-sm ring-1 ring-inset ring-black/5" style={{ background: `linear-gradient(90deg, ${stops})` }} />
      <div className="mt-1 grid text-[10px] text-fg-subtle tabular" style={{ gridTemplateColumns: `repeat(${n}, 1fr)` }}>{DEPTH_BAND_LABELS.map(label => <span key={label} className="text-center">{label}</span>)}</div>
      <div className="mt-1 text-[10.5px] text-fg-subtle">GEBCO 2024 (15″ ≈ 460 m) · datum MSL (mực nước TB), không phải số 0 hải đồ · không dùng cho hàng hải</div>
    </div>
    <SwatchLegend title="Độ tin cậy (TID)" items={[
      { color: depthBandColor(3, theme), label: 'Đo trực tiếp (đậm)', shape: 'square' },
      { color: depthBandColor(3, theme) + '99', label: 'Nội suy / dự đoán', shape: 'square' },
      { color: FLAG_STYLE.coarse.color, label: FLAG_STYLE.coarse.label, shape: 'dash' },
      { color: FLAG_STYLE.suspect.color, label: FLAG_STYLE.suspect.label, shape: 'dash' },
    ]} note={<>~97 % ô là nội suy; chỉ ~3 % đo trực tiếp (TID){gebco?.direct_cell_count != null && gebco.depth_cell_count ? ` · vùng này ${(100 * gebco.direct_cell_count / gebco.depth_cell_count).toFixed(1).replace('.', ',')} %` : ''}. Tại lồng NB1 giá trị là nội suy.</>} />
    {showEtopo && <div className="text-[10.5px] text-fg-subtle">Lớp so sánh ETOPO 2022 vẽ dưới GEBCO; hố sâu ở Cửa Lục / Vân Đồn bị cờ “nghi lỗi nguồn”.</div>}
    <div className="text-[10px] text-fg-subtle">GEBCO Compilation Group (2024) GEBCO 2024 Grid</div>
  </div>
}

/** Exposure: wedge = wind direction (from), length = Hs at cấp 10, ink weight = Hs band; pill = exposure class. */
function ExposureLegend({ theme, exposure }: { theme: Theme; exposure: SiteExposure | null }) {
  const ink = EXPOSURE_INK[theme]
  const wedge = (opacity: number) => <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden className="flex-none"><path d={wedgePath(2, 14, 0, 14, 45, 14)} fill={ink} fillOpacity={opacity} /></svg>
  return <div>
    <div className="flex items-center gap-1.5 text-[11.5px] font-semibold text-fg">Phơi nhiễm sóng gió <span className="rounded-[4px] bg-info-bg px-1 text-[10px] font-semibold text-info">lý thuyết</span></div>
    <ul className="m-0 mt-1.5 grid list-none gap-y-1 p-0 text-[11px] text-fg-muted">
      <li className="flex items-center gap-2">{wedge(0.92)}Gió thổi từ hướng này cho sóng Hs ≥ 2 m (nguy hiểm)</li>
      <li className="flex items-center gap-2">{wedge(0.42)}Hs 1–2 m (cần chú ý); dài hơn = sóng lớn hơn</li>
      <li className="flex items-center gap-2"><span className="flex-none rounded-[4px] border border-line-strong bg-surface px-1 text-[10px] font-semibold text-fg">hở</span>Lớp: hở / bán kín / kín (Hs lớn nhất ở gió cấp 8)</li>
    </ul>
    <div className="mt-1 text-[10.5px] text-fg-subtle">Gió ngoài khơi cấp 10 (24,5 m/s); đà gió + che chắn địa hình + SPM 1984. Chưa kiểm chứng, không dùng cho cảnh báo.{exposure?.run_name ? ` Run ${exposure.run_name}.` : ''}</div>
  </div>
}

/** Bottom-left legends for whatever is switched on. */
export const MapLegends = memo(function MapLegends({ enabled, environmentLayers, mockMode, theme, gebco, etopo, advisoryStale, exposure }: { enabled: EnabledLayers; environmentLayers: Layer[]; mockMode: boolean; theme: Theme; gebco: GebcoManifest | null; etopo: EtopoManifest | null; advisoryStale: boolean; exposure: SiteExposure | null }) {
  const [open, setOpen] = useState(() => !isCompactScreen())
  const field = activeField(enabled)
  const fieldLayer = environmentLayers.find(layer => layer.layer === ({ rain: 'rain', rain6h: 'advisory_forecast', wind: 'wind', wave: 'wave', current: 'current', sea_level: 'sea_level' } as const)[field ?? 'rain'])
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
          {/* Depth colours most of the map by default: its key comes right after the station states. */}
          {(enabled.depth_isobands || enabled.depth_isobaths) && <DepthLegend theme={theme} gebco={gebco} showEtopo={enabled.depth_etopo && etopo?.status === 'ready'} />}
          {enabled.site_exposure && exposure?.status === 'ready' && <ExposureLegend theme={theme} exposure={exposure} />}
          {enabled.hsi_zones && <SwatchLegend title="HSI lịch sử" note={HSI_LEGACY_LABEL} items={HSI_CLASSES.map(item => ({ color: item.color, label: item.label }))} columns={2} />}
          {field && <FieldLegend id={field} layer={fieldLayer} />}
          {enabled.flow_streamlines && <SwatchLegend title="Tia dòng chảy quanh trạm" items={[{ color: '#0b5fc1', label: 'Tia nội suy theo mặt nước', shape: 'line' }, { color: '#ea580c', label: 'Tương thích dòng–trạm (chỉ nghiên cứu)', shape: 'line' }]} />}
          {bathyBands && <GradientLegend title="Bãi triều (vệ tinh SDB ~100 m)" gradient="linear-gradient(to right, hsl(195 78% 76%), hsl(210 78% 55%), hsl(225 78% 33%))" ticks={['0 m', '1 m', '≥ 2 m']} note="Chỉ có ở bãi triều ven bờ Hải Phòng · không dùng cho hàng hải" />}
          {enabled.depth_slope && <SwatchLegend title="Độ dốc đáy (GEBCO ~460 m)" items={GEBCO_SLOPE_CLASSES.map(item => ({ color: item.color, label: item.label }))} columns={2} note="Lưới thô: chỉ thấy sườn dốc lớn quanh đảo, không thấy rãnh hẹp." />}
          {enabled.station_network && <SwatchLegend title="Mạng trạm" items={[{ color: '#64748b', label: 'Kết nối mặt nước tĩnh (không phải hướng dòng)', shape: 'dash' }]} />}
          {enabled.context_buffer && <SwatchLegend title="Phạm vi" items={[{ color: '#38bdf8', label: 'Context 5 km trên mặt nước' }, { color: '#2563eb', label: 'Biên buffer', shape: 'dash' }]} />}
        </div>
      )}
    </section>
  )
})
