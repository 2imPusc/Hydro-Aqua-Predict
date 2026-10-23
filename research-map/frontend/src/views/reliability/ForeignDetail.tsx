import { useEffect, useMemo, useState, type ReactNode } from 'react'
import L from 'leaflet'
import { ArrowLeft, Ruler } from 'lucide-react'
import { getForeignDetail, getForeignIndex } from '../../api/research'
import { RELIABILITY_HASH } from '../../app/routes'
import { CanvasLayer, ResearchMap, boxOfPoints, type LonLatBox } from '../../components/map/ResearchMap'
import { escapeHtml } from '../../components/map/mapConfig'
import { Chip, Disclosure, GradientLegend, SectionLabel, Segmented, Select, Skeleton, type VerdictStatus } from '../../components/ui'
import { MapPanel, MapVerdict, mapInset, mapPanelStyle, useNarrow } from '../shared/MapPanel'
import type { Theme } from '../../hooks/useTheme'
import { gateLabel, num, pct, radiusText, regimeRelationLabel, scaleLabel, splitRefs, stopLabel, transferLabel, variableLabel } from '../../lib/format'
import { shareColor, shareGradient } from '../../lib/palette'
import type { ForeignDetail as Detail, ReliabilityPair, ReliabilityRadius } from '../../types/research'
import { FindingList, RefChips, Unavailable, useResearch } from '../shared/research'
import { RegimeLegend, regimeLine, regimeTooltip, stationMarker } from './common'
import { RedistributableBadge } from './ForeignOverview'

const PANEL_W = 400
type RegimeFilter = 'all' | 'same' | 'different'
type DistanceFilter = '10' | '20' | '30' | 'all'
const DISTANCE_OPTIONS: { value: DistanceFilter; label: string }[] = [
  { value: '10', label: '≤ 10 km' }, { value: '20', label: '≤ 20 km' }, { value: '30', label: '≤ 30 km' }, { value: 'all', label: 'Tất cả' },
]
const passes = (p: ReliabilityPair) => (p.share ?? 0) >= 0.8

const gateText = (gate: string | null) => (gate === 'pass' ? 'đạt' : gate === 'fail' ? 'trượt' : '—')

function pairTooltip(pair: ReliabilityPair, habitat: boolean) {
  const relation = habitat ? (pair.same_habitat == null ? null : pair.same_habitat ? 'cùng môi trường sống' : 'khác môi trường sống') : (pair.same_regime == null ? null : pair.same_regime ? 'cùng chế độ mặn' : 'khác chế độ mặn')
  return regimeTooltip(`${pair.anchor} → ${pair.target}`, [
    `${num(pair.km, 1)} km${relation ? ` · ${relation}` : ''}${pair.dsal != null ? ` · Δ mặn ${num(pair.dsal, 1)}` : ''}`,
    `Tỷ lệ trong dung sai: <b>${pct(pair.share, 1)}</b>${pair.ci_low != null ? ` (CI dưới ${pct(pair.ci_low, 1)})` : ''}`,
    pair.gate80 || pair.gate90 || pair.gate95 ? `Gate 80/90/95: ${gateText(pair.gate80)} / ${gateText(pair.gate90)} / ${gateText(pair.gate95)}` : 'Không có gate theo cặp',
    pair.n_days != null ? `${pair.n_days} ngày ghép cặp` : null,
  ])
}

function PairLayers({ detail, pairs, theme, habitat }: { detail: Detail; pairs: ReliabilityPair[]; theme: Theme; habitat: boolean }) {
  return (
    <>
      {/* Failing pairs first, thin and faint; pairs passing the 80 % gate drawn on top. */}
      <CanvasLayer deps={[pairs, theme]} build={renderer => [...pairs]
        .filter(p => p.lat1 != null && p.lon1 != null && p.lat2 != null && p.lon2 != null)
        .sort((a, b) => Number(passes(a)) - Number(passes(b)) || (a.share ?? 0) - (b.share ?? 0))
        .map(p => L.polyline([[p.lat1!, p.lon1!], [p.lat2!, p.lon2!]], {
          renderer, color: shareColor(p.share, theme), weight: passes(p) ? 3 : 1.25, opacity: passes(p) ? 0.9 : 0.4,
          dashArray: (habitat ? p.same_habitat === false : p.same_regime === false) ? '5 4' : undefined,
        }).bindTooltip(pairTooltip(p, habitat), { sticky: true }))} />
      <CanvasLayer deps={[detail.stations, theme]} build={renderer => (detail.stations?.features ?? []).map(feature => {
        const [lon, lat] = feature.geometry.coordinates as [number, number]
        const p = feature.properties
        return stationMarker(lat, lon, p.regime_class, theme, renderer)
          .bindTooltip(regimeTooltip(`${p.station}${p.name ? ` · ${escapeHtml(p.name)}` : ''}`, [regimeLine(p.regime_class), `Độ mặn mùa ướt (trung vị): ${num(p.wet_sal_median, 1)} psu`, p.habitat ? `Môi trường sống: ${escapeHtml(p.habitat)}` : null, p.group ? `Khu: ${escapeHtml(p.group)}` : null]))
      })} />
    </>
  )
}

