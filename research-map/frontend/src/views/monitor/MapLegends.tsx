import { memo, useMemo, useState } from 'react'
import { ChevronDown, Palette } from 'lucide-react'
import type { Layer } from '../../types/monitor'
import { GradientLegend, SwatchLegend } from '../../components/ui'
import { HSI_CLASSES, HSI_LEGACY_LABEL } from '../../components/map/overlays/HsiZonesOverlay'
import { SEVERITY_STYLE } from '../../components/map/overlays/StationMarkers'
import type { EnabledLayers } from './useMonitorData'

function RainLegend({ layer }: { layer: Layer }) {
  const range = useMemo(() => {
    const values = layer.geojson?.features.map(feature => Number(feature.properties?.value)).filter(Number.isFinite) ?? []
    return values.length ? [Math.min(...values), Math.max(...values)] : null
  }, [layer])
  if (!range) return null
  return <GradientLegend title="Thang mưa" gradient="linear-gradient(90deg, hsl(215 78% 52%), hsl(180 78% 52%))" ticks={[`${range[0].toFixed(1)} mm`, `${range[1].toFixed(1)} mm`]} />
}

/** Bottom-left legends for whatever is switched on. */
export const MapLegends = memo(function MapLegends({ enabled, environmentLayers, mockMode }: { enabled: EnabledLayers; environmentLayers: Layer[]; mockMode: boolean }) {
  const [open, setOpen] = useState(true)
  const rain = environmentLayers.find(layer => layer.layer === 'rain')
  const bathyBands = enabled.bathymetry_bands && !enabled.bathymetry_slope
  return (
    <section aria-label="Chú giải" className="glass pointer-events-auto w-[296px] flex-none overflow-hidden rounded-[var(--radius-lg)]">
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="flex w-full items-center gap-2 px-3.5 py-2 text-left">
        <Palette size={14} className="text-fg-subtle" />
        <span className="flex-1 text-[12px] font-semibold text-fg">Chú giải</span>
        <ChevronDown size={15} className={`text-fg-subtle transition-transform duration-200 ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && (
        <div className="scroll-thin max-h-[34vh] space-y-3 overflow-y-auto border-t border-line px-3.5 pb-3 pt-2.5">
          <SwatchLegend title="Trạng thái trạm" items={(['NORMAL', 'WATCH', 'WARNING', 'UNKNOWN'] as const).map(key => ({ color: SEVERITY_STYLE[key].color, label: SEVERITY_STYLE[key].label, shape: 'dot' as const }))} columns={2}
            note={mockMode ? 'Viền tím nét đứt = điểm mô phỏng.' : 'Một cảm biến vật lý (06M26042804); các điểm khác dùng chung số đo của trạm này.'} />
          {enabled.hsi_zones && <SwatchLegend title="HSI lịch sử" note={HSI_LEGACY_LABEL} items={HSI_CLASSES.map(item => ({ color: item.color, label: item.label }))} columns={2} />}
          {enabled.rain && rain && <RainLegend layer={rain} />}
          {enabled.flow_streamlines && <SwatchLegend title="Tia dòng chảy" items={[{ color: '#0b5fc1', label: 'Tia nội suy theo nước (+ hạt minh hoạ)', shape: 'line' }, { color: '#ea580c', label: 'Tương thích dòng–trạm (research only)', shape: 'line' }]} />}
          {enabled.wind_particles && <SwatchLegend title="Vệt gió (10 m)" items={[{ color: 'var(--fg-subtle)', label: 'Hạt canvas một màu — chỉ hướng, không mã hoá tốc độ', shape: 'line' }]} note="Chỉ quan sát · không kích hoạt cảnh báo" />}
          {bathyBands && <GradientLegend title="Độ sâu (Copernicus SDB)" gradient="linear-gradient(to right, hsl(195 78% 76%), hsl(210 78% 55%), hsl(225 78% 33%))" ticks={['0 m', '0.6 m', '≥ 1.2 m']} note="Chỉ nghiên cứu; không dùng cho hàng hải" />}
          {enabled.bathymetry_slope && <SwatchLegend title="Độ dốc đáy" items={[{ color: '#0ea5e9', label: '< 4°' }, { color: '#facc15', label: '4–9°' }, { color: '#ea580c', label: '9–18°' }, { color: '#991b1b', label: '≥ 18°' }]} columns={2} />}
          {enabled.station_network && <SwatchLegend title="Mạng trạm" items={[{ color: '#64748b', label: 'Kết nối mặt nước tĩnh (không phải hướng dòng)', shape: 'dash' }]} />}
          {enabled.context_buffer && <SwatchLegend title="Phạm vi" items={[{ color: '#38bdf8', label: 'Context 5 km trên mặt nước' }, { color: '#2563eb', label: 'Biên buffer', shape: 'dash' }]} />}
        </div>
      )}
    </section>
  )
})
