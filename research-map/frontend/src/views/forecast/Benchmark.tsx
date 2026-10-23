import { useMemo, useState } from 'react'
import { ChartLine, FlaskRound, Scale, Target } from 'lucide-react'
import { ChartLegend, HollowMarkerNote, LineChart, type ChartBand, type ChartSeries } from '../../components/charts'
import { Chip, Disclosure, Note, Panel, Segmented, SectionLabel, StatusWord } from '../../components/ui'
import { baseFeatureSet, featureSetLabel, horizonLabel, horizonShort, methodLabel, num, pct, pValue, signedPct } from '../../lib/format'
import type { BenchmarkRow, ConformalRow, ForecastBenchmark } from '../../types/research'
import { FindingList, GateChip, RefChips } from '../shared/research'

/** Feature set → fixed categorical slot (colour follows the entity in every chart). */
const FS_COLOR: Record<string, string> = { B4_quality: 'var(--series-1)', B5_external_as_issued: 'var(--series-2)', B6_tide: 'var(--series-3)', B0_lags: 'var(--series-4)' }
const fsColor = (featureSet: string) => FS_COLOR[baseFeatureSet(featureSet)] ?? 'var(--fg-subtle)'
const uniqueSorted = (values: number[]) => [...new Set(values)].sort((a, b) => a - b)

function skillSeries(rows: BenchmarkRow[], key: (row: BenchmarkRow) => string, label: (row: BenchmarkRow) => string, dashed?: (row: BenchmarkRow) => boolean): ChartSeries[] {
  const groups = new Map<string, BenchmarkRow[]>()
  rows.forEach(row => groups.set(key(row), [...(groups.get(key(row)) ?? []), row]))
  return [...groups.entries()].map(([id, list]) => ({
    id, label: label(list[0]), color: fsColor(list[0].feature_set), dashed: dashed?.(list[0]),
    points: list.map(row => ({ x: row.horizon_min, y: row.skill, hollow: row.gate !== 'pass' })),
  }))
}

function rowTooltip(rows: BenchmarkRow[]) {
  return (x: number) => {
    const at = rows.filter(row => row.horizon_min === x)
    if (!at.length) return null
    return (
      <div className="mt-1 border-t border-line pt-1 text-[10.5px] text-fg-subtle">
        {at.map(row => <div key={row.feature_set + row.variant}>{featureSetLabel(row.feature_set)}: fold {row.folds_won ?? '—'} · DM p {pValue(row.dm_p)} · {row.gate === 'pass' ? 'đạt' : 'không đạt'}</div>)}
      </div>
    )
  }
}

/** Headline numbers for the H1 verdict, computed from the exported benchmark rows (never typed in). */
export function benchmarkSummary(data: ForecastBenchmark) {
  const h12 = (data.temperature ?? []).filter(row => row.source === 'H1.2')
  const passing = h12.filter(row => row.gate === 'pass')
  const maxPassHorizon = passing.length ? Math.max(...passing.map(row => row.horizon_min)) : null
  const phLong = (data.ph_clean ?? []).filter(row => row.horizon_min >= 180)
  return {
    tempPassed: passing.length, tempTotal: h12.length, maxPassHorizon,
    phPassed: phLong.filter(row => row.gate === 'pass').length, phTotal: phLong.length,
  }
}

export function TemperatureSkill({ rows }: { rows: BenchmarkRow[] }) {
  const h12 = rows.filter(row => row.source === 'H1.2')
  const xs = uniqueSorted(h12.map(row => row.horizon_min))
  const series = skillSeries(h12, row => row.feature_set, row => featureSetLabel(row.feature_set))
  const order = ['B4_quality', 'B5_external_as_issued', 'B6_tide', 'B0_lags']
  series.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
  return (
    <div>
      <ChartLegend series={series} markerNote={<HollowMarkerNote filled="đạt gate" hollow="không đạt" />} />
      <LineChart xs={xs} xFormat={horizonShort} series={series} yFormat={v => `${v.toFixed(0)} %`} yTitle="skill (%)" include={[0]} height={220}
        ariaLabel="Skill nhiệt độ so với persistence theo horizon, mỗi đường một bộ đặc trưng" tooltipExtra={rowTooltip(h12)} hollowLabel="không đạt" />
      <Disclosure summary="Đọc biểu đồ thế nào?">
        <p className="m-0">Skill = mức giảm sai số so với cách đoán “giữ nguyên giá trị hiện tại” (1 − MAE/MAE persistence, trên lockbox). Cao hơn là tốt hơn; dưới 0 là thua cách đoán đơn giản.</p>
        <p className="m-0">Điểm đặc = đạt gate #16, điểm rỗng = không đạt. B0 (chỉ trễ) không có kiểm định DM nên luôn rỗng. Dữ liệu H1.2, có pH.</p>
      </Disclosure>
    </div>
  )
}

