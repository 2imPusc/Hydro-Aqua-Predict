import { useMemo, useState } from 'react'
import L from 'leaflet'
import { FlaskConical, Grid2x2, MapPinned, Target } from 'lucide-react'
import { getSuitability, getResearchOverview } from '../../api/research'
import { CiBar } from '../../components/charts'
import { CanvasLayer, ResearchMap, boxOfPoints, squareBounds, type LonLatBox } from '../../components/map/ResearchMap'
import { escapeHtml } from '../../components/map/mapConfig'
import { Chip, GradientLegend, Note, Panel, SectionLabel, Segmented, Skeleton, Toggle } from '../../components/ui'
import type { Theme } from '../../hooks/useTheme'
import { num } from '../../lib/format'
import { sequentialColor, sequentialGradient } from '../../lib/palette'
import type { Suitability, SuitabilityRegion, SuitabilityVariant } from '../../types/research'
import { FindingList, Unavailable, useResearch } from '../shared/research'

const INSET = { top: 70, right: 390, bottom: 20, left: 20 }
const VARIANT_LABEL: Record<SuitabilityVariant, string> = { A_W_SUM: 'Ghaderi (xa bờ)', N1_W_SUM: 'Gần bờ (N1)' }
const REGION_LABEL: Record<SuitabilityRegion, string> = { vn: 'Hải Phòng + Quảng Ninh', hk: 'Hong Kong' }
const LAYER_LABEL: Record<string, string> = {
  SWH: 'Sóng (SWH)', SCS: 'Dòng chảy', SCS_near: 'Dòng chảy (gần bờ)', SST: 'Nhiệt độ mặt', CSCD: 'Chl-a', WS: 'Gió', DEP: 'Độ sâu',
  DfS: 'Khoảng cách bờ', DfS_near: 'Khoảng cách bờ (gần)', DfP: 'Cách cảng', DfPA: 'Cách khu bảo tồn', SSS: 'Độ mặn', SSS_repo: 'Độ mặn (repo)',
  WQ_DO: 'DO', WQ_NH3: 'NH3', WQ_TSS: 'TSS', WQ_pH: 'pH',
}

function cellPopup(props: { id: string; score: number | null; percentile: number | null; layers: Record<string, number | null> }, variant: SuitabilityVariant) {
  const layers = Object.entries(props.layers ?? {}).map(([key, value]) => `<tr><td>${escapeHtml(LAYER_LABEL[key] ?? key)}</td><td style="text-align:right">${value == null ? '—' : value.toFixed(2)}</td></tr>`).join('')
  return `<b>Ô ${escapeHtml(props.id)}</b> · ${escapeHtml(VARIANT_LABEL[variant])}<br/>Điểm <b>${props.score?.toFixed(3) ?? '—'}</b> · phân vị ${props.percentile != null ? Math.round(props.percentile * 100) + ' %' : '—'}<hr/><table style="font-size:11px;width:100%">${layers}</table><div style="margin-top:4px;font-size:10.5px;opacity:.75">Chỉ nghiên cứu · điểm lớp 0–1</div>`
}

function SuitabilityLayers({ data, theme, showFarms, range }: { data: Suitability; theme: Theme; showFarms: boolean; range: [number, number] }) {
  const size = data.cells?.cell_size_deg ?? 0.05
  const variant = data.variant ?? 'N1_W_SUM'
  return (
    <>
      <CanvasLayer deps={[data, theme, range[0], range[1]]} build={renderer => (data.cells?.features ?? []).map(feature => {
        const [lon, lat] = feature.geometry.coordinates as [number, number]
        const score = feature.properties.score
        return L.rectangle(squareBounds(lon, lat, size), {
          renderer, weight: 0.5, color: theme === 'dark' ? '#0a1220' : '#ffffff', opacity: 0.6,
          fillColor: score == null ? '#98a2b3' : sequentialColor((score - range[0]) / (range[1] - range[0] || 1), theme), fillOpacity: 0.78,
        }).bindPopup(cellPopup(feature.properties, variant), { maxWidth: 260 })
      })} />
      {showFarms && (
        <CanvasLayer deps={[data.farms, theme]} build={renderer => L.geoJSON(data.farms, {
          pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { renderer, radius: 5, weight: 2, color: theme === 'dark' ? '#fde68a' : '#7a2e0e', fillColor: theme === 'dark' ? '#0a1220' : '#ffffff', fillOpacity: 0.9 }),
          style: () => ({ renderer, weight: 2, color: theme === 'dark' ? '#fde68a' : '#7a2e0e', fillOpacity: 0.15, fillColor: theme === 'dark' ? '#fde68a' : '#7a2e0e' }),
          onEachFeature: (feature, layer) => {
            const p = feature.properties ?? {}
            layer.bindTooltip(`<b>${escapeHtml(p.name_en ?? p.name ?? p.code ?? 'Vùng nuôi')}</b><br/><span style="opacity:.75">${escapeHtml(p.source ?? '')}</span>`, { sticky: true })
          },
        }).getLayers()} />
      )}
    </>
  )
}

