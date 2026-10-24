import { Database } from 'lucide-react'
import { researchReason } from '../../api/research'
import { Chip, Disclosure, KeyValue, Panel, Skeleton, Stat } from '../../components/ui'
import type { PollState } from '../../hooks/usePolling'
import { horizonLabel, num, pct } from '../../lib/format'
import type { B5Coverage, CaptureSource } from '../../types/research'
import { Unavailable } from '../shared/research'

const TZ = 'Asia/Ho_Chi_Minh'
const intFormat = new Intl.NumberFormat('vi-VN')
const SHORT: Record<string, string> = { hap_weather_snapshot_task: 'Task', research_map_worker: 'Worker' }

/** "2026-12-09" → "09/12/2026" (a calendar date, no timezone shift). */
function day(value: string | null | undefined): string {
  if (!value) return '—'
  const [year, month, date] = value.slice(0, 10).split('-')
  return `${date}/${month}/${year}`
}
const count = (value: number | null | undefined) => (value == null ? '—' : intFormat.format(value))
const perSource = (sources: CaptureSource[], pick: (source: CaptureSource) => string) =>
  sources.map(source => `${SHORT[source.source] ?? source.label} ${pick(source)}`).join(' · ')

/** H2.1: is the as-issued weather record growing fast enough for the B5 test (H2.2)? */
export function B5CoverageCard({ poll }: { poll: PollState<B5Coverage> }) {
  const data = poll.data?.status === 'ready' ? poll.data : null
  if (!data) {
    if (poll.data || poll.error) return <Unavailable envelope={poll.data} error={poll.error} title="Không tính được độ phủ bản tin cho B5" onRetry={poll.refresh} />
    return <Skeleton className="h-28" />
  }
  const sources = data.sources ?? []
  const combined = data.combined
  const days = data.days
  const projection = data.projection
  const required = projection?.required_days ?? 63
  const atRate = projection?.projected_ready_date ?? null
  const earliest = projection?.earliest_ready_date ?? null
  const ready = projection?.ready_now === true
  const dateValue = ready ? 'Đã đủ' : day(atRate ?? earliest)
  const dateHint = ready
    ? `${days?.window_eligible_days ?? 0}/${required} ngày gần nhất đạt`
    : atRate ? 'nếu giữ tốc độ hiện tại' : earliest ? 'sớm nhất, nếu từ nay không thiếu ngày nào' : 'chưa ước tính được'
  const slow = !ready && !atRate
  const lastCapture = combined?.last_capture_at ? new Date(combined.last_capture_at).toLocaleString('vi-VN', { timeZone: TZ }) : '—'

  return (
    <Panel title="Đã đủ bản tin cho phép thử B5 chưa?" icon={<Database size={15} />} summary={`H2.1 · cần ${required} ngày bản tin trùng sensor`}>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-1.5">
        <Stat label="Bản tin đã thu" value={count(combined?.captures_total)} unit="bản tin" hint={perSource(sources, source => count(source.captures_total))} />
        <Stat label="Độ phủ 7 ngày" value={pct(combined?.coverage_7d)} unit="giờ có bản tin" hint={perSource(sources, source => pct(source.coverage_7d))} />
        <Stat label="Origin đủ điều kiện cho B5" value={count(combined?.eligible_origins)} unit="origin"
          hint={`${days?.window_eligible_days ?? 0}/${required} ngày đạt · chuỗi ${days?.current_streak_days ?? 0} ngày`} />
        <Stat label="Dự kiến đủ dữ liệu H2.2" value={dateValue} hint={dateHint}
          status={slow ? <Chip size="xs" tone="warn">Tốc độ chưa đủ</Chip> : ready ? <Chip size="xs" tone="ok">Đủ</Chip> : undefined} />
      </div>
      {slow && days?.recent_day_rate != null && (
        <p className="mb-0 mt-2 text-[12px] text-fg-muted">
          {days.recent_days ?? 14} ngày gần nhất chỉ {pct(days.recent_day_rate)} số ngày đạt; cần khoảng 90 % thì cửa sổ {required} ngày mới đủ. Ngày {day(earliest)} chỉ đạt được nếu từ nay không thiếu ngày nào.
        </p>
      )}
      <Disclosure summary="Cách tính" className="mt-2">
        <p className="m-0">
          Hai nguồn thu cùng một bản tin Open-Meteo tại NB1: task Windows mỗi giờ và worker research-map. Gộp lại theo giờ phát hành; giờ nào task đã thu thì bỏ bản của worker. Một origin (mốc dự báo của sensor, {data.origins?.target ?? 'Temperature'}, trước {horizonLabel(data.origins?.horizon_minutes)}) đủ điều kiện khi có bản tin <span className="font-mono">captured_live</span> thu trước đó tối đa {num(data.origins?.max_age_hours ?? 24, 0)} giờ, đúng như phép nối của B5.
        </p>
        <KeyValue items={[
          ['Quy tắc H2.2', projection?.rule ?? '—'],
          ['Ngày đạt (tổng)', `${days?.eligible_days_total ?? 0} ngày · tính đến ${day(days?.as_of)}`],
          ['Ngưỡng một ngày', days?.min_daily_origins != null ? `${count(days.min_daily_origins)} origin` : '—'],
          ['Độ phủ từ đầu', perSource(sources, source => pct(source.coverage_since_start))],
          ['Lần thu gần nhất', lastCapture],
          ['Lịch sử sensor', `${data.sensor_history?.run ?? '—'} · đến ${data.sensor_history?.end ? new Date(data.sensor_history.end).toLocaleString('vi-VN', { timeZone: TZ }) : '—'}`],
          ['File worker', data.worker_capture_present ? 'đã có' : 'chưa có (worker chưa thu lần nào)'],
        ]} />
        {data.reason && <p className="m-0 text-[12px] text-fg-subtle">{researchReason(data.reason)}</p>}
      </Disclosure>
    </Panel>
  )
}
