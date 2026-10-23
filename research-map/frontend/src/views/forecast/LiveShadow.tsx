import { useMemo } from 'react'
import { Ban, Layers3, Radio } from 'lucide-react'
import { getLongForecast } from '../../api/research'
import { IntervalBar } from '../../components/charts'
import { Chip, Disclosure, KeyValue, Note, Panel, Skeleton, StateChip } from '../../components/ui'
import type { PollState } from '../../hooks/usePolling'
import { formatAge, formatTime } from '../../hooks/useNow'
import { baseFeatureSet, featureSetLabel, horizonLabel, isNoPh, num, pct } from '../../lib/format'
import type { LongForecast, LongForecastBundle, LongForecastItem } from '../../types/research'
import { RefChips, Unavailable, useResearch } from '../shared/research'

const UNIT: Record<string, string> = { Temperature: '°C', pH: '' }
const TARGET_LABEL: Record<string, string> = { Temperature: 'Nhiệt độ nước', pH: 'pH' }
const LEDGER_STATE: Record<string, { state: string; label: string }> = {
  active: { state: 'live', label: 'Đang ghi' },
  empty: { state: 'stale', label: 'Sổ ghi rỗng' },
  missing: { state: 'unavailable', label: 'Chưa có sổ ghi' },
}
const ROLE_LABEL: Record<string, string> = { primary_shadow: 'shadow chính', parallel_shadow: 'shadow song song' }

type Group = { key: string; target: string; horizon: number; base: string }
const groupKey = (target: string, horizon: number, featureSet: string) => `${target}|${horizon}|${baseFeatureSet(featureSet)}`

/** Groups items/bundles by target × horizon × base feature set, so "có pH" and "không pH" sit side by side. */
function useGroups(bundles: LongForecastBundle[], items: LongForecastItem[]): Group[] {
  return useMemo(() => {
    const groups = new Map<string, Group>()
    for (const entry of [...bundles.filter(b => b.status !== 'withdrawn'), ...items]) {
      const key = groupKey(entry.target, entry.horizon_min, entry.feature_set)
      if (!groups.has(key)) groups.set(key, { key, target: entry.target, horizon: entry.horizon_min, base: baseFeatureSet(entry.feature_set) })
    }
    return [...groups.values()].sort((a, b) => a.target.localeCompare(b.target) || a.horizon - b.horizon || a.base.localeCompare(b.base))
  }, [bundles, items])
}

function VariantCell({ title, bundle, item, domain, unit, color }: { title: string; bundle?: LongForecastBundle; item?: LongForecastItem; domain: [number, number] | null; unit: string; color: string }) {
  if (!bundle && !item) return <div className="rounded-[var(--radius-sm)] border border-dashed border-line px-2.5 py-2 text-[11.5px] text-fg-subtle">{title}: không cấu hình</div>
  const fmt = (v: number) => num(v, unit === '°C' ? 2 : 3)
  return (
    <div className="min-w-0 rounded-[var(--radius-sm)] border border-line bg-surface-2 px-2.5 py-2">
      <div className="flex items-center justify-between gap-1">
        <span className="text-[11px] font-semibold text-fg-subtle">{title}</span>
        {item ? <Chip size="xs" tone={item.sensor_status === 'ok' ? 'ok' : 'warn'} title={`sensor_status = ${item.sensor_status ?? '—'}`}>{item.sensor_status === 'ok' ? 'phát hành' : item.sensor_status ?? '—'}</Chip>
          : <Chip size="xs" tone="neutral" title="Bundle đã cấu hình nhưng sổ ghi chưa có bản dự báo">chưa phát hành</Chip>}
      </div>
      {item && item.value != null ? (
        <>
          <div className="mt-0.5 flex items-baseline gap-1 tabular"><span className="text-[18px] font-semibold tracking-tight text-fg">{fmt(item.value)}</span><span className="text-[11px] text-fg-subtle">{unit}</span>
            {item.current != null && <span className="ml-auto text-[10.5px] text-fg-subtle">hiện tại {fmt(item.current)}</span>}</div>
          {domain && <IntervalBar value={item.value} current={item.current} pi80={item.pi80} pi90={item.pi90} domain={domain} format={fmt} color={color}
            ariaLabel={`Dự báo ${fmt(item.value)}${unit}, PI80 ${item.pi80 ? item.pi80.map(fmt).join('–') : 'không có'}, PI90 ${item.pi90 ? item.pi90.map(fmt).join('–') : 'không có'}`} />}
          <div className="grid grid-cols-2 gap-x-2 text-[10.5px] text-fg-subtle tabular">
            <span>PI80 {item.pi80 ? item.pi80.map(fmt).join(' – ') : '—'}</span>
            <span className="text-right">PI90 {item.pi90 ? item.pi90.map(fmt).join(' – ') : '∞ / —'}</span>
            <span>phát {formatTime(item.issued_at)}</span>
            <span className="text-right">hiệu lực {formatTime(item.valid_at, true)}</span>
          </div>
          {item.ph_input_status && item.ph_input_status !== 'ok' && item.ph_input_status !== 'not_used' && <div className="mt-1"><Note tone="warn">pH đầu vào: {item.ph_input_status}</Note></div>}
        </>
      ) : (
        <div className="mt-1 space-y-0.5 text-[11px] text-fg-subtle">
          <div>PI: <span className="font-mono">{bundle?.pi_method ?? '—'}</span> · {ROLE_LABEL[bundle?.role ?? ''] ?? bundle?.role ?? '—'}</div>
          <div className="truncate font-mono text-[10px]" title={bundle?.model_version ?? undefined}>{bundle?.model_version ?? ''}</div>
        </div>
      )}
    </div>
  )
}