export default function ZoningView({ theme }: { theme: Theme }) {
  const [region, setRegion] = useState<SuitabilityRegion>('vn')
  const [variant, setVariant] = useState<SuitabilityVariant>('N1_W_SUM')
  const [showFarms, setShowFarms] = useState(true)
  const ghaderi = useResearch(signal => getSuitability('A_W_SUM', region, signal), [region], { keepPreviousData: false })
  const nearshore = useResearch(signal => getSuitability('N1_W_SUM', region, signal), [region], { keepPreviousData: false })
  const overview = useResearch(getResearchOverview)
  const direction = overview.data?.directions?.find(item => item.id === 'H3') ?? null
  const poll = variant === 'A_W_SUM' ? ghaderi : nearshore
  const data = poll.data?.status === 'ready' ? poll.data : null

  const box = useMemo<LonLatBox | null>(() => {
    const cells = (data?.cells?.features ?? []).map(f => f.geometry.coordinates as [number, number])
    return boxOfPoints(cells)
  }, [data?.cells])
  /** Colour scale spans both variants of the region, so switching variants compares like with like. */
  const scoreRange = useMemo<[number, number] | null>(() => {
    const scores = [ghaderi.data, nearshore.data].flatMap(d => d?.cells?.features ?? []).map(f => f.properties.score).filter((v): v is number => v != null)
    return scores.length ? [Math.min(...scores), Math.max(...scores)] : null
  }, [ghaderi.data, nearshore.data])
  const layerRange = useMemo(() => {
    const scores = (data?.cells?.features ?? []).map(f => f.properties.score).filter((v): v is number => v != null)
    return scores.length ? [Math.min(...scores), Math.max(...scores)] : null
  }, [data?.cells])

  return (
    <div className="absolute inset-0 overflow-hidden">
      <ResearchMap theme={theme} box={box} inset={INSET} ariaLabel="Bản đồ phù hợp nuôi trồng (nghiên cứu)">
        {data && scoreRange && <SuitabilityLayers data={data} theme={theme} showFarms={showFarms} range={scoreRange} />}
      </ResearchMap>

      <div className="pointer-events-none absolute left-3 top-3 z-[800] flex max-w-[calc(100%-400px)] flex-wrap items-center gap-2">
        <span className="glass pointer-events-auto inline-flex items-center gap-2 rounded-[var(--radius-md)] px-3 py-2 text-[12.5px] font-semibold text-fg">
          <Grid2x2 size={15} className="text-accent" aria-hidden /> {REGION_LABEL[region]} · {VARIANT_LABEL[variant]}
          <Chip size="xs" tone="info" icon={<FlaskConical size={11} />}>Chỉ nghiên cứu</Chip>
        </span>
        {poll.status === 'loading' && <span className="glass rounded-[var(--radius-md)] px-3 py-2 text-[12px] text-fg-muted">Đang tải lớp…</span>}
      </div>

      <aside aria-label="Điều khiển và kết quả phân vùng" className="glass panel-enter scroll-thin absolute bottom-3 right-3 top-3 z-[800] flex w-[360px] flex-col gap-3 overflow-y-auto rounded-[var(--radius-lg)] p-3.5">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[.12em] text-accent">H3 · Phân vùng phù hợp</div>
          <p className="m-0 mt-1 text-[12.5px] leading-snug text-fg-muted">{direction?.headline ?? 'Bản đồ phù hợp nuôi cá giò theo hai bộ tiêu chí.'}</p>
        </div>
        <div className="space-y-2">
          <SectionLabel>Vùng</SectionLabel>
          <Segmented label="Vùng" value={region} onChange={setRegion} options={[{ value: 'vn', label: 'Việt Nam' }, { value: 'hk', label: 'Hong Kong' }]} />
          <SectionLabel>Bộ tiêu chí</SectionLabel>
          <Segmented label="Bộ tiêu chí" value={variant} onChange={setVariant} options={[{ value: 'A_W_SUM', label: 'Ghaderi (xa bờ)' }, { value: 'N1_W_SUM', label: 'Gần bờ' }]} />
          <Toggle checked={showFarms} onChange={setShowFarms} label="Vùng nuôi kiểm chứng" disabled={!data?.farms_available}
            description={region === 'hk' ? 'AFCD fish culture zones (CSDI) · đa giác' : 'OSM aquaculture · tâm điểm (không phải ranh giới chính thức)'} />
        </div>

        <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3">
          <div className="flex items-center gap-2"><Target size={14} className="text-accent" aria-hidden /><span className="text-[12.5px] font-semibold">Kiểm chứng (AUC)</span></div>
          {[{ id: 'A_W_SUM' as const, poll: ghaderi }, { id: 'N1_W_SUM' as const, poll: nearshore }].map(item => {
            const d = item.poll.data
            return (
              <div key={item.id} className={`mt-2 rounded-[var(--radius-sm)] px-2 py-1.5 ${item.id === variant ? 'bg-accent-soft' : ''}`}>
                <div className="flex items-baseline justify-between text-[12px]">
                  <span className="font-semibold text-fg">{VARIANT_LABEL[item.id]}</span>
                  <span className="tabular text-fg">{d?.auc != null ? <>AUC <b>{num(d.auc, 3)}</b>{d.auc_ci ? <span className="text-fg-subtle"> [{num(d.auc_ci[0], 3)}; {num(d.auc_ci[1], 3)}]</span> : null}</> : d ? <span className="text-fg-subtle">không có AUC</span> : '…'}</span>
                </div>
                {d?.auc != null && <CiBar value={d.auc} ci={d.auc_ci ?? null} reference={{ value: 0.5, label: 'ngẫu nhiên' }} ariaLabel={`AUC ${VARIANT_LABEL[item.id]} ${d.auc}`} />}
              </div>
            )
          })}
          {region === 'vn' && <p className="m-0 mt-2 text-[11.5px] text-fg-subtle">Việt Nam chưa có ranh giới vùng nuôi chính thức có tọa độ: không tính được AUC độc lập (RL-11).</p>}
        </div>

        <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3">
          <GradientLegend title="Điểm phù hợp (thang chung cho cả hai bộ tiêu chí của vùng)" gradient={sequentialGradient(theme)}
            ticks={scoreRange ? [0, 0.25, 0.5, 0.75, 1].map(t => num(scoreRange[0] + t * (scoreRange[1] - scoreRange[0]), 2)) : ['—']}
            note={layerRange ? `Bộ đang xem: ${num(layerRange[0], 2)}–${num(layerRange[1], 2)} · ô ${data?.cells?.cell_size_deg ? `${(data.cells.cell_size_deg * 60).toFixed(0)}′` : ''} · ${data?.cells?.features.length ?? 0} ô · bấm ô để xem điểm từng lớp` : undefined} />
          <div className="mt-2 flex items-center gap-2 text-[11px] text-fg-muted">
            <svg width="14" height="14" aria-hidden><circle cx="7" cy="7" r="4.5" fill="var(--surface)" stroke={theme === 'dark' ? '#fde68a' : '#7a2e0e'} strokeWidth="2" /></svg>
            Vùng nuôi kiểm chứng {region === 'hk' ? '(đa giác AFCD)' : '(điểm OSM)'}
          </div>
        </div>

        {!data && poll.data && <Unavailable compact envelope={poll.data} onRetry={poll.refresh} />}
        {!poll.data && poll.error && <Unavailable compact error={poll.error} onRetry={poll.refresh} />}
        {!poll.data && !poll.error && <Skeleton className="h-20" />}
        {data && (
          <div>
            <SectionLabel icon={<MapPinned size={12} />}>Ghi chú ({VARIANT_LABEL[variant]})</SectionLabel>
            <FindingList items={data.notes} />
            <p className="m-0 mt-2 text-[10.5px] text-fg-subtle">Run nguồn <span className="font-mono">{data.source_run}</span> · export {data.export_version} · điểm = tổng có trọng số các lớp 0–1.</p>
          </div>
        )}
        <Note tone="info">Bản đồ nháp nghiên cứu: xếp hạng rất nhạy với lựa chọn tiêu chí; không dùng để cấp phép hay khuyến cáo vị trí nuôi.</Note>
      </aside>
    </div>
  )
}
