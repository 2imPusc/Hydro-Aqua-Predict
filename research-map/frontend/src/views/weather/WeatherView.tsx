import { useMemo } from 'react'
import { CalendarClock, CloudSun, Eye } from 'lucide-react'
import { getHazards, getWeatherStatus, researchReason } from '../../api/research'
import { useLiveData } from '../../app/LiveDataContext'
import { HeatStrip, type HeatRow } from '../../components/charts'
import { Chip, Disclosure, KeyValue, Panel, Skeleton, Stat, Verdict, type VerdictStatus } from '../../components/ui'
import { formatAge } from '../../hooks/useNow'
import type { PollState } from '../../hooks/usePolling'
import { pct, pValue } from '../../lib/format'
import type { WeatherHour, WeatherStatus } from '../../types/research'
import { DirectionPanel, FindingList, PageScroll, ResearchHeader, Unavailable, useDirection, useResearch } from '../shared/research'
import { HazardCard } from './HazardCard'

const TZ = 'Asia/Ho_Chi_Minh'
const HOURS = Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, '0'))
const dateKey = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
const hourKey = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', hourCycle: 'h23' })
const dayLabel = new Intl.DateTimeFormat('vi-VN', { timeZone: TZ, weekday: 'short', day: '2-digit', month: '2-digit' })

/** Buckets the 168 UTC hours by local (UTC+7) date × hour; hours outside the window are "outside". */
function toRows(hourly: WeatherHour[]): HeatRow[] {
  const byDate = new Map<string, { label: string; hours: Map<string, boolean> }>()
  for (const item of hourly) {
    const at = new Date(item.hour)
    const key = dateKey.format(at)
    if (!byDate.has(key)) byDate.set(key, { label: dayLabel.format(at), hours: new Map() })
    byDate.get(key)!.hours.set(hourKey.format(at), item.captured)
  }
  return [...byDate.entries()].map(([key, value]) => ({
    key, label: value.label,
    cells: HOURS.map(hour => {
      const captured = value.hours.get(hour)
      const when = `${value.label} ${hour}:00`
      return captured === undefined
        ? { key: `${key}-${hour}`, state: 'outside' as const, label: `${when} · ngoài cửa sổ 7 ngày` }
        : { key: `${key}-${hour}`, state: captured ? 'on' as const : 'off' as const, label: `${when} · ${captured ? 'đã thu bản tin' : 'không có bản tin'}` }
    }),
  }))
}

const HEALTH: Record<string, VerdictStatus> = {
  healthy: { tone: 'ok', label: 'Ổn định' },
  degraded: { tone: 'warn', label: 'Suy giảm' },
  unavailable: { tone: 'danger', label: 'Không khả dụng' },
}

/** "3 h +8.4 % (DM p=0.00043)" fragments of the H2 finding → stat tiles (values verbatim from the export). */
function parseGains(findings: string[] | undefined) {
  const text = findings?.find(item => item.includes('B5')) ?? ''
  return [...text.matchAll(/(\d+)\s*h\s*\+([\d.]+)\s*%\s*\(DM p=([^)]+)\)/g)].map(match => ({ hours: Number(match[1]), gain: Number(match[2]), p: Number(match[3]) }))
}