function GroupCard({ group, data }: { group: Group; data: LongForecast }) {
  const bundles = (data.bundles ?? []).filter(b => b.status !== 'withdrawn' && groupKey(b.target, b.horizon_min, b.feature_set) === group.key)
  const items = (data.items ?? []).filter(i => groupKey(i.target, i.horizon_min, i.feature_set) === group.key)
  const withPh = { bundle: bundles.find(b => !isNoPh(b.feature_set)), item: items.find(i => !isNoPh(i.feature_set)) }
  const noPh = { bundle: bundles.find(b => isNoPh(b.feature_set)), item: items.find(i => isNoPh(i.feature_set)) }
  const bounds = items.flatMap(i => [i.value, i.current, ...(i.pi90 ?? i.pi80 ?? [])]).filter((v): v is number => v != null && Number.isFinite(v))
  const pad = bounds.length ? Math.max(0.05, (Math.max(...bounds) - Math.min(...bounds)) * 0.08) : 0
  const domain: [number, number] | null = bounds.length ? [Math.min(...bounds) - pad, Math.max(...bounds) + pad] : null
  const unit = UNIT[group.target] ?? ''
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface p-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[12.5px] font-semibold text-fg">{TARGET_LABEL[group.target] ?? group.target} · +{horizonLabel(group.horizon)}</span>
        <Chip size="xs" tone="neutral">{featureSetLabel(group.base)}</Chip>
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        <VariantCell title="Có pH" {...withPh} domain={domain} unit={unit} color="var(--series-1)" />
        <VariantCell title="Không pH" {...noPh} domain={domain} unit={unit} color="var(--series-2)" />
      </div>
    </div>
  )
}

/** Compact lineup matrix (target × horizon rows, feature set × pH columns) for when nothing has been issued yet. */
function LineupTable({ bundles }: { bundles: LongForecastBundle[] }) {
  const active = bundles.filter(b => b.status !== 'withdrawn')
  const columns = [...new Set(active.map(b => b.feature_set))].sort((a, b) => baseFeatureSet(a).localeCompare(baseFeatureSet(b)) || Number(isNoPh(a)) - Number(isNoPh(b)))
  const rows = [...new Set(active.map(b => `${b.target}|${b.horizon_min}`))].sort((a, b) => a.localeCompare(b, 'en', { numeric: true }))
  return (
    <div className="scroll-thin overflow-x-auto rounded-[var(--radius-sm)] border border-line">
      <table className="data-table" aria-label="Đội hình bundle dự báo dài hạn đã cấu hình">
        <thead>
          <tr><th>Biến · horizon</th>{columns.map(fs => <th key={fs}>{featureSetLabel(baseFeatureSet(fs)).split(' · ')[0]} · {isNoPh(fs) ? 'không pH' : 'có pH'}</th>)}</tr>
        </thead>
        <tbody>{rows.map(row => {
          const [target, horizon] = row.split('|')
          return (
            <tr key={row}>
              <td className="whitespace-nowrap font-semibold">{TARGET_LABEL[target] ?? target} · +{horizonLabel(Number(horizon))}</td>
              {columns.map(fs => {
                const bundle = active.find(b => b.target === target && b.horizon_min === Number(horizon) && b.feature_set === fs)
                return (
                  <td key={fs} title={bundle?.model_version ?? undefined}>
                    {bundle ? <span className="inline-flex flex-wrap items-center gap-1"><Chip size="xs" tone="neutral">chưa phát hành</Chip><span className="font-mono text-[10.5px] text-fg-subtle">{bundle.pi_method}</span><span className="text-[10.5px] text-fg-subtle">{ROLE_LABEL[bundle.role ?? ''] ?? bundle.role}</span></span> : <span className="text-fg-subtle">—</span>}
                  </td>
                )
              })}
            </tr>
          )
        })}</tbody>
      </table>
    </div>
  )
}

