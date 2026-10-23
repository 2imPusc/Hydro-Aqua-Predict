import { useMemo, useState } from 'react'
import L from 'leaflet'
import { Anchor, TriangleAlert } from 'lucide-react'
import { getReliabilityVn } from '../../api/research'
import { CanvasLayer, ResearchMap, boxOfPoints, metresToDeg, type LonLatBox } from '../../components/map/ResearchMap'
import { escapeHtml } from '../../components/map/mapConfig'
import { Chip, Disclosure, Note, SectionLabel, Segmented, Skeleton, StateChip, type VerdictStatus } from '../../components/ui'
import { MapPanel, MapVerdict, mapInset, mapPanelStyle, useNarrow } from '../shared/MapPanel'
import type { Theme } from '../../hooks/useTheme'
import { num, variableLabel } from '../../lib/format'
import { regimeColor, regimeLabel, REGIME_SHORT } from '../../lib/palette'
import type { ReliabilityVn, VnPassCount } from '../../types/research'
import { FindingList, RefChips, Unavailable, useResearch } from '../shared/research'
import { RegimeLegend, regimeLine, regimeTooltip, stationMarker } from './common'

const PANEL_W = 380
const REGION_LABEL: Record<string, string> = { haiphong: 'Hải Phòng', quangninh: 'Quảng Ninh' }
const PROTOCOL_LABEL: Record<string, string> = { tolerance_dayblock_bootstrap: 'Dung sai (bootstrap theo ngày)', p1_conformal_pair_gate: 'P1 · gate cặp conformal' }
const RELATION_LABEL: Record<string, string> = { same_regime: 'Cùng chế độ', different_regime: 'Khác chế độ', all: 'Tất cả' }

function VnLayers({ data, theme }: { data: ReliabilityVn; theme: Theme }) {
  const step = data.layer?.grid_step_m ?? 1000
  const nb1 = data.nb1_regime
  return (
    <>
      <CanvasLayer deps={[data.layer, theme]} build={renderer => (data.layer?.features ?? []).map(cell => {
        const [lon, lat] = cell.geometry.coordinates as [number, number]
        const { dLat, dLon } = metresToDeg(step, lat)
        const p = cell.properties
        return L.rectangle([[lat - dLat / 2, lon - dLon / 2], [lat + dLat / 2, lon + dLon / 2]], { renderer, stroke: false, fillColor: regimeColor(p.regime_class, theme), fillOpacity: 0.32 })
          .bindTooltip(regimeTooltip(`Ô ${Math.round(step)} m`, [regimeLine(p.regime_class), `Trạm quan sát gần nhất: ${escapeHtml(p.nearest_obs_station)} (${num(p.nearest_obs_km, 1)} km, ${num(p.nearest_obs_wet_median_sal, 1)} psu)`, `IDW: ${num(p.idw_obs_wet_median_sal, 1)} psu → ${escapeHtml(regimeLabel(p.idw_obs_regime_class))}`]), { sticky: true })
      })} />
      <CanvasLayer deps={[nb1, theme]} build={renderer => nb1 ? nb1.nearest_observed_stations.map(st => {
        const feature = data.stations?.features.find(f => f.properties.station === st.station && f.properties.region === st.region)
        if (!feature) return null
        const [lon, lat] = feature.geometry.coordinates as [number, number]
        return L.polyline([[nb1.nb1_lat, nb1.nb1_lon], [lat, lon]], { renderer, color: theme === 'dark' ? '#e6edf5' : '#0f1b2b', weight: 1.2, opacity: 0.55, dashArray: '4 4' })
      }).filter((l): l is L.Polyline => !!l) : []} />
      <CanvasLayer deps={[data.stations, theme]} build={renderer => (data.stations?.features ?? []).map(feature => {
        const [lon, lat] = feature.geometry.coordinates as [number, number]
        const p = feature.properties
        const model = p.salinity_source !== 'observed'
        return stationMarker(lat, lon, p.regime_class, theme, renderer, { radius: p.station === 'NB1' ? 9 : 5.5, modelDerived: model })
          .bindTooltip(regimeTooltip(`${p.station} · ${REGION_LABEL[p.region] ?? p.region}${p.station === 'NB1' ? ' · trạm cảm biến sống' : ''}`, [regimeLine(p.regime_class), `Độ mặn mùa ướt ${num(p.wet_median_sal, 1)} · khô ${num(p.dry_median_sal, 1)} psu`, model ? '<b>Độ mặn từ mô hình lưới (không quan sát)</b>' : 'Độ mặn quan sát', p.coordinate_suspect ? 'Toạ độ nghi ngờ' : null]))
      })} />
      {nb1 && <CanvasLayer deps={[nb1.nb1_lat, nb1.nb1_lon]} build={() => [L.marker([nb1.nb1_lat, nb1.nb1_lon], {
        icon: L.divIcon({ className: 'nb1-label', html: '<span>NB1 · cảm biến</span>', iconSize: [92, 22], iconAnchor: [-10, 11] }), keyboard: false, interactive: false,
      })]} />}
    </>
  )
}