/** Radius pivot: rows regime × transfer (× group), columns gate 80/90/95. */
function RadiusTable({ rows }: { rows: ReliabilityRadius[] }) {
  const groups = [...new Set(rows.map(r => r.group ?? ''))]
  const [group, setGroup] = useState(groups.includes('pooled') ? 'pooled' : groups[0] ?? '')
  const scales = [...new Set(rows.map(r => r.scale))]
  const [scale, setScale] = useState(scales[0] ?? '')
  const subset = rows.filter(r => (r.group ?? '') === (groups.includes(group) ? group : groups[0] ?? '') && r.scale === (scales.includes(scale) ? scale : scales[0]))
  const keys = [...new Set(subset.map(r => `${r.regime}|${r.transfer}`))].sort((a, b) => {
    const rank = (k: string) => ['same', 'all', 'different'].indexOf(k.split('|')[0]) * 2 + (k.endsWith('raw') ? 0 : 1)
    return rank(a) - rank(b)
  })
  const gates = [...new Set(subset.map(r => r.gate))].sort()
  if (!rows.length) return <p className="m-0 text-[12px] text-fg-subtle">Bộ này không có bảng bán kính cho biến đã chọn.</p>
  return (
    <div className="space-y-2">
      {groups.length > 1 && <Select label="Khu (NERRS)" value={group} onChange={setGroup} options={groups.map(g => ({ value: g, label: g === 'pooled' ? 'Gộp tất cả khu' : g }))} />}
      {scales.length > 1 && <Segmented size="xs" label="Thang thời gian" value={scale} onChange={setScale} options={scales.map(s => ({ value: s, label: scaleLabel(s) }))} />}
      <div className="scroll-thin overflow-x-auto rounded-[var(--radius-sm)] border border-line">
        <table className="data-table" aria-label="Bán kính đạt gate theo chế độ mặn và cách chuyển">
          <thead><tr><th>Cặp</th><th>Chuyển</th>{gates.map(g => <th key={g} className="num">Gate {gateLabel(g)}</th>)}</tr></thead>
          <tbody>{keys.map(key => {
            const [regime, transfer] = key.split('|')
            return (
              <tr key={key}>
                <td className="whitespace-nowrap">{regimeRelationLabel(regime)}</td>
                <td>{transferLabel(transfer)}</td>
                {gates.map(g => {
                  const row = subset.find(r => r.regime === regime && r.transfer === transfer && r.gate === g)
                  return <td key={g} className="num whitespace-nowrap" title={stopLabel(row?.stop) ?? undefined}>{row ? <span className={row.radius_km ? 'font-semibold' : 'text-fg-subtle'}>{radiusText(row)}</span> : '—'}</td>
                })}
              </tr>
            )
          })}</tbody>
        </table>
      </div>
      <p className="m-0 text-[10.5px] text-fg-subtle">Bán kính lớn nhất mà mọi ô khoảng cách đến đó đều đạt gate; rê chuột vào ô để xem ô khoảng cách bị trượt.</p>
    </div>
  )
}