function NoPhComparison({ rows }: { rows: BenchmarkRow[] }) {
  const a1 = rows.filter(row => row.source === 'A1')
  const xs = uniqueSorted(a1.map(row => row.horizon_min))
  const series = skillSeries(a1, row => row.feature_set, row => featureSetLabel(row.feature_set), row => row.variant === 'nopH')
  const order = ['B4_quality', 'B4_quality_nopH', 'B5_external_as_issued', 'B5_external_as_issued_nopH']
  series.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
  const passed = a1.filter(row => row.gate === 'pass').length
  const deltas = useMemo(() => xs.map(h => {
    const pick = (fs: string) => a1.find(row => row.horizon_min === h && row.feature_set === fs)?.skill
    const b5 = pick('B5_external_as_issued'), b5n = pick('B5_external_as_issued_nopH')
    return { h, delta: b5 != null && b5n != null ? b5n - b5 : null }
  }), [a1, xs])
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-fg-muted">Đường liền = có pH, đứt = không pH</span>
        <Chip size="xs" tone={passed === a1.length ? 'ok' : 'warn'}>{passed}/{a1.length} đạt gate</Chip>
        <RefChips refs={['RL-18']} />
      </div>
      <ChartLegend series={series} />
      <LineChart xs={xs} xFormat={horizonShort} series={series} yFormat={v => `${v.toFixed(0)} %`} yTitle="skill (%)" include={[0]} height={190}
        ariaLabel="So sánh skill nhiệt độ có và không có đặc trưng pH" tooltipExtra={rowTooltip(a1)} hollowLabel="không đạt" />
      <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-fg-muted">
        <span className="text-fg-subtle">B5 bỏ pH, chênh skill:</span>
        {deltas.map(d => <span key={d.h} className="rounded bg-surface-2 px-1.5 py-0.5 tabular">{horizonShort(d.h)} {d.delta != null ? `${d.delta > 0 ? '+' : ''}${d.delta.toFixed(1)} điểm` : '—'}</span>)}
      </div>
    </div>
  )
}