function PassCounts({ rows }: { rows: VnPassCount[] }) {
  const regions = [...new Set(rows.map(r => r.region))]
  const [region, setRegion] = useState(regions[0] ?? 'haiphong')
  const protocols = [...new Set(rows.filter(r => r.region === region).map(r => r.protocol))]
  const [protocol, setProtocol] = useState(protocols[0] ?? '')
  const [coverage, setCoverage] = useState('0.8')
  const activeProtocol = protocols.includes(protocol) ? protocol : protocols[0]
  const subset = rows.filter(r => r.region === region && r.protocol === activeProtocol && String(r.coverage) === coverage)
  const relations = [...new Set(subset.map(r => r.regime_relation))].sort((a, b) => (a === 'same_regime' ? -1 : b === 'same_regime' ? 1 : a.localeCompare(b)))
  const variables = [...new Set(subset.map(r => r.variable))].sort()
  return (
    <div className="space-y-2">
      <Segmented size="xs" label="Vùng" value={region} onChange={setRegion} options={regions.map(r => ({ value: r, label: REGION_LABEL[r] ?? r }))} />
      <Segmented size="xs" label="Giao thức" value={activeProtocol} onChange={setProtocol} options={protocols.map(p => ({ value: p, label: p.startsWith('tolerance') ? 'Dung sai' : 'P1 conformal' }))} />
      <Segmented size="xs" label="Mức độ phủ" value={coverage} onChange={setCoverage} options={['0.8', '0.9', '0.95'].map(c => ({ value: c, label: `${Math.round(Number(c) * 100)} %` }))} />
      <div className="scroll-thin overflow-x-auto rounded-[var(--radius-sm)] border border-line">
        <table className="data-table" aria-label={`Số ô đạt: ${REGION_LABEL[region]}, ${PROTOCOL_LABEL[activeProtocol] ?? activeProtocol}`}>
          <thead><tr><th>Biến</th>{relations.map(rel => <th key={rel} className="num">{RELATION_LABEL[rel] ?? rel}</th>)}</tr></thead>
          <tbody>{variables.map(variable => (
            <tr key={variable}>
              <td>{variableLabel(variable)}{subset.some(r => r.variable === variable && r.model_derived) && <span className="ml-1 text-warn" title="Biến dựa trên độ mặn/nhiệt độ mô hình (HP)">*</span>}</td>
              {relations.map(rel => {
                const row = subset.find(r => r.variable === variable && r.regime_relation === rel)
                return (
                  <td key={rel} className="num" title={row ? `đạt chặt ${row.n_pass_strict}/${row.n_cells}${row.n_insufficient_strict != null ? ` · thiếu dữ liệu ${row.n_insufficient_strict}` : ''}${row.n_relaxed_diagnostic_pass != null ? ` · chẩn đoán nới ${row.n_relaxed_diagnostic_pass}` : ''}` : undefined}>
                    {row ? <span className={row.n_pass_strict > 0 ? 'font-semibold text-ok' : 'text-fg-muted'}>{row.n_pass_strict}/{row.n_cells}</span> : '—'}
                  </td>
                )
              })}
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="m-0 text-[10.5px] text-fg-subtle">Số ô (khoảng cách × cặp) đạt gate chặt / tổng ô. * biến dùng giá trị mô hình (HP). Rê chuột để xem ô thiếu dữ liệu.</p>
    </div>
  )
}

function Nb1Card({ data, theme }: { data: ReliabilityVn; theme: Theme }) {
  const nb1 = data.nb1_regime
  if (!nb1) return <Note tone="warn">Bản export không có thông tin chế độ mặn của NB1.</Note>
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3">
      <div className="flex items-center gap-2"><Anchor size={14} className="text-accent" aria-hidden /><span className="text-[12.5px] font-semibold">NB1 · Cát Bà (trạm sống duy nhất)</span></div>
      <div className="mt-2 grid grid-cols-2 gap-1.5 text-[11.5px]">
        <div className="rounded-[var(--radius-sm)] bg-surface-2 px-2 py-1.5">
          <div className="text-fg-subtle">Theo mô hình (HP)</div>
          <div className="mt-0.5 flex items-center gap-1.5 font-semibold"><span className="size-2.5 rounded-full" style={{ background: regimeColor(nb1.nb1_model_derived_class, theme) }} aria-hidden />{REGIME_SHORT[nb1.nb1_model_derived_class]} · {num(nb1.nb1_model_derived_wet_median_sal, 1)} psu</div>
        </div>
        <div className="rounded-[var(--radius-sm)] bg-surface-2 px-2 py-1.5">
          <div className="text-fg-subtle">Theo trạm QN quan sát gần nhất</div>
          <div className="mt-0.5 flex items-center gap-1.5 font-semibold"><span className="size-2.5 rounded-full" style={{ background: regimeColor(nb1.nb1_observed_regime_class_by_nearest, theme) }} aria-hidden />{REGIME_SHORT[nb1.nb1_observed_regime_class_by_nearest]}</div>
        </div>
      </div>
      <SectionLabel>Trạm quan sát cùng chế độ gần NB1 (đường đứt trên bản đồ)</SectionLabel>
      <ul className="m-0 grid list-none grid-cols-2 gap-x-3 gap-y-0.5 p-0 text-[11.5px] tabular">
        {nb1.nearest_observed_stations.map(st => (
          <li key={st.station} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: regimeColor(st.regime_class, theme) }} aria-hidden /><span className="font-semibold">{st.station}</span><span className="ml-auto text-fg-subtle">{num(st.distance_km, 1)} km · {num(st.wet_median_sal, 1)}</span></li>
        ))}
      </ul>
      <p className="m-0 mt-2 text-[11px] text-fg-subtle">{nb1.qn_observed_same_regime_as_nb1_nearest} trạm QN quan sát cùng chế độ; trạm HP cùng chế độ mô hình: {nb1.hp_stations_sharing_model_regime.length}. Phạm vi: <span className="font-mono">{nb1.scope}</span>, không dùng cho runtime/cảnh báo.</p>
    </div>
  )
}

