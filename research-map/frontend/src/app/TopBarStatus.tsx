import { Archive, FlaskConical, WifiOff } from 'lucide-react'
import { useLiveData } from './LiveDataContext'
import { Chip, StateChip } from '../components/ui'
import { formatAge, useNow } from '../hooks/useNow'
import { describeApiError } from '../api/client'
import { researchReason } from '../api/research'

const SCENARIO_LABEL: Record<string, string> = {
  normal: 'Bình thường', rain_wind_watch: 'Mưa + gió', nh3_watch: 'NH3 tăng', temperature_warning: 'Sốc nhiệt',
  extreme_hazard: 'Tổng hợp', oyster_danger_cobia_safe: 'Lệch pha đối tượng', missing_sensor_data: 'Mất dữ liệu cảm biến',
}
export const scenarioLabel = (id: string) => SCENARIO_LABEL[id] ?? id

/**
 * Live status chips from the light `/api/v1/status` poll: backend link, sensor
 * freshness/age, context snapshot age, research export, data mode.
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

  return (
    <div className="flex min-w-0 items-center gap-1.5 overflow-hidden" aria-live="polite">
      {offline && (
        <Chip tone="danger" icon={<WifiOff size={12} />} title={describeApiError(status.error)}>
          <span className="hidden xl:inline">Mất kết nối backend</span><span className="xl:hidden">Offline</span>
        </Chip>
      )}
      {sensor
        ? <StateChip prefix="Cảm biến" state={failed && sensor.status === 'fresh' ? 'stale' : sensor.status} suffix={sensorAge != null ? formatAge(sensorAge) : undefined}
            title={`Trạm ${pilotStation}${sensor.latest_observed_at ? ` · đo lúc ${new Date(sensor.latest_observed_at).toLocaleString('vi-VN')}` : ''}${sensor.reason ? ` · ${researchReason(sensor.reason)}` : ''}`} />
        : <StateChip prefix="Cảm biến" state={failed ? 'unavailable' : 'loading'} title={describeApiError(status.error)} />}
      {context
        ? <StateChip prefix="Context" state={failed && context.status === 'fresh' ? 'stale' : context.status} suffix={contextAge != null ? formatAge(contextAge) : undefined}
            title={context.snapshot_id ? `Snapshot ${context.snapshot_id.slice(0, 8)}${context.retrieved_at ? ` · lấy lúc ${new Date(context.retrieved_at).toLocaleString('vi-VN')}` : ''}` : researchReason(context.reason)} />
        : <StateChip prefix="Context" state={failed ? 'unavailable' : 'loading'} title={describeApiError(status.error)} />}
      {data && (
        <span className="hidden 2xl:inline-flex">
          <Chip tone={exportVersion ? 'neutral' : 'warn'} icon={<Archive size={12} />} title={exportVersion ? 'Bản export nghiên cứu đang dùng (artifacts/research-map/)' : researchReason('research_export_missing')}>
            {exportVersion ? `Export ${exportVersion}` : 'Chưa có export'}
          </Chip>
        </span>
      )}
      {mode === 'mock'
        ? <Chip tone="mock" icon={<FlaskConical size={12} />} className="mock-stripes" title="Dữ liệu khuyến nghị đang ở chế độ mô phỏng, không phải dữ liệu thật">MÔ PHỎNG · {scenarioLabel(scenario)}</Chip>
        : <Chip tone="neutral" dot title="Khuyến nghị dựng từ cảm biến + API (shadow mode, không gửi tới người nuôi)">Live · shadow</Chip>}
    </div>
  )
}