function PhClean({ rows }: { rows: BenchmarkRow[] }) {
  const xs = uniqueSorted(rows.map(row => row.horizon_min))
  const sets = [...new Set(rows.map(row => row.feature_set))].sort()
  const long = rows.filter(row => row.horizon_min >= 180)
  const longPass = long.filter(row => row.gate === 'pass').length
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-fg-muted">A3 · dữ liệu sạch, trước khi đầu dò pH trôi</span>
        <RefChips refs={['RL-13', 'RL-18']} />
      </div>
      <div className="mb-2 flex items-center gap-2 text-[12.5px] text-fg">
        <StatusWord status={{ tone: 'danger', label: `${longPass}/${long.length} đạt ở 3–12 h` }} />
        <span className="text-fg-muted">→ bundle pH dài hạn đã rút khỏi shadow</span>
      </div>
      <div className="scroll-thin overflow-x-auto rounded-[var(--radius-sm)] border border-line">
        <table className="data-table" aria-label="Gate pH theo bộ đặc trưng và horizon">
          <thead><tr><th>Bộ đặc trưng</th>{xs.map(h => <th key={h} className="num">{horizonLabel(h)}</th>)}</tr></thead>
          <tbody>{sets.map(fs => (
            <tr key={fs}>
              <td className="whitespace-nowrap">{featureSetLabel(fs)}</td>
              {xs.map(h => {
                const row = rows.find(r => r.feature_set === fs && r.horizon_min === h)
                return (
                  <td key={h} className="num" title={row ? `fold ${row.folds_won} · DM p ${pValue(row.dm_p)}` : undefined}>
                    {row ? <span className="inline-flex flex-col items-end gap-0.5 whitespace-nowrap"><span className={row.skill != null && row.skill < 0 ? 'text-danger' : ''}>{signedPct(row.skill)}</span><GateChip gate={row.gate} /></span> : '—'}
                  </td>
                )
              })}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}

const METHOD_COLOR: Record<string, string> = { aci_scaled: 'var(--series-1)', aci_amp: 'var(--series-2)', static: 'var(--series-3)', static_night: 'var(--series-4)' }
const BANDS: Record<string, ChartBand> = { '0.8': { from: 0.75, to: 0.85, label: 'mục tiêu 75–85 %' }, '0.9': { from: 0.85, to: 0.95, label: 'mục tiêu 85–95 %' } }

function Conformal({ rows }: { rows: ConformalRow[] }) {
  const valid = rows.filter(row => !row.validity)
  const invalid = rows.filter(row => row.validity)
  const sets = [...new Set(valid.map(row => row.feature_set))].sort()
  const [featureSet, setFeatureSet] = useState(() => sets.includes('B5_external_as_issued') ? 'B5_external_as_issued' : sets[0] ?? '')
  const selected = valid.filter(row => row.feature_set === featureSet)
  const xs = uniqueSorted(selected.map(row => row.horizon_min))
  const methods = ['aci_scaled', 'aci_amp', 'static', 'static_night'].filter(m => selected.some(row => row.method === m))
  const seriesFor = (level: number): ChartSeries[] => methods.map(method => ({
    id: method, label: methodLabel(method), color: METHOD_COLOR[method] ?? 'var(--fg-subtle)', dashed: method === 'static' || method === 'static_night',
    points: selected.filter(row => row.method === method && row.level === level).map(row => ({ x: row.horizon_min, y: row.coverage, hollow: row.gate === 'fail' })),
  }))
  const tooltip = (level: number) => (x: number) => (
    <div className="mt-1 border-t border-line pt-1 text-[10.5px] text-fg-subtle">
      {selected.filter(row => row.level === level && row.horizon_min === x).map(row => <div key={row.method}>{row.method}: rộng {num(row.width, 2)} · Winkler {num(row.winkler, 2)}{row.frac_infinite ? ` · ∞ ${pct(row.frac_infinite, 1)}` : ''}</div>)}
    </div>
  )
  const passAmp = selected.filter(row => row.method === 'aci_amp' && row.level === 0.8)
  const invalidRuns = [...new Set(invalid.map(row => row.validity))]
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-fg-muted">Nhiệt độ · khoảng tin cậy có phủ đúng tỷ lệ không?</span>
        <RefChips refs={['RL-09', 'RL-19']} />
        <div className="ml-auto w-[min(100%,360px)]">
          <Segmented size="xs" label="Bộ đặc trưng" value={featureSet} onChange={setFeatureSet} options={sets.map(fs => ({ value: fs, label: featureSetLabel(fs).split(' · ')[0] + ' · ' + (featureSetLabel(fs).split(' · ')[1] ?? '') }))} />
        </div>
      </div>
      <ChartLegend series={seriesFor(0.8)} markerNote={<HollowMarkerNote filled="đạt / chưa chấm" hollow="trượt gate (PI80)" />} />
      <div className="mt-1 grid gap-3 lg:grid-cols-2">
        {[0.8, 0.9].map(level => (
          <div key={level}>
            <div className="text-[11.5px] font-semibold text-fg-muted">PI{Math.round(level * 100)} · độ phủ thực tế</div>
            <LineChart xs={xs} xFormat={horizonShort} series={seriesFor(level)} yFormat={v => `${Math.round(v * 100)} %`} bands={[BANDS[String(level)]]} height={180}
              ariaLabel={`Độ phủ PI${Math.round(level * 100)} theo horizon cho ${featureSetLabel(featureSet)}`} tooltipExtra={tooltip(level)} hollowLabel="trượt" />
          </div>
        ))}
      </div>
      <Disclosure summary="Đọc biểu đồ thế nào?">
        <p className="m-0">Dải xanh là vùng mục tiêu: đường nằm trong dải = khoảng tin cậy phủ đúng tỷ lệ.</p>
        <p className="m-0">aci_amp PI80 đạt {passAmp.filter(row => row.gate === 'pass').length}/{passAmp.length} horizon cho bộ này, nhưng cửa sổ 24 h được chọn sau khi xem lockbox (gần in-sample), nên mặc định vẫn là aci_scaled.</p>
      </Disclosure>
      {invalid.length > 0 && (
        <details className="mt-2 rounded-[var(--radius-sm)] border border-dashed border-line-strong bg-surface-2 px-3 py-2 text-[11.5px] text-fg-subtle">
          <summary className="cursor-pointer font-semibold">pH: {invalid.length} dòng conformal không có giá trị: {invalidRuns.join(', ')}</summary>
          <p className="m-0 mt-1">Các dòng này nằm trong giai đoạn đầu dò pH trôi (từ 19/09, RL-13): giữ lại để truy vết, không vẽ thành kết quả.</p>
          <div className="scroll-thin mt-1.5 max-h-48 overflow-auto opacity-70">
            <table className="data-table">
              <thead><tr><th>Bộ</th><th>Phương pháp</th><th className="num">Horizon</th><th className="num">Mức</th><th className="num">Độ phủ (không hợp lệ)</th></tr></thead>
              <tbody>{invalid.map((row, index) => <tr key={index} className="is-muted"><td>{featureSetLabel(row.feature_set)}</td><td>{row.method}</td><td className="num">{horizonShort(row.horizon_min)}</td><td className="num">{pct(row.level)}</td><td className="num line-through">{pct(row.coverage, 1)}</td></tr>)}</tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}

/** Main chart of the H1 view: temperature skill by horizon, with the gate rule one click away. */
export function SkillPanel({ data }: { data: ForecastBenchmark }) {
  const { tempPassed, tempTotal } = benchmarkSummary(data)
  return (
    <Panel title="Nhiệt độ nước · tốt hơn cách đoán đơn giản bao nhiêu?" icon={<ChartLine size={15} />}
      actions={<Chip size="xs" tone={tempPassed === tempTotal ? 'ok' : 'warn'} title={data.gate_rule}>{tempPassed}/{tempTotal} đạt gate #16</Chip>}>
      <TemperatureSkill rows={data.temperature ?? []} />
      <Disclosure summary="Gate #16 là gì?">
        <p className="m-0"><Scale size={12} className="mr-1 inline align-[-2px]" aria-hidden />{data.gate_rule}</p>
      </Disclosure>
    </Panel>
  )
}

/** Secondary analyses: closed by default, each header carries its one-line answer. */
export function BenchmarkDetails({ data }: { data: ForecastBenchmark }) {
  const a1 = (data.temperature ?? []).filter(row => row.source === 'A1')
  const { phPassed, phTotal } = benchmarkSummary(data)
  const runs = [...new Set([...(data.temperature ?? []), ...(data.ph_clean ?? []), ...(data.conformal ?? [])].map(row => row.source_run))]
  return (
    <>
      <Panel title="Bỏ pH có làm dự báo kém đi?" icon={<FlaskRound size={15} />} collapsible defaultOpen={false}
        summary={`A1 · ${a1.filter(row => row.gate === 'pass').length}/${a1.length} cấu hình đạt cả khi không có pH`}>
        <NoPhComparison rows={data.temperature ?? []} />
      </Panel>
      <Panel title="pH dài hạn" icon={<FlaskRound size={15} />} collapsible defaultOpen={false}
        summary={<StatusWord size="xs" status={{ tone: 'danger', label: `Không đạt · ${phPassed}/${phTotal} cấu hình 3–12 h` }} />}>
        <PhClean rows={data.ph_clean ?? []} />
      </Panel>
      <Panel title="Khoảng tin cậy (conformal)" icon={<Target size={15} />} collapsible defaultOpen={false} summary="PI80 / PI90 theo horizon và phương pháp">
        <Conformal rows={data.conformal ?? []} />
      </Panel>
      {(data.notes?.length ?? 0) > 0 && (
        <Panel title="Nguồn số liệu" collapsible defaultOpen={false} summary={`${runs.length} run${(data.missing_runs?.length ?? 0) > 0 ? ` · thiếu ${data.missing_runs!.length}` : ''}`}>
          <FindingList items={data.notes} />
          {(data.missing_runs?.length ?? 0) > 0 && <div className="mt-2"><Note tone="warn">Thiếu run: {data.missing_runs!.join(', ')}</Note></div>}
          <SectionLabel>Run nguồn</SectionLabel>
          <div className="flex flex-wrap gap-1.5">{runs.map(run => <Chip key={run} size="xs" tone="neutral">{run}</Chip>)}</div>
        </Panel>
      )}
    </>
  )
}
