import { ClipboardCheck } from 'lucide-react'
import { getShadowScorecard, researchReason } from '../../api/research'
import { Chip, Disclosure, KeyValue, Note, Panel, Skeleton, Stat, type Tone } from '../../components/ui'
import { formatAge, formatTime } from '../../hooks/useNow'
import { featureSetLabel, horizonLabel, num, pct, pValue } from '../../lib/format'
import type { ScorecardGroup, ScorecardPair, ShadowScorecard as Scorecard } from '../../types/research'
import { Unavailable, useResearch } from '../shared/research'

const EVIDENCE: Record<string, { tone: Tone; label: string }> = {
  sufficient: { tone: 'ok', label: 'Đủ bằng chứng' },
  insufficient_evidence: { tone: 'warn', label: 'Chưa đủ bằng chứng' },
}
const BETTER: Record<string, string> = { with_pH: 'có pH tốt hơn', nopH: 'không pH tốt hơn', no_significant_difference: 'không khác biệt có ý nghĩa' }

const signed = (value: number | null | undefined, digits = 2) => (value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${num(value, digits)}`)

export function useShadowScorecard(station: string) {
  return useResearch(signal => getShadowScorecard(station, signal), [station], { intervalMs: 5 * 60_000, keepPreviousData: true })
}

/** PI80 coverage cell: coloured against the 75–85 % target only once the group has enough evidence. */
function Coverage({ group, target }: { group?: ScorecardGroup; target: [number, number] }) {
  if (!group || group.coverage_pi80 == null) return <span className="text-fg-subtle">—</span>
  const judged = group.evidence === 'sufficient' && group.pi80_in_target != null
  const tone = !judged ? 'text-fg-muted' : group.pi80_in_target ? 'text-ok' : 'text-warn'
  return <span className={tone} title={`PI80 mục tiêu ${pct(target[0])}–${pct(target[1])}${judged ? '' : ' (chưa đủ bằng chứng để đánh giá)'}`}>{pct(group.coverage_pi80)}</span>
}

function Skill({ group }: { group?: ScorecardGroup }) {
  if (!group || group.skill == null) return <span className="text-fg-subtle">—</span>
  const dm = group.dm_vs_persistence
  const tone = group.evidence !== 'sufficient' ? 'text-fg-muted' : dm?.model_better ? 'text-ok' : 'text-warn'
  const title = dm ? `DM ${num(dm.dm_stat, 2)}, p = ${pValue(dm.p_value)}` : 'Chưa kiểm định DM (chưa đủ bằng chứng)'
  return <span className={tone} title={title}>{signed(group.skill)}</span>
}

type Row = { key: string; base: string; horizon: number; withPh?: ScorecardGroup; noPh?: ScorecardGroup; pair?: ScorecardPair }

function rows(data: Scorecard): Row[] {
  const out = new Map<string, Row>()
  for (const g of data.groups ?? []) {
    if (g.target !== 'Temperature') continue
    const key = `${g.base_feature_set}|${g.horizon_minutes}`
    const row = out.get(key) ?? { key, base: g.base_feature_set, horizon: g.horizon_minutes }
    if (g.variant === 'nopH') row.noPh = g
    else row.withPh = g
    out.set(key, row)
  }
  for (const p of data.paired ?? []) {
    const row = out.get(`${p.base_feature_set}|${p.horizon_minutes}`)
    if (row && p.target === 'Temperature') row.pair = p
  }
  return [...out.values()].sort((a, b) => a.horizon - b.horizon || a.base.localeCompare(b.base))
}

function HorizonTable({ data }: { data: Scorecard }) {
  const list = rows(data)
  const target = data.thresholds?.pi80_target ?? [0.75, 0.85]
  if (!list.length) return <p className="m-0 text-[12px] text-fg-subtle">Bảng chấm điểm chưa có nhóm nào: sổ ghi chưa có dự báo nhiệt độ.</p>
  return (
    <div className="scroll-thin overflow-x-auto rounded-[var(--radius-sm)] border border-line">
      <table className="data-table" aria-label="Skill so với persistence và độ phủ PI80 theo chân trời, có pH và không pH">
        <thead>
          <tr>
            <th>Chân trời · bộ</th>
            <th className="num" title="Số dự báo đã đối chiếu (có pH / không pH)">n chấm</th>
            <th className="num" title="1 − MAE / MAE persistence, cùng thời điểm phát hành">Skill có pH</th>
            <th className="num">Skill không pH</th>
            <th className="num" title={`Mục tiêu ${pct(target[0])}–${pct(target[1])}`}>Phủ PI80 có pH</th>
            <th className="num">Phủ PI80 không pH</th>
            <th className="num" title="MAE có pH − MAE không pH trên cùng thời điểm phát hành (âm = có pH tốt hơn)">Δ MAE (°C)</th>
            <th>Bằng chứng</th>
          </tr>
        </thead>
        <tbody>{list.map(row => {
          const evidence = row.withPh?.evidence === 'sufficient' && row.noPh?.evidence === 'sufficient' ? 'sufficient' : 'insufficient_evidence'
          const days = Math.min(row.withPh?.days_scored ?? 0, row.noPh?.days_scored ?? 0)
          return (
            <tr key={row.key}>
              <td className="whitespace-nowrap font-semibold">+{horizonLabel(row.horizon)} · {featureSetLabel(row.base).split(' · ')[0]}</td>
              <td className="num">{row.withPh?.n_scored ?? 0} / {row.noPh?.n_scored ?? 0}</td>
              <td className="num"><Skill group={row.withPh} /></td>
              <td className="num"><Skill group={row.noPh} /></td>
              <td className="num"><Coverage group={row.withPh} target={target} /></td>
              <td className="num"><Coverage group={row.noPh} target={target} /></td>
              <td className="num" title={row.pair?.dm ? `DM ${num(row.pair.dm.dm_stat, 2)}, p = ${pValue(row.pair.dm.p_value)}: ${BETTER[row.pair.dm.better]}` : 'Chưa kiểm định DM'}>{signed(row.pair?.mean_diff, 3)}</td>
              <td><Chip size="xs" tone={EVIDENCE[evidence].tone} title={`${days} ngày có dự báo đã chấm`}>{evidence === 'sufficient' ? 'đủ' : `chưa đủ · ${days} ngày`}</Chip></td>
            </tr>
          )
        })}</tbody>
      </table>
    </div>
  )
}

function Weekly({ data }: { data: Scorecard }) {
  const weekly = (data.weekly ?? []).filter(w => w.target === 'Temperature')
  if (!weekly.length) return <p className="m-0 text-[12px] text-fg-subtle">Chưa có tuần nào.</p>
  return (
    <div className="scroll-thin max-h-72 overflow-auto rounded-[var(--radius-sm)] border border-line">
      <table className="data-table">
        <thead><tr><th>Tuần</th><th>Chân trời · bộ · pH</th><th className="num">n</th><th className="num">MAE</th><th className="num">MAE persistence</th><th className="num">Skill</th><th className="num">Phủ PI80</th><th className="num">Phủ PI90</th><th className="num">Rộng PI80</th></tr></thead>
        <tbody>{weekly.map(w => (
          <tr key={`${w.iso_week}-${w.base_feature_set}-${w.variant}-${w.horizon_minutes}`}>
            <td className="whitespace-nowrap">{w.iso_week}</td>
            <td className="whitespace-nowrap">+{horizonLabel(w.horizon_minutes)} · {featureSetLabel(w.base_feature_set).split(' · ')[0]} · {w.variant === 'nopH' ? 'không pH' : 'có pH'}</td>
            <td className="num">{w.n_scored}</td><td className="num">{num(w.mae, 3)}</td><td className="num">{num(w.persistence_mae, 3)}</td>
            <td className="num">{signed(w.skill)}</td><td className="num">{pct(w.coverage_pi80)}</td><td className="num">{pct(w.coverage_pi90)}</td><td className="num">{num(w.mean_width_pi80, 2)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function GateBar({ progress }: { progress: number }) {
  const value = Math.max(0, Math.min(1, progress))
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-label="Tiến độ gate 4 tuần" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
      <div className="h-full rounded-full bg-[var(--series-1)]" style={{ width: `${value * 100}%` }} />
    </div>
  )
}

/**
 * H1.5 scorecard: days of ledger, resolved forecasts, skill vs persistence per
 * horizon, PI80 coverage, with-pH vs nopH and progress toward the 4-week gate.
 * Numbers come from the newest scorecard run; the ledger span is read live.
 */
export function ShadowScorecard({ station }: { station: string }) {
  const poll = useShadowScorecard(station)
  const data = poll.data
  const live = data?.live
  const ready = data?.status === 'ready'
  const evidence = ready ? EVIDENCE[data.evidence ?? 'insufficient_evidence'] : null
  const thresholds = data?.thresholds
  const gateDays = live?.gate_days ?? thresholds?.gate_days ?? 28
  const noneScored = ready && (data.ledger?.n_scored ?? 0) === 0
  const stale = ready && (data.scorecard_age_hours ?? 0) > 24
  // Gate counts days that have forecasts (scorecard); the live read only knows the span, which would count runner gaps.
  const activeDays = ready ? data.gate?.active_days ?? 0 : null
  const progress = ready ? data.gate?.progress ?? 0 : null
  const span = live?.ledger_state === 'active' ? live.ledger_days : 0

  return (
    <Panel title="Chấm điểm shadow · gate 4 tuần (H1.5)" icon={<ClipboardCheck size={15} />}
      summary={ready && data.generated_at ? `bảng chấm lúc ${formatTime(data.generated_at, true)} · cách ${formatAge((data.scorecard_age_hours ?? 0) * 3600)}` : undefined}
      actions={evidence ? <span className="inline-flex gap-1">{stale && <Chip size="xs" tone="warn" title="Bảng chấm tạo hơn 24 giờ trước; chạy lại experiments/shadow_scorecard.py">bảng chấm cũ</Chip>}<Chip size="xs" tone={evidence.tone}>{evidence.label}</Chip></span> : data ? <Chip size="xs" tone="neutral">Chưa chấm</Chip> : null}>
      {!data && !poll.error && <div className="grid grid-cols-2 gap-2 md:grid-cols-4"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>}
      {!data && poll.error && <Unavailable compact error={poll.error} onRetry={poll.refresh} />}
      {data && (
        <div className="space-y-2.5">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Ngày có dự báo" value={activeDays != null ? num(activeDays, 1) : '—'} unit={`/ ${gateDays} ngày`}
              hint={live?.first_issued_at ? `khoảng từ lần phát đầu ${formatTime(live.first_issued_at, true)}: ${num(span, 1)} ngày (trực tiếp)` : live?.ledger_state === 'empty' ? 'sổ ghi rỗng' : 'chưa có sổ ghi'}
              muted={activeDays == null || live?.ledger_state !== 'active'} />
            <Stat label="Dự báo đã chấm" value={ready ? (data.ledger?.n_scored ?? 0) : '—'} unit={ready ? `/ ${data.ledger?.n_forecasts ?? 0} đã phát` : undefined}
              hint={ready ? `chờ đến hạn ${data.ledger?.n_pending ?? 0} · loại QC ${data.ledger?.n_excluded ?? 0}` : 'chưa có bảng chấm'} muted={!ready || noneScored} />
            <div className="min-w-0 rounded-[var(--radius-sm)] border border-line bg-surface-2 px-2.5 py-2">
              <div className="text-[11px] font-semibold text-fg-subtle">Tiến độ gate 4 tuần</div>
              <div className="mt-0.5 text-[18px] font-semibold leading-tight tracking-tight text-fg tabular">{progress != null ? pct(progress, 1) : '—'}</div>
              <div className="mt-1"><GateBar progress={progress ?? 0} /></div>
              <div className="mt-0.5 truncate text-[10.5px] text-fg-subtle">giờ có dự báo / 24; khoảng trống không tính</div>
            </div>
            <Stat label="Ngưỡng bằng chứng / nhóm" value={`≥ ${thresholds?.min_resolved ?? 200}`} unit={`dự báo · ≥ ${thresholds?.min_days ?? 7} ngày`}
              hint={`PI80 mục tiêu ${pct(thresholds?.pi80_target?.[0] ?? 0.75)}–${pct(thresholds?.pi80_target?.[1] ?? 0.85)}`} muted />
          </div>

          {!ready && <Note tone="info">{researchReason(data.reason)}</Note>}
          {ready && data.evidence !== 'sufficient' && (
            <Note tone="warn">Chưa đủ bằng chứng: mỗi nhóm cần ≥ {thresholds?.min_resolved ?? 200} dự báo đã đối chiếu trải trên ≥ {thresholds?.min_days ?? 7} ngày; kiểm định Diebold–Mariano chỉ chạy khi đủ. Số dưới đây để theo dõi, chưa dùng để kết luận.</Note>
          )}
          {noneScored && <p className="m-0 text-[12px] text-fg-subtle">Chưa có dự báo nào đến hạn đối chiếu: dự báo 3 giờ cần ít nhất 3 giờ sau lần phát đầu tiên mới có giá trị thật để so.</p>}
          {ready && <HorizonTable data={data} />}
          {ready && <p className="m-0 text-[11px] text-fg-subtle">Skill = 1 − MAE / MAE persistence trên cùng thời điểm phát hành (dương = tốt hơn giữ nguyên giá trị hiện tại). Δ MAE âm = có pH tốt hơn. Rê chuột để xem kiểm định DM.</p>}

          <div className="flex flex-col gap-1.5">
            {ready && <Disclosure summary="Theo tuần ISO" hint={`(${(data.weekly ?? []).length})`}><Weekly data={data} /></Disclosure>}
            <Disclosure summary="Nguồn">
              <KeyValue items={[
                ['Trạm', <span key="st" className="font-mono">{data.station ?? station}</span>],
                ready ? ['Bảng chấm', <span key="dir" className="font-mono text-[11px]">artifacts/experiments/{data.export_version}/scorecard.json</span>] : null,
                ['Tạo bảng chấm', <span key="cli" className="font-mono text-[11px]">python experiments/shadow_scorecard.py</span>],
                ['Số ngày sổ ghi', 'đọc trực tiếp từ runtime/forecast-shadow/long_forecasts.jsonl (chỉ đọc)'],
                ready && (data.ledger?.n_on_the_fly ?? 0) > 0 ? ['Đối chiếu tại chỗ', `${data.ledger?.n_on_the_fly} dự báo chưa có trong long_outcomes, đối chiếu từ lịch sử sensor (không ghi vào runtime)`] : null,
                ['Dùng cho cảnh báo', 'Không (shadow mode)'],
              ]} />
            </Disclosure>
          </div>
        </div>
      )}
    </Panel>
  )
}
