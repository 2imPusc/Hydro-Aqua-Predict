import { useMemo } from 'react'
import { CalendarClock, CloudSun, Eye, Gauge } from 'lucide-react'
import { getWeatherStatus, researchReason } from '../../api/research'
import { useLiveData } from '../../app/LiveDataContext'
import { HeatStrip, type HeatRow } from '../../components/charts'
import { Chip, KeyValue, Note, Panel, Stat, type Tone } from '../../components/ui'
import { formatAge } from '../../hooks/useNow'
import { pct, pValue } from '../../lib/format'
import type { WeatherHour, WeatherStatus } from '../../types/research'
import { DirectionPanel, FindingList, PageScroll, ResearchGate, ResearchHeader, useDirection, useResearch } from '../shared/research'

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

const HEALTH: Record<string, { tone: Tone; label: string }> = {
  healthy: { tone: 'ok', label: 'Ổn định' },
  degraded: { tone: 'warn', label: 'Suy giảm' },
  unavailable: { tone: 'danger', label: 'Không khả dụng' },
}

/** "3 h +8.4 % (DM p=0.00043)" fragments of the H2 finding → stat tiles (values verbatim from the export). */
function parseGains(findings: string[] | undefined) {
  const text = findings?.find(item => item.includes('B5')) ?? ''
  return [...text.matchAll(/(\d+)\s*h\s*\+([\d.]+)\s*%\s*\(DM p=([^)]+)\)/g)].map(match => ({ hours: Number(match[1]), gain: Number(match[2]), p: Number(match[3]) }))
}

function CoveragePanel({ data }: { data: WeatherStatus }) {
  const rows = useMemo(() => toRows(data.hourly ?? []), [data.hourly])
  const health = HEALTH[data.health ?? 'unavailable']
  const minCoverage = data.min_coverage ?? 0.9
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Panel title="Độ phủ bản tin thời tiết · 7 ngày × 24 giờ (giờ Việt Nam)" icon={<CalendarClock size={15} />}
        actions={<Chip size="xs" tone={health.tone} dot title={data.reason ? researchReason(data.reason) : undefined}>{health.label}</Chip>}>
        <HeatStrip rows={rows} columns={HOURS} ariaLabel="Lưới giờ có/không có bản tin thời tiết trong 7 ngày gần nhất" />
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-fg-muted">
          <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-[3px]" style={{ background: 'var(--cell-on)' }} aria-hidden />Có bản tin</span>
          <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-[3px]" style={{ background: 'var(--cell-off)' }} aria-hidden />Thiếu</span>
          <span className="inline-flex items-center gap-1.5"><span className="hatch size-3 rounded-[3px] border border-dashed border-line" aria-hidden />Ngoài cửa sổ</span>
          <span className="ml-auto text-fg-subtle">Nguồn: {data.source}</span>
        </div>
      </Panel>
      <div className="flex flex-col gap-4">
        <Panel title="Tình trạng thu thập" icon={<Gauge size={15} />}>
          <div className="grid grid-cols-2 gap-1.5">
            <Stat label="Độ phủ 24 h" value={pct(data.coverage_24h)} hint={`${data.captures_24h ?? 0}/24 giờ`} />
            <Stat label="Độ phủ 7 ngày" value={pct(data.coverage_7d)} muted={data.coverage_7d != null && data.coverage_7d < minCoverage}
              hint={`${data.captures_7d ?? 0}/168 giờ · ngưỡng ${pct(minCoverage)}${data.coverage_7d != null && data.coverage_7d < minCoverage ? ' · dưới ngưỡng' : ''}`} />
          </div>
          <div className="mt-3">
            <KeyValue items={[
              ['Lần thu gần nhất', data.last_captured_at ? new Date(data.last_captured_at).toLocaleString('vi-VN', { timeZone: TZ }) : '—'],
              ['Cách đây', data.age_hours != null ? formatAge(data.age_hours * 3600) : '—'],
              ['Trạm', <span key="s" className="font-mono">{data.station}</span>],
              data.reason ? ['Lý do suy giảm', researchReason(data.reason)] : null,
            ]} />
          </div>
        </Panel>
        <Note tone="info" icon={<Eye size={14} />}>
          <b>Chỉ để quan sát.</b> Bản tin thời tiết là đầu vào nghiên cứu (đặc trưng B5); không bao giờ trực tiếp kích hoạt cảnh báo hay khuyến cáo{data.used_by_alerts === false ? ' (used_by_alerts = false)' : ''}.
        </Note>
      </div>
    </div>
  )
}

export default function WeatherView() {
  const { pilotStation } = useLiveData()
  const { direction, poll: overview } = useDirection('H2')
  const status = useResearch(signal => getWeatherStatus(pilotStation, signal), [pilotStation], { intervalMs: 5 * 60_000, keepPreviousData: true })
  const gains = parseGains(direction?.findings)
  const gainSource = direction?.findings.find(item => item.includes('B5'))

  return (
    <PageScroll>
      <ResearchHeader code="H2" title="Thời tiết & khuyến cáo" direction={direction} exportVersion={overview.data?.export_version ?? undefined} />
      <ResearchGate poll={status} title="Không đọc được trạng thái snapshot thời tiết">{data => <CoveragePanel data={data} />}</ResearchGate>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="Thời tiết giúp dự báo nhiệt độ nước bao nhiêu? (B5 so với B4)" icon={<CloudSun size={15} />}>
          {gains.length ? (
            <>
              <div className="grid grid-cols-3 gap-1.5">
                {gains.map(gain => (
                  <Stat key={gain.hours} label={`Chân trời ${gain.hours} h`} value={`+${gain.gain.toFixed(1)}`} unit="% MAE giảm" hint={`DM p = ${pValue(gain.p)}`} />
                ))}
              </div>
              <p className="m-0 mt-2 text-[11.5px] text-fg-subtle">Giá trị lấy nguyên văn từ overview.json (export). Thời tiết dựng lại (reconstructed_run), một trạm, lockbox 14 ngày.</p>
            </>
          ) : gainSource ? <FindingList items={[gainSource]} /> : <p className="m-0 text-[12px] text-fg-subtle">Bản export chưa có số đo lợi ích B5.</p>}
        </Panel>
        <DirectionPanel direction={direction} poll={overview} />
      </div>
    </PageScroll>
  )
}