function Withdrawn({ data }: { data: LongForecast }) {
  const withdrawn = data.withdrawn ?? []
  if (!withdrawn.length) return null
  const reasons = [...new Set(withdrawn.map(w => w.reason ?? ''))]
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Ban size={14} className="text-fg-subtle" aria-hidden />
        <StateChip size="xs" state="withdrawn" />
        <RefChips refs={['RL-18', 'RL-13']} />
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {withdrawn.map(w => (
          <span key={`${w.target}-${w.feature_set}-${w.horizon_min}`} className="rounded-[var(--radius-xs)] border border-line bg-surface px-2 py-1 text-[11px] text-fg-subtle line-through decoration-fg-subtle/60">
            {w.target} · {featureSetLabel(w.feature_set)} · +{horizonLabel(w.horizon_min)}
          </span>
        ))}
      </div>
      {reasons.map(reason => <p key={reason} className="m-0 mt-2 text-[11.5px] text-fg-muted">Lý do: <span className="font-mono text-[11px]">{reason || '—'}</span>{withdrawn[0]?.withdrawn_at ? ` · rút ngày ${withdrawn[0].withdrawn_at}` : ''}</p>)}
      <p className="m-0 mt-1 text-[11px] text-fg-subtle">Giữ lại để truy vết; runner không bao giờ phát hành (ghi skip <span className="font-mono">bundle_withdrawn</span>).</p>
    </div>
  )
}

