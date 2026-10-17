import { FlaskConical, WifiOff } from 'lucide-react'
import { useLiveData } from './LiveDataContext'
import { Chip, StateChip } from '../components/ui'
import { formatAge, useNow } from '../hooks/useNow'
import { describeApiError } from '../api/client'

const SCENARIO_LABEL: Record<string, string> = {
  normal: 'Bình thường', rain_wind_watch: 'Mưa + gió', nh3_watch: 'NH3 tăng', temperature_warning: 'Sốc nhiệt',
  extreme_hazard: 'Tổng hợp', oyster_danger_cobia_safe: 'Lệch pha đối tượng', missing_sensor_data: 'Mất dữ liệu cảm biến',
}
export const scenarioLabel = (id: string) => SCENARIO_LABEL[id] ?? id

/** Live status chips: backend link, sensor freshness/age, context snapshot age, data mode. */
export function TopBarStatus() {
  const { context, sensor, mode, scenario, pilotStation } = useLiveData()
  const now = useNow(15_000)
  const elapsed = (updatedAt: number | null) => (updatedAt ? (now - updatedAt) / 1000 : 0)

  const snapshot = context.data?.snapshot
  const offline = !!context.error && context.error === 'api_unreachable'
  const snapshotAge = snapshot ? snapshot.age_seconds + elapsed(context.updatedAt) : null
  const sensorData = sensor.data
  const sensorAge = sensorData?.age_seconds != null ? sensorData.age_seconds + elapsed(sensor.updatedAt) : null

  return (
    <div className="flex min-w-0 items-center gap-1.5 overflow-hidden" aria-live="polite">
      {offline && (
        <Chip tone="danger" icon={<WifiOff size={12} />} title={describeApiError(context.error)}>
          <span className="hidden xl:inline">Mất kết nối backend</span><span className="xl:hidden">Offline</span>
        </Chip>
      )}
              {sensorData
          ? <StateChip prefix="Cảm biến" state={sensor.error ? 'stale' : sensorData.status} suffix={sensorAge != null ? formatAge(sensorAge) : undefined}
              title={`Trạm ${pilotStation}${sensorData.latest_observed_at ? ` · đo lúc ${new Date(sensorData.latest_observed_at).toLocaleString('vi-VN')}` : ''}${sensor.error ? ` · lần tải gần nhất lỗi (${describeApiError(sensor.error)})` : ''}`} />
          : <StateChip prefix="Cảm biến" state={sensor.error ? 'unavailable' : 'loading'} title={describeApiError(sensor.error)} />}
              {snapshot
          ? <StateChip prefix="Context" state={context.error ? 'stale' : snapshot.status} suffix={formatAge(snapshotAge)} title={`Snapshot ${snapshot.snapshot_id.slice(0, 8)} · lấy lúc ${new Date(snapshot.retrieved_at).toLocaleString('vi-VN')}`} />
          : <StateChip prefix="Context" state={context.error ? 'unavailable' : 'loading'} title={describeApiError(context.error)} />}
      {mode === 'mock'
        ? <Chip tone="mock" icon={<FlaskConical size={12} />} className="mock-stripes" title="Dữ liệu khuyến nghị đang ở chế độ mô phỏng — không phải dữ liệu thật">MÔ PHỎNG · {scenarioLabel(scenario)}</Chip>
        : <Chip tone="neutral" dot title="Khuyến nghị dựng từ cảm biến + API (shadow mode, không gửi tới người nuôi)">Live · shadow</Chip>}
    </div>
  )
}
