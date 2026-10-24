import { Archive, FlaskConical, RefreshCw, WifiOff } from 'lucide-react'
import type { SyncPhase } from './useSync'
import { useLiveData } from './LiveDataContext'
import { Chip, StateChip, stateMeta, type Tone } from '../components/ui'
import { formatAge, useNow } from '../hooks/useNow'
import { describeApiError } from '../api/client'
import { researchReason } from '../api/research'

const SCENARIO_LABEL: Record<string, string> = {
  normal: 'Bình thường', rain_wind_watch: 'Mưa + gió', nh3_watch: 'NH3 tăng', temperature_warning: 'Sốc nhiệt',
  extreme_hazard: 'Tổng hợp', oyster_danger_cobia_safe: 'Lệch pha đối tượng', missing_sensor_data: 'Mất dữ liệu cảm biến',
}
export const scenarioLabel = (id: string) => SCENARIO_LABEL[id] ?? id

const RANK: Record<Tone, number> = { danger: 4, warn: 3, mock: 2, info: 1, neutral: 1, accent: 0, ok: 0 }

/**
 * Live status chips from the light `/api/v1/status` poll: backend link, sensor
 * freshness/age, context snapshot age, research export, data mode. The mode
 * chip never says "live" while the backend is unreachable or the sensor feed
 * is not fresh. Phones get one summary chip (worst state) with the full list
 * in its tooltip and accessible name.
 */
export function TopBarStatus() {
  const { status, mode, scenario, pilotStation } = useLiveData()
  const now = useNow(15_000)
  const elapsed = status.updatedAt ? (now - status.updatedAt) / 1000 : 0

  const data = status.data
  const offline = status.error === 'api_unreachable'
  const failed = !!status.error
  const context = data?.context
  const sensor = data?.sensor
  const contextAge = context?.age_seconds != null ? context.age_seconds + elapsed : null
  const sensorAge = sensor?.age_seconds != null ? sensor.age_seconds + elapsed : null
  const exportVersion = data?.research.export_version

  const sensorState = sensor ? (failed && sensor.status === 'fresh' ? 'stale' : sensor.status) : failed ? 'unavailable' : 'loading'
  const contextState = context ? (failed && context.status === 'fresh' ? 'stale' : context.status) : failed ? 'unavailable' : 'loading'
  // Advisory mode: "live" only when the sensor feed actually is fresh; otherwise say what it is.
  const modeChip = mode === 'mock'
    ? { tone: 'mock' as Tone, label: `Mô phỏng · ${scenarioLabel(scenario)}`, title: 'Dữ liệu khuyến nghị đang ở chế độ mô phỏng, không phải dữ liệu thật' }
    : offline ? { tone: 'danger' as Tone, label: 'Live · mất kết nối', title: 'Không kết nối được backend: không có dữ liệu trực tiếp' }
    : sensorState === 'fresh' ? { tone: 'neutral' as Tone, label: 'Live · shadow', title: 'Khuyến nghị dựng từ cảm biến + API (shadow mode, không gửi tới người nuôi)' }
    : sensorState === 'stale' ? { tone: 'warn' as Tone, label: 'Live · dữ liệu cũ', title: 'Chế độ live nhưng cảm biến đã quá hạn tươi: đang thấy giá trị cũ, không phải hiện tại' }
    : sensorState === 'loading' ? { tone: 'neutral' as Tone, label: 'Live · đang tải', title: 'Đang kiểm tra trạng thái cảm biến' }
    : { tone: 'danger' as Tone, label: 'Live · không có cảm biến', title: 'Chế độ live nhưng không có dữ liệu cảm biến' }

  const sensorTitle = `Cảm biến: ${stateMeta(sensorState).label}${sensorAge != null ? ` (${formatAge(sensorAge)})` : ''} · trạm ${pilotStation}${sensor?.latest_observed_at ? ` · đo lúc ${new Date(sensor.latest_observed_at).toLocaleString('vi-VN')}` : ''}${sensor?.reason ? ` · ${researchReason(sensor.reason)}` : ''}`
  const contextTitle = `Thời tiết vùng (bản tin context): ${stateMeta(contextState).label}${contextAge != null ? ` (${formatAge(contextAge)})` : ''}${context?.snapshot_id ? ` · snapshot ${context.snapshot_id.slice(0, 8)}` : context?.reason ? ` · ${researchReason(context.reason)}` : ''}`
  const worst = [stateMeta(sensorState).tone, stateMeta(contextState).tone, modeChip.tone].sort((a, b) => RANK[b] - RANK[a])[0]
  const summaryLabel = mode === 'mock' ? 'Mô phỏng' : worst === 'danger' ? 'Thiếu dữ liệu' : worst === 'warn' ? 'Dữ liệu cũ' : sensorState === 'loading' ? 'Đang tải' : 'Trực tiếp'
  const summaryTitle = [offline ? describeApiError(status.error) : null, sensorTitle, contextTitle, modeChip.label].filter(Boolean).join(' · ')

  return (
    <div className="flex min-w-0 items-center gap-1.5 overflow-hidden" aria-live="polite">
      <span className="md:hidden" role="status" aria-label={summaryTitle}>
        <Chip tone={mode === 'mock' ? 'mock' : worst} icon={offline ? <WifiOff size={12} /> : mode === 'mock' ? <FlaskConical size={12} /> : undefined} dot={!offline && mode !== 'mock'} title={summaryTitle} className={mode === 'mock' ? 'mock-stripes' : ''}>{summaryLabel}</Chip>
      </span>
      <span className="hidden min-w-0 items-center gap-1.5 md:inline-flex">
        {offline && (
          <Chip tone="danger" icon={<WifiOff size={12} />} title={describeApiError(status.error)}>
            <span className="hidden xl:inline">Mất kết nối backend</span><span className="xl:hidden">Offline</span>
          </Chip>
        )}
        <StateChip prefix="Cảm biến" state={sensorState} suffix={sensorAge != null ? formatAge(sensorAge) : undefined} title={sensorTitle} />
        <span className="hidden lg:inline-flex"><StateChip prefix="Thời tiết vùng" state={contextState} suffix={contextAge != null ? formatAge(contextAge) : undefined} title={contextTitle} /></span>
        {data && (
          <span className="hidden 2xl:inline-flex">
            <Chip tone={exportVersion ? 'neutral' : 'warn'} icon={<Archive size={12} />} title={exportVersion ? 'Bản export nghiên cứu đang dùng (artifacts/research-map/)' : researchReason('research_export_missing')}>
              {exportVersion ? `Export ${exportVersion}` : 'Chưa có export'}
            </Chip>
          </span>
        )}
        <Chip tone={modeChip.tone} icon={mode === 'mock' ? <FlaskConical size={12} /> : undefined} dot={mode !== 'mock'} className={mode === 'mock' ? 'mock-stripes' : ''} title={modeChip.title}>{modeChip.label}</Chip>
      </span>
    </div>
  )
}