/** One question: is the weather feed being captured every hour? */
function WeatherVerdict({ status }: { status: PollState<WeatherStatus> }) {
  const data = status.data?.status === 'ready' ? status.data : null
  if (!data) {
    if (status.data || status.error) return <Unavailable envelope={status.data} error={status.error} title="Không đọc được trạng thái bản tin thời tiết" onRetry={status.refresh} />
    return <Skeleton className="h-32" />
  }
  const health = HEALTH[data.health ?? 'unavailable'] ?? HEALTH.unavailable
  const minCoverage = data.min_coverage ?? 0.9
  const below = data.coverage_7d != null && data.coverage_7d < minCoverage
  return (
    <Verdict
      question="Bản tin thời tiết có được thu đủ mỗi giờ không?"
      status={health}
      value={pct(data.coverage_7d)}
      unit="giờ có bản tin · 7 ngày"
      answer={data.reason ? researchReason(data.reason) : below ? `Dưới ngưỡng ${pct(minCoverage)}.` : `Đạt ngưỡng ${pct(minCoverage)}.`}
      facts={[
        { label: '24 giờ qua', value: pct(data.coverage_24h), hint: `${data.captures_24h ?? 0}/24 giờ` },
        { label: 'Lần thu gần nhất', value: data.age_hours != null ? formatAge(data.age_hours * 3600) : '—', hint: data.last_captured_at ? new Date(data.last_captured_at).toLocaleString('vi-VN', { timeZone: TZ }) : undefined },
      ]}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Chip size="xs" tone="info" icon={<Eye size={11} />}>Chỉ quan sát</Chip>
        <Disclosure summary="Nghĩa là gì?">
          <p className="m-0">Bản tin thời tiết là đầu vào nghiên cứu (đặc trưng B5); không bao giờ trực tiếp kích hoạt cảnh báo hay khuyến cáo{data.used_by_alerts === false ? ' (used_by_alerts = false)' : ''}.</p>
          <KeyValue items={[['Trạm', <span key="s" className="font-mono">{data.station}</span>], ['Nguồn', data.source], ['Ngưỡng 7 ngày', pct(minCoverage)]]} />
        </Disclosure>
      </div>
    </Verdict>
  )
}

function CoveragePanel({ data }: { data: WeatherStatus }) {
  const rows = useMemo(() => toRows(data.hourly ?? []), [data.hourly])
  return (
    <Panel title="Giờ nào thiếu bản tin?" icon={<CalendarClock size={15} />} summary="7 ngày × 24 giờ, giờ Việt Nam">
      <div className="scroll-thin overflow-x-auto">
        <div className="min-w-[560px]"><HeatStrip rows={rows} columns={HOURS} ariaLabel="Lưới giờ có/không có bản tin thời tiết trong 7 ngày gần nhất" /></div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-fg-muted">
        <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-[3px]" style={{ background: 'var(--cell-on)' }} aria-hidden />Có bản tin</span>
        <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-[3px]" style={{ background: 'var(--cell-off)' }} aria-hidden />Thiếu</span>
        <span className="inline-flex items-center gap-1.5"><span className="hatch size-3 rounded-[3px] border border-dashed border-line" aria-hidden />Ngoài cửa sổ</span>
      </div>
    </Panel>
  )
}

export default function WeatherView() {
  const { pilotStation } = useLiveData()
  const { direction, poll: overview } = useDirection('H2')
  const status = useResearch(signal => getWeatherStatus(pilotStation, signal), [pilotStation], { intervalMs: 5 * 60_000, keepPreviousData: true })
  const gains = parseGains(direction?.findings)
  const gainSource = direction?.findings.find(item => item.includes('B5'))
  const ready = status.data?.status === 'ready' ? status.data : null
  const hazards = useResearch(signal => getHazards(signal), [])

  return (
    <PageScroll>
      <ResearchHeader code="H2" title="Thời tiết & khuyến cáo" direction={direction} exportVersion={overview.data?.export_version ?? undefined} />
      <WeatherVerdict status={status} />
      {ready && <CoveragePanel data={ready} />}
      <HazardCard poll={hazards} />
      <Panel title="Thời tiết giúp dự báo nhiệt độ nước bao nhiêu?" icon={<CloudSun size={15} />}>
        {gains.length ? (
          <>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(110px,1fr))] gap-1.5">
              {gains.map(gain => (
                <Stat key={gain.hours} label={`Trước ${gain.hours} giờ`} value={`+${gain.gain.toFixed(1)}`} unit="% sai số giảm" hint={`DM p = ${pValue(gain.p)}`} />
              ))}
            </div>
            <Disclosure summary="Số này từ đâu?" className="mt-2">
              <p className="m-0">So sánh bộ có thời tiết (B5) với bộ chỉ dùng chất lượng nước (B4). Giá trị lấy nguyên văn từ overview.json; thời tiết dựng lại (reconstructed_run), một trạm, lockbox 14 ngày.</p>
            </Disclosure>
          </>
        ) : gainSource ? <FindingList items={[gainSource]} /> : <p className="m-0 text-[12px] text-fg-subtle">Bản export chưa có số đo lợi ích B5.</p>}
      </Panel>
      <DirectionPanel direction={direction} poll={overview} />
    </PageScroll>
  )
}