export function VnTab({ theme }: { theme: Theme }) {
  const poll = useResearch(getReliabilityVn)
  const narrow = useNarrow()
  const data = poll.data?.status === 'ready' ? poll.data : null
  // Fit to the regime layer + stations with trusted coordinates (a few QN points are flagged coordinate_suspect).
  const box = useMemo<LonLatBox | null>(() => boxOfPoints([
    ...(data?.layer?.features ?? []).map(f => f.geometry.coordinates as [number, number]),
    ...(data?.stations?.features ?? []).filter(f => !f.properties.coordinate_suspect).map(f => f.geometry.coordinates as [number, number]),
  ]), [data?.layer, data?.stations])
  const classes = useMemo(() => [...new Set([...(data?.layer?.features ?? []), ...(data?.stations?.features ?? [])].map(f => f.properties.regime_class))], [data])

  const nb1 = data?.nb1_regime
  const nearest = nb1?.nearest_observed_stations ?? []
  const closest = nearest.length ? Math.min(...nearest.map(st => st.distance_km ?? Infinity)) : null
  const status: VerdictStatus = !data ? { tone: 'neutral', label: poll.error || poll.data ? 'Không có dữ liệu' : 'Đang tải' }
    : !nb1 ? { tone: 'warn', label: 'Thiếu thông tin NB1' }
    : nb1.nb1_model_derived_class === nb1.nb1_observed_regime_class_by_nearest ? { tone: 'ok', label: 'Mô hình và quan trắc khớp' }
    : { tone: 'warn', label: 'Mô hình và quan trắc lệch' }
  const header = (
    <MapVerdict code="H4" question="NB1 được mượn giá trị từ trạm nào?"
      value={nb1 ? REGIME_SHORT[nb1.nb1_observed_regime_class_by_nearest] : '—'} unit={nb1 ? 'chế độ mặn' : undefined} status={status}
      answer={nb1 ? `${nb1.qn_observed_same_regime_as_nb1_nearest} trạm QN quan sát cùng chế độ${closest != null && Number.isFinite(closest) ? `, gần nhất ${num(closest, 1)} km` : ''}.` : undefined}
      chips={<>
        <StateChip size="xs" state="research_only" />
        <Chip size="xs" tone="warn" icon={<TriangleAlert size={11} />} title="Độ mặn Hải Phòng là giá trị mô hình dạng lưới, không phải quan trắc (RL-25)">Độ mặn HP là mô hình</Chip>
      </>} />
  )
  return (
    <div className="map-with-panel absolute inset-0 overflow-hidden" style={mapPanelStyle(narrow, PANEL_W)}>
      <ResearchMap theme={theme} box={box} inset={mapInset(narrow, PANEL_W)} ariaLabel="Bản đồ chế độ mặn Hải Phòng – Quảng Ninh (nghiên cứu)">
        {data && <VnLayers data={data} theme={theme} />}
      </ResearchMap>
      <MapPanel label="Độ tin cậy không gian ở Việt Nam" header={header} width={PANEL_W}>
        {!poll.data && !poll.error && <Skeleton className="h-40" />}
        {!data && (poll.data || poll.error) && <Unavailable compact envelope={poll.data} error={poll.error} onRetry={poll.refresh} title="Lớp chế độ mặn VN chưa có" />}
        {data && (
          <>
            <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3">
              <RegimeLegend theme={theme} classes={classes} title="Chế độ mặn (mùa mưa)" />
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-fg-muted">
                <span className="inline-flex items-center gap-1.5"><svg width="12" height="12" aria-hidden><circle cx="6" cy="6" r="4.5" fill="var(--fg-muted)" stroke="var(--surface)" strokeWidth="1.5" /></svg>Trạm QN (quan sát)</span>
                <span className="inline-flex items-center gap-1.5"><svg width="12" height="12" aria-hidden><circle cx="6" cy="6" r="4.5" fill="var(--surface)" stroke="var(--fg-muted)" strokeWidth="1.5" strokeDasharray="2 2" /></svg>Trạm HP (mô hình)</span>
              </div>
            </div>
            <Disclosure summary="Vì sao độ mặn HP chỉ để tham khảo?">
              <p className="m-0">Độ mặn Hải Phòng là giá trị mô hình dạng lưới, không phải quan trắc. Lớp chế độ chỉ dựa trên trạm Quảng Ninh quan sát; trạm HP (viền đứt) chỉ để tham khảo. <RefChips refs={['RL-25']} /></p>
              <p className="m-0">Ô {Math.round((data.layer?.grid_step_m ?? 1000) / 1000)} km có trạm quan sát trong 10 km: {data.layer?.features.length ?? 0}; bỏ {data.layer?.n_unassigned_omitted ?? 0} ô không có trạm (không gán).</p>
            </Disclosure>
            <Disclosure summary="NB1 và các trạm cùng chế độ" hint={nb1 ? `(${nearest.length} gần nhất)` : undefined}>
              <Nb1Card data={data} theme={theme} />
            </Disclosure>
            <Disclosure summary="Số ô đạt theo biến (A6)">
              <PassCounts rows={data.pass_counts ?? []} />
            </Disclosure>
            <Disclosure summary="Ghi chú" hint={`(${(data.notes?.length ?? 0) + 1})`}>
              <p className="m-0"><b>Vùng HSI lịch sử</b> (bản đồ giám sát) <Chip size="xs" tone="neutral">chưa kiểm chứng</Chip>: chỉ số legacy dựa trên độ mặn mô hình ở HP, không phải lớp tin cậy.</p>
              <FindingList items={data.notes} />
              <p className="m-0 text-[11.5px] text-fg-subtle">Lần chạy <span className="font-mono">{data.source_run}</span> · bản xuất {data.export_version}</p>
            </Disclosure>
          </>
        )}
      </MapPanel>
    </div>
  )
}