const SYNC_LABEL: Record<SyncPhase, string> = {
  idle: 'Đồng bộ dữ liệu mới nhất',
  requesting: 'Đang kiểm tra dữ liệu mới…',
  waiting: 'Đang lấy bản tin mới (tối đa ~2 phút)…',
  done: 'Đã cập nhật dữ liệu mới nhất',
  fresh: 'Dữ liệu đã mới (< 10 phút), đã tải lại giao diện',
  error: 'Không đồng bộ được — kiểm tra kết nối backend',
}

/** "Đồng bộ": ask the worker for a new snapshot, then reload every view (also runs once on app open). */
export function SyncButton() {
  const { sync, syncPhase, lastSyncedAt } = useLiveData()
  const busy = syncPhase === 'requesting' || syncPhase === 'waiting'
  const title = `${SYNC_LABEL[syncPhase]}${lastSyncedAt && !busy ? ` · lần cuối ${lastSyncedAt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}` : ''}`
  return (
    <button type="button" onClick={sync} disabled={busy} title={title} aria-label={title}
      className="inline-flex h-8 flex-none items-center gap-1.5 rounded-[var(--radius-sm)] border border-line bg-surface px-2 text-[12px] font-semibold text-fg-muted transition-colors hover:text-fg disabled:cursor-progress">
      <RefreshCw size={14} className={busy ? 'animate-spin' : ''} />
      <span className="hidden sm:inline">{busy ? 'Đang đồng bộ' : 'Đồng bộ'}</span>
    </button>
  )
}