function Scoring({ data }: { data: LongForecast }) {
  const rows = data.scoring ?? []
  if (!rows.length) return <p className="m-0 text-[12px] text-fg-subtle">Chưa có kết quả đối chiếu (outcomes) trong cửa sổ đọc.</p>
  return (
    <div className="scroll-thin max-h-64 overflow-auto rounded-[var(--radius-sm)] border border-line">
      <table className="data-table">
        <thead><tr><th>Biến · horizon</th><th>Bộ đặc trưng</th><th className="num">n</th><th className="num">MAE</th><th className="num">MAE persistence</th><th className="num">Phủ PI80</th><th className="num">Phủ PI90</th><th className="num">loại (QC)</th></tr></thead>
        <tbody>{rows.map(r => (
          <tr key={`${r.target}-${r.horizon_min}-${r.feature_set}`}>
            <td>{r.target} · {horizonLabel(r.horizon_min)}</td><td>{featureSetLabel(r.feature_set)}</td><td className="num">{r.n}</td>
            <td className="num">{num(r.mae, 3)}</td><td className="num">{num(r.persistence_mae, 3)}</td><td className="num">{pct(r.coverage80)}</td><td className="num">{pct(r.coverage90)}</td><td className="num">{r.n_excluded}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

/** Ledger state → chip state + label, shared with the H1 verdict. */
export function ledgerMeta(data: LongForecast | null | undefined) {
  return LEDGER_STATE[data?.ledger_state ?? 'missing']
}

export function useLongForecast(station: string) {
  return useResearch(signal => getLongForecast(station, signal), [station], { intervalMs: 60_000, keepPreviousData: true })
}

/**
 * H1 live shadow ledger: latest long-horizon forecasts, or an honest one-line
 * empty state. Lineup, withdrawn bundles, skips and source sit behind disclosures.
 */
export function LiveShadow({ poll }: { poll: PollState<LongForecast> }) {
  const data = poll.data
  const groups = useGroups(data?.bundles ?? [], data?.items ?? [])
  const ledger = ledgerMeta(data)
  const activeBundles = (data?.bundles ?? []).filter(b => b.status !== 'withdrawn').length

  return (
    <Panel title="Shadow trực tiếp · 3–12 giờ" icon={<Radio size={15} />}
      summary={data ? (data.latest_issued_at ? `phát gần nhất ${formatTime(data.latest_issued_at, true)} · cách ${formatAge((data.latest_age_minutes ?? 0) * 60)}` : 'chưa có bản phát hành nào') : undefined}
      actions={data ? <StateChip size="xs" state={ledger.state} label={ledger.label} /> : poll.error ? <StateChip size="xs" state="unavailable" /> : <StateChip size="xs" state="loading" />}>
      {!data && !poll.error && <div className="grid grid-cols-3 gap-2"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>}
      {!data && poll.error && <Unavailable compact error={poll.error} onRetry={poll.refresh} />}
      {data && (
        <div className="space-y-2.5">
          {data.ledger_state !== 'active' && (
            <p className="m-0 flex items-start gap-2 text-[13px] text-fg">
              <Layers3 size={15} className="mt-0.5 flex-none text-info" aria-hidden />
              <span>{data.ledger_state === 'empty' ? 'Sổ ghi đang rỗng' : 'Bộ chạy shadow chưa ghi bản dự báo dài hạn nào'}: không hiển thị số cũ hay giả lập.
                <span className="text-fg-muted"> {activeBundles} mô hình đã cấu hình sẽ hiện số khi bộ chạy bắt đầu ghi.</span></span>
            </p>
          )}

          {data.ledger_state === 'active' && groups.length > 0 && (
            <>
              <p className="m-0 text-[12px] text-fg-muted">Dải đậm = PI80, nhạt = PI90, vạch đứt = giá trị hiện tại.</p>
              <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">{groups.map(group => <GroupCard key={group.key} group={group} data={data} />)}</div>
            </>
          )}

          <div className="flex flex-col gap-1.5">
            {data.ledger_state !== 'active' && groups.length > 0 && (
              <Disclosure summary="Đội hình đã cấu hình" hint={`(${activeBundles} mô hình)`}>
                <p className="m-0">Có pH = shadow chính, không pH = shadow song song (A1).</p>
                <LineupTable bundles={data.bundles ?? []} />
              </Disclosure>
            )}
            {!groups.length && data.ledger_state !== 'active' && <p className="m-0 text-[12px] text-fg-subtle">Không đọc được manifest mô hình: không có đội hình để hiển thị.</p>}
            {(data.withdrawn?.length ?? 0) > 0 && (
              <Disclosure summary="Mô hình pH đã rút" hint={`(${data.withdrawn!.length})`}><Withdrawn data={data} /></Disclosure>
            )}
            {data.ledger_state === 'active' && (
              <Disclosure summary="Chấm điểm trực tiếp" hint={`(${data.scoring?.length ?? 0})`}><Scoring data={data} /></Disclosure>
            )}
            {(data.skips?.length ?? 0) > 0 && (
              <Disclosure summary="Lý do bỏ qua gần đây (48 h)" hint={`(${data.skips!.length})`}>
              <ul className="m-0 grid list-none gap-1 p-0 md:grid-cols-2">
                {data.skips!.slice(0, 12).map(skip => (
                  <li key={`${skip.target}-${skip.horizon_min}-${skip.feature_set}-${skip.reason}`} className="flex items-center gap-2 rounded-[var(--radius-xs)] bg-surface-2 px-2 py-1 text-[11.5px]">
                    <span className="min-w-0 flex-1 truncate text-fg-muted">{skip.target} · {featureSetLabel(skip.feature_set)} · +{horizonLabel(skip.horizon_min)}</span>
                    <span className="font-mono text-[10.5px] text-fg">{skip.reason}</span>
                    <span className="text-[10.5px] text-fg-subtle tabular">{formatTime(skip.at)}</span>
                  </li>
                ))}
              </ul>
              </Disclosure>
            )}
            <Disclosure summary="Nguồn">
              <KeyValue items={[
                ['Trạm', <span key="st" className="font-mono">{data.station}</span>],
                ['Sổ ghi', <span key="src" className="font-mono text-[11px]">runtime/forecast-shadow/long_*.jsonl (chỉ đọc)</span>],
                data.window ? ['Cửa sổ đọc', data.window] : null,
                ['Dùng cho cảnh báo', 'Không (shadow mode)'],
              ]} />
            </Disclosure>
          </div>
        </div>
      )}
    </Panel>
  )
}
