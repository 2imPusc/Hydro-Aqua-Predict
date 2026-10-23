import { useCallback, useEffect, useMemo, useState } from 'react'
import L from 'leaflet'
import { FlaskConical, Target } from 'lucide-react'
import { getSuitability, getResearchOverview } from '../../api/research'
import { CiBar } from '../../components/charts'
import { useMap } from 'react-leaflet'
import { CanvasLayer, ResearchMap, boxOfPoints, type LonLatBox } from '../../components/map/ResearchMap'
import { SmoothCellField, type FieldCell } from '../../components/map/overlays/SmoothCellField'
import { escapeHtml } from '../../components/map/mapConfig'
import { Chip, Disclosure, GradientLegend, Segmented, Skeleton, Toggle, type VerdictStatus } from '../../components/ui'
import type { Theme } from '../../hooks/useTheme'
import { num } from '../../lib/format'
import { sequentialColor, sequentialGradient } from '../../lib/palette'
import type { Suitability, SuitabilityRegion, SuitabilityVariant } from '../../types/research'
import { FindingList, RefChips, Unavailable, useResearch } from '../shared/research'
import { MapPanel, MapVerdict, mapInset, mapPanelStyle, useNarrow } from '../shared/MapPanel'

const PANEL_W = 360
/** Tablets (768–1024 px): a narrower side panel so the map keeps most of the width. */
const PANEL_W_TABLET = 268
const TABLET = '(min-width: 768px) and (max-width: 1024px)'
function useTablet(): boolean {
  const [tablet, setTablet] = useState(() => typeof window !== 'undefined' && window.matchMedia(TABLET).matches)
  useEffect(() => {
    const query = window.matchMedia(TABLET)
    const onChange = () => setTablet(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return tablet
}

const hexRgb = (hex: string): [number, number, number] => {
  const value = parseInt(hex.slice(1), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}
/** "0,083° (~9 km)" for the resolution note. */
export const cellSizeLabel = (deg: number) => `${deg.toFixed(3).replace('.', ',')}° (~${Math.round(deg * 111)} km)`
const VARIANT_LABEL: Record<SuitabilityVariant, string> = { A_W_SUM: 'Ghaderi (xa bờ)', N1_W_SUM: 'Gần bờ (N1)' }
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
  const map = useMap()
  const size = data.cells?.cell_size_deg ?? 0.05
  const variant = data.variant ?? 'N1_W_SUM'
  const features = useMemo(() => data.cells?.features ?? [], [data.cells])
  const cells = useMemo<FieldCell[]>(() => features.map(feature => {
    const [lon, lat] = feature.geometry.coordinates as [number, number]
    return { lon, lat, value: feature.properties.score }
  }), [features])
  const color = useCallback((score: number) => hexRgb(sequentialColor((score - range[0]) / (range[1] - range[0] || 1), theme)), [range, theme])
  const onCellClick = useCallback((index: number, latlng: L.LatLng) => {
    const feature = features[index]
    if (feature) L.popup({ maxWidth: 260 }).setLatLng(latlng).setContent(cellPopup(feature.properties, variant)).openOn(map)
  }, [features, map, variant])
  return (
    <>
      <SmoothCellField cells={cells} cellSizeDeg={size} color={color} onCellClick={onCellClick}
        dataKey={`${data.region}-${data.variant}-${data.export_version}-${theme}-${range[0]}-${range[1]}`} />
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

/** AUC verdict: does the score rank real farms above random cells? Never typed in: AUC + CI come from the export. */
function aucStatus(data: Suitability | null): VerdictStatus {
  if (!data) return { tone: 'neutral', label: 'Đang tải' }
  if (data.auc == null) return { tone: 'warn', label: 'Chưa kiểm chứng được' }
  const low = data.auc_ci?.[0] ?? data.auc
  if (low > 0.5) return { tone: 'ok', label: 'Tốt hơn ngẫu nhiên' }
  return { tone: 'warn', label: 'Chưa chắc hơn ngẫu nhiên' }
}

export default function ZoningView({ theme }: { theme: Theme }) {
  const [region, setRegion] = useState<SuitabilityRegion>('vn')
  const [variant, setVariant] = useState<SuitabilityVariant>('N1_W_SUM')
  const [showFarms, setShowFarms] = useState(true)
  const narrow = useNarrow()
  const tablet = useTablet()
  const panelWidth = tablet ? PANEL_W_TABLET : PANEL_W
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

  const status = aucStatus(data)
  const other = variant === 'A_W_SUM' ? nearshore.data : ghaderi.data
  const answer = data?.auc != null
    ? `${VARIANT_LABEL[variant]}: AUC ${num(data.auc, 2)}${other?.auc != null ? ` · bộ kia ${num(other.auc, 2)}` : ''}`
    : region === 'vn' ? 'Việt Nam chưa có ranh giới vùng nuôi chính thức có toạ độ, nên chưa tính được AUC.' : undefined

  const header = (
    <MapVerdict code="H3" question="Bộ tiêu chí có chỉ đúng vùng nuôi thật không?"
      value={data?.auc != null ? num(data.auc, 2) : '—'} unit={data?.auc != null ? 'AUC' : undefined} status={status} answer={answer}
      chips={<Chip size="xs" tone="info" icon={<FlaskConical size={11} />}>Chỉ nghiên cứu</Chip>} />
  )

  return (
    <div className="map-with-panel absolute inset-0 overflow-hidden" style={mapPanelStyle(narrow, panelWidth)}>
      <ResearchMap theme={theme} box={box} inset={mapInset(narrow, panelWidth)} ariaLabel="Bản đồ phù hợp nuôi trồng (nghiên cứu)">
        {data && scoreRange && <SuitabilityLayers data={data} theme={theme} showFarms={showFarms} range={scoreRange} />}
      </ResearchMap>
      {poll.status === 'loading' && <span className="glass absolute left-3 top-3 z-[800] rounded-[var(--radius-md)] px-3 py-1.5 text-[12px] text-fg-muted">Đang tải lớp…</span>}

      <MapPanel label="Điều khiển và kết quả phân vùng" header={header} width={panelWidth}>
        <div className="grid gap-2">
          <Segmented label="Vùng" value={region} onChange={setRegion} options={[{ value: 'vn', label: 'Hải Phòng + QN' }, { value: 'hk', label: 'Hong Kong' }]} />
          <Segmented label="Bộ tiêu chí" value={variant} onChange={setVariant} options={[{ value: 'N1_W_SUM', label: 'Gần bờ' }, { value: 'A_W_SUM', label: 'Ghaderi (xa bờ)' }]} />
          <Toggle checked={showFarms} onChange={setShowFarms} label="Vùng nuôi thật (để kiểm chứng)" disabled={!data?.farms_available}
            description={region === 'hk' ? 'AFCD · đa giác' : 'OSM · tâm điểm, không phải ranh giới chính thức'} />
        </div>

        <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3">
          <GradientLegend title="Điểm phù hợp (thấp → cao)" gradient={sequentialGradient(theme)}
            ticks={scoreRange ? [0, 0.5, 1].map(t => num(scoreRange[0] + t * (scoreRange[1] - scoreRange[0]), 2)) : ['—']}
            note={<>Cùng thang cho cả hai bộ tiêu chí. Bấm vào vùng màu để xem điểm từng lớp.<br />
              Lưới mô hình {data?.cells?.cell_size_deg ? cellSizeLabel(data.cells.cell_size_deg) : '—'}: tô mượt giữa tâm ô, không thêm chi tiết.
              Biên theo phạm vi ô lưới, không theo đường bờ, nên có chỗ tràn lên đất.</>} />
          <div className="mt-2 flex items-center gap-2 text-[12px] text-fg-muted">
            <svg width="14" height="14" aria-hidden><circle cx="7" cy="7" r="4.5" fill="var(--surface)" stroke={theme === 'dark' ? '#fde68a' : '#7a2e0e'} strokeWidth="2" /></svg>
            Vùng nuôi thật {region === 'hk' ? '(đa giác AFCD)' : '(điểm OSM)'}
          </div>
        </div>

        {!data && poll.data && <Unavailable compact envelope={poll.data} onRetry={poll.refresh} />}
        {!poll.data && poll.error && <Unavailable compact error={poll.error} onRetry={poll.refresh} />}
        {!poll.data && !poll.error && <Skeleton className="h-20" />}

        <Disclosure summary="So sánh AUC hai bộ tiêu chí">
          {[{ id: 'A_W_SUM' as const, poll: ghaderi }, { id: 'N1_W_SUM' as const, poll: nearshore }].map(item => {
            const d = item.poll.data
            return (
              <div key={item.id} className={`rounded-[var(--radius-sm)] px-2 py-1.5 ${item.id === variant ? 'bg-accent-soft' : ''}`}>
                <div className="flex items-baseline justify-between text-[12px]">
                  <span className="font-semibold text-fg">{VARIANT_LABEL[item.id]}</span>
                  <span className="tabular text-fg">{d?.auc != null ? <>AUC <b>{num(d.auc, 3)}</b>{d.auc_ci ? <span className="text-fg-subtle"> [{num(d.auc_ci[0], 3)}; {num(d.auc_ci[1], 3)}]</span> : null}</> : d ? <span className="text-fg-subtle">không có AUC</span> : '…'}</span>
                </div>
                {d?.auc != null && <CiBar value={d.auc} ci={d.auc_ci ?? null} reference={{ value: 0.5, label: 'ngẫu nhiên' }} ariaLabel={`AUC ${VARIANT_LABEL[item.id]} ${d.auc}`} />}
              </div>
            )
          })}
          <p className="m-0">AUC = xác suất một vùng nuôi thật được chấm điểm cao hơn một ô ngẫu nhiên (0,5 = đoán mò). {region === 'vn' && <RefChips refs={['RL-11']} />}</p>
        </Disclosure>
        {data && (
          <Disclosure summary="Ghi chú & giới hạn" hint={`(${data.notes?.length ?? 0})`}>
            {direction?.headline && <p className="m-0 text-fg">{direction.headline}</p>}
            <FindingList items={data.notes} />
            <p className="m-0">Bản đồ nháp nghiên cứu: xếp hạng rất nhạy với lựa chọn tiêu chí; không dùng để cấp phép hay khuyến cáo vị trí nuôi.</p>
            <p className="m-0 text-[11.5px] text-fg-subtle">
              <Target size={11} className="mr-1 inline align-[-1px]" aria-hidden />
              Bộ đang xem {layerRange ? `${num(layerRange[0], 2)}–${num(layerRange[1], 2)}` : '—'} · ô {data.cells?.cell_size_deg ? `${(data.cells.cell_size_deg * 60).toFixed(0)}′` : '—'} · {data.cells?.features.length ?? 0} ô · lần chạy <span className="font-mono">{data.source_run}</span> · bản xuất {data.export_version}
            </p>
          </Disclosure>
        )}
      </MapPanel>
    </div>
  )
}