export function ForeignDetail({ id, theme }: { id: string; theme: Theme }) {
  const [query, setQuery] = useState<{ var?: string; scale?: string; transfer?: string }>({})
  const [regime, setRegime] = useState<RegimeFilter>('all')
  const [maxKm, setMaxKm] = useState<DistanceFilter>('30')
  const narrow = useNarrow()
  useEffect(() => { setQuery({}); setRegime('all'); setMaxKm('30') }, [id])
  const poll = useResearch(signal => getForeignDetail(id, query, signal), [id, query.var, query.scale, query.transfer], { keepPreviousData: true })
  const index = useResearch(getForeignIndex)
  const detail = poll.data?.status === 'ready' && poll.data.id === id ? poll.data : null
  const card = index.data?.datasets?.find(d => d.id === id)
  const habitat = !!detail && (detail.pairs ?? []).every(p => p.same_regime == null) && (detail.pairs ?? []).some(p => p.same_habitat != null)

  const box = useMemo<LonLatBox | null>(() => {
    if (card?.bbox) return card.bbox
    return boxOfPoints((detail?.stations?.features ?? []).map(f => f.geometry.coordinates as [number, number]))
  }, [card?.bbox, detail?.stations])

  const allPairs = detail?.pairs ?? []
  const pairs = useMemo(() => (detail?.pairs ?? []).filter(p => {
    // Pairs without a distance cannot be placed against a radius; show them only under "all".
    if (maxKm !== 'all' && (p.km == null || p.km > Number(maxKm))) return false
    if (regime === 'all') return true
    const same = habitat ? p.same_habitat : p.same_regime
    return regime === 'same' ? same === true : same === false
  }), [detail?.pairs, regime, habitat, maxKm])
  const passing = pairs.filter(passes).length
  const classes = useMemo(() => [...new Set((detail?.stations?.features ?? []).map(f => f.properties.regime_class))], [detail?.stations])
  const selected = detail?.selected
  const available = detail?.available

  const status: VerdictStatus = !detail ? { tone: 'neutral', label: poll.error || poll.data ? 'Không có dữ liệu' : 'Đang tải' }
    : !pairs.length ? { tone: 'neutral', label: 'Không có cặp khớp bộ lọc' }
    : passing > 0 ? { tone: 'ok', label: `${Math.round((passing / pairs.length) * 100)} % cặp đạt` }
    : { tone: 'warn', label: 'Không cặp nào đạt' }
  const header = (
    <MapVerdict code="H4" question={detail ? `${(detail.name ?? id).split(' — ')[0]}: chuyển giá trị được bao xa?` : 'Bộ dữ liệu nước ngoài'}
      value={detail && pairs.length ? `${passing}/${pairs.length}` : '—'} unit={detail && pairs.length ? 'cặp ≥ 80 % thời gian' : undefined} status={status}
      answer={detail?.headline ? splitRefs(detail.headline).text : undefined}
      chips={detail ? <><RedistributableBadge value={!!detail.redistributable} /><Chip size="xs" tone="neutral">{detail.cadence}</Chip><Chip size="xs" tone="neutral">{detail.stations?.features.length ?? 0} trạm</Chip></> : undefined} />
  )

  return (
    <div className="map-with-panel absolute inset-0 overflow-hidden" style={mapPanelStyle(narrow, PANEL_W)}>
      <ResearchMap theme={theme} box={box} inset={mapInset(narrow, PANEL_W)} ariaLabel={`Bản đồ cặp trạm ${card?.name ?? id}`}>
        {detail && <PairLayers detail={detail} pairs={pairs} theme={theme} habitat={habitat} />}
      </ResearchMap>
      <div className="absolute left-3 top-3 z-[800] flex flex-wrap items-center gap-2">
        <a href={RELIABILITY_HASH.foreign} className="glass inline-flex items-center gap-1 rounded-[var(--radius-md)] px-3 py-1.5 text-[12.5px] font-semibold text-accent no-underline hover:underline"><ArrowLeft size={14} /> Tất cả bộ dữ liệu</a>
        {poll.status === 'loading' && detail && <span className="glass rounded-[var(--radius-md)] px-3 py-1.5 text-[12px] text-fg-muted">Đang lọc…</span>}
      </div>

      <MapPanel label="Chi tiết bộ dữ liệu" header={header} width={PANEL_W}>
        {!detail && !poll.data && !poll.error && <Skeleton className="h-48" />}
        {!detail && (poll.data?.status === 'unavailable' || poll.error) && <Unavailable compact envelope={poll.data} error={poll.error} onRetry={poll.refresh} title={`Bộ “${id}” chưa có`} />}
        {detail && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <Select label="Biến" value={selected?.var ?? ''} onChange={v => setQuery(q => ({ ...q, var: v }))} options={(available?.vars ?? []).map(v => ({ value: v, label: variableLabel(v) }))} />
              <Select label="Thang thời gian" value={selected?.scale ?? ''} onChange={v => setQuery(q => ({ ...q, scale: v }))} options={(available?.scales ?? []).map(v => ({ value: v, label: scaleLabel(v) }))} />
            </div>
            <FilterRow label="Cách chuyển giá trị">
              <Segmented size="xs" label="Cách chuyển" value={selected?.transfer ?? 'raw'} onChange={v => setQuery(q => ({ ...q, transfer: v }))} options={(available?.transfers ?? ['raw']).map(t => ({ value: t, label: t === 'raw' ? 'Lấy nguyên' : 'Hiệu chỉnh 30 ngày' }))} />
            </FilterRow>
            <FilterRow label={habitat ? 'Môi trường sống của cặp' : 'Chế độ mặn của cặp'}>
              <Segmented size="xs" label={habitat ? 'Môi trường sống' : 'Chế độ mặn'} value={regime} onChange={setRegime} options={[{ value: 'all', label: 'Tất cả' }, { value: 'same', label: 'Cùng' }, { value: 'different', label: 'Khác' }]} />
            </FilterRow>
            <FilterRow label="Khoảng cách tối đa">
              <Segmented size="xs" label="Khoảng cách tối đa" value={maxKm} onChange={setMaxKm} options={DISTANCE_OPTIONS} />
            </FilterRow>
            {pairs.length === 0 && allPairs.length > 0 && <p className="m-0 text-[12px] text-fg-muted">Không có cặp nào khớp bộ lọc: nới khoảng cách hoặc chọn “Tất cả”.</p>}

            <div className="rounded-[var(--radius-md)] border border-line bg-surface p-3">
              <GradientLegend title="Thời gian trong dung sai (mỗi đường một cặp)" gradient={shareGradient(theme)} ticks={['0 %', '20 %', '40 %', '60 %', '80 %', '100 %']}
                note={`Gate = 80 %; cặp đạt vẽ đậm. Liền = ${habitat ? 'cùng môi trường sống' : 'cùng chế độ'}, đứt = khác.`} />
              <div className="mt-3"><RegimeLegend theme={theme} classes={classes} title="Trạm theo chế độ mặn" /></div>
            </div>

            <div>
              <SectionLabel icon={<Ruler size={12} />}>Bán kính đạt gate · {variableLabel(selected?.var ?? '')}</SectionLabel>
              <RadiusTable key={`${id}-${selected?.var}`} rows={detail.radius ?? []} />
            </div>

            <p className="m-0 text-[11.5px] leading-snug text-fg-muted"><span className="font-semibold">Ghi công:</span> {detail.credit}</p>
            <div className="flex flex-col gap-1">
              <Disclosure summary="Phát hiện" hint={`(${detail.findings?.length ?? 0})`}>
                <FindingList items={detail.findings} />
              </Disclosure>
              {(detail.notes?.length ?? 0) > 0 && (
                <Disclosure summary="Ghi chú" hint={`(${detail.notes!.length})`}><FindingList items={detail.notes} /></Disclosure>
              )}
              <Disclosure summary="Giấy phép & nguồn">
                <p className="m-0"><span className="font-semibold">Giấy phép:</span> {detail.licence}</p>
                {!detail.redistributable && <p className="m-0">Chỉ hiển thị thống kê tổng hợp theo cặp/bán kính; không có chuỗi số liệu thô.</p>}
                <p className="m-0">{detail.region} · {detail.country} · {detail.period} · {detail.climate} {detail.research_log && <RefChips refs={[detail.research_log]} />}</p>
                <p className="m-0 text-[11.5px] text-fg-subtle">Lần chạy <span className="font-mono">{detail.source_run}</span> · bản xuất {detail.export_version}{detail.stations?.regime_class_rule ? ` · ${detail.stations.regime_class_rule}` : ''}</p>
              </Disclosure>
            </div>
          </>
        )}
      </MapPanel>
    </div>
  )
}

function FilterRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <span className="text-[12px] font-semibold text-fg-muted">{label}</span>
      {children}
    </div>
  )
}
