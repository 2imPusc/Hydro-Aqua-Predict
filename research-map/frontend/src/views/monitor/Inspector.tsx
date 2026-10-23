import { memo, useMemo, useState } from 'react'
import { ChevronRight, Database, FlaskConical, Info, MapPin, Radio, ShieldAlert, X } from 'lucide-react'
import type { AquacultureMap, BathymetryManifest, BathymetrySample, DataMode, FlowArtifact, HsiZones, Layer, SensorLatest, SensorObservation, Snapshot, StationNetwork, Stations } from '../../types/monitor'
import { Chip, EmptyState, IconButton, KeyValue, Note, Panel, Segmented, Skeleton, Stat, StateChip, type Tone } from '../../components/ui'
import { LABEL } from '../../components/map/mapConfig'
import { HSI_LEGACY_LABEL } from '../../components/map/overlays/HsiZonesOverlay'
import { advisoryForStation, SEVERITY_STYLE, toSeverity } from '../../components/map/overlays/StationMarkers'
import { formatAge, formatTime } from '../../hooks/useNow'
import { describeApiError } from '../../api/client'
import { scenarioLabel } from '../../app/TopBarStatus'
import type { PollState } from '../../hooks/usePolling'
import type { EnabledLayers } from './useMonitorData'

const SCENARIOS = ['normal', 'rain_wind_watch', 'nh3_watch', 'temperature_warning', 'extreme_hazard', 'oyster_danger_cobia_safe', 'missing_sensor_data']

/* ------------------------------------------------------------------ sensor */

const qcTone = (status: string): Tone => {
  const value = status.toLowerCase()
  if (['pass', 'ok', 'valid', 'good'].includes(value)) return 'ok'
  if (value.includes('suspect') || value.includes('flag') || value.includes('warn')) return 'warn'
  if (value.includes('fail') || value.includes('invalid') || value.includes('rail') || value.includes('stuck') || value.includes('reject')) return 'danger'
  return 'neutral'
}
const METRIC_ORDER = ['Temperature', 'pH', 'NH4', 'COD', 'TSS', 'DO', 'Salinity']
const formatValue = (value: number) => (Math.abs(value) >= 100 ? value.toFixed(1) : Math.abs(value) >= 10 ? value.toFixed(2) : value.toFixed(3)).replace(/\.?0+$/, '')

function SensorCard({ sensor, station }: { sensor: PollState<SensorLatest>; station: string }) {
  const data = sensor.data
  const observations = useMemo(() => [...(data?.observations ?? [])].sort((a, b) => {
    const ia = METRIC_ORDER.indexOf(a.metric), ib = METRIC_ORDER.indexOf(b.metric)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.metric.localeCompare(b.metric)
  }), [data])
  const unknownUnits = observations.some(item => item.unit === 'vendor_unit_unknown')

  return (
    <Panel variant="glass" icon={<Radio size={15} />} title={<>Cảm biến <span className="font-mono text-[11.5px] font-medium text-fg-subtle">{station}</span></>}
      actions={data ? <StateChip size="xs" state={sensor.error ? 'stale' : data.status} /> : undefined} collapsible>
      {!data && sensor.status === 'loading' && <div className="space-y-2"><Skeleton className="h-3 w-2/3" /><div className="grid grid-cols-2 gap-1.5"><Skeleton className="h-14" /><Skeleton className="h-14" /></div></div>}
      {!data && sensor.error && <EmptyState compact tone="danger" icon={<ShieldAlert size={15} />} title="Không có dữ liệu cảm biến" description={`${describeApiError(sensor.error)} — không hiển thị giá trị cũ hay giả lập.`} />}
      {data && (
        <>
          <div className="mb-2 flex items-center justify-between text-[11.5px] text-fg-subtle">
            <span>Đo lúc <b className="font-semibold text-fg tabular">{formatTime(data.latest_observed_at, true)}</b></span>
            <span className="tabular">cách {formatAge(data.age_seconds)}</span>
          </div>
          {data.status === 'unavailable' || !observations.length
            ? <EmptyState compact icon={<Database size={15} />} title="Chưa có quan trắc" description={data.reason_code ?? 'Backend chưa nhận bản ghi nào cho trạm này.'} />
            : <div className="grid grid-cols-2 gap-1.5">{observations.map(item => <ObservationStat key={item.observation_id ?? item.metric} item={item} />)}</div>}
          {data.status === 'stale' && <div className="mt-2"><Note tone="warn">Dữ liệu cũ hơn hạn tươi — đây là giá trị hợp lệ cuối cùng, không phải hiện tại.</Note></div>}
          {unknownUnits && <div className="mt-2"><Note>Đơn vị hoá chất <code className="font-mono">vendor_unit_unknown</code>: chưa có tài liệu hiệu chuẩn GreenLab, không quy đổi ngầm (đặc biệt NH4).</Note></div>}
          <p className="m-0 mt-2 text-[10.5px] text-fg-subtle">Chỉ hiển thị · chưa dùng để kích hoạt thông báo.</p>
        </>
      )}
    </Panel>
  )
}

function ObservationStat({ item }: { item: SensorObservation }) {
  const tone = qcTone(item.qc_status)
  return (
    <Stat label={item.metric} value={Number.isFinite(item.value) ? formatValue(item.value) : '—'} unit={item.unit === 'vendor_unit_unknown' ? 'đv. chưa rõ' : item.unit}
      muted={tone === 'danger'}
      status={<Chip size="xs" tone={tone} title={item.qc_reason ?? undefined}>{item.qc_status}</Chip>}
      hint={item.qc_reason ?? undefined} />
  )
}

/* ---------------------------------------------------------------- advisory */

type Driver = { metric: string; value: unknown; unit: string }

function AdvisoryCard({ aquaculture, stations, mode, onMode, scenario, onScenario }: { aquaculture: PollState<AquacultureMap>; stations: Stations | null; mode: DataMode; onMode: (mode: DataMode) => void; scenario: string; onScenario: (value: string) => void }) {
  const map = aquaculture.data
  const isMock = mode === 'mock'
  return (
    <Panel variant="glass" icon={<ShieldAlert size={15} />} title="Khuyến nghị nuôi trồng" collapsible
      actions={map ? <StateChip size="xs" state={map.mode === 'mock' ? 'mock' : map.status} /> : aquaculture.error ? <StateChip size="xs" state="unavailable" /> : <StateChip size="xs" state="loading" />}>
      <Segmented label="Chế độ dữ liệu" value={mode} onChange={onMode} options={[{ value: 'live', label: 'Live · cảm biến + API' }, { value: 'mock', label: 'Mô phỏng', tone: 'mock' }]} />
      {isMock && (
        <div className="mt-2 space-y-2">
          <Note tone="mock" icon={<FlaskConical size={13} />}><b>CHẾ ĐỘ MÔ PHỎNG</b> — kịch bản giả lập để trình diễn, không phải quan trắc thật.</Note>
          <label className="block text-[11px] font-semibold text-fg-subtle">Kịch bản
            <select value={scenario} onChange={event => onScenario(event.target.value)}
              className="mt-1 block w-full rounded-[var(--radius-sm)] border border-line bg-surface px-2 py-1.5 text-[12.5px] font-normal text-fg focus:border-mock">
              {SCENARIOS.map(id => <option key={id} value={id}>{scenarioLabel(id)}</option>)}
            </select>
          </label>
        </div>
      )}
      {map?.disclaimer && <p className="m-0 mt-2 text-[11px] italic leading-snug text-fg-subtle">{map.disclaimer}</p>}

      <div className="mt-2">
        {!map && aquaculture.error && <EmptyState compact tone="danger" icon={<ShieldAlert size={15} />} title="Không tải được bản đồ khuyến nghị" description={describeApiError(aquaculture.error)} />}
        {!map && !aquaculture.error && <div className="space-y-1.5"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>}
        {map && map.status === 'building' && <Note tone="info">Đang dựng artifact khuyến nghị…</Note>}
        {map && stations?.features.length ? (
          <ul className="scroll-thin m-0 max-h-72 list-none space-y-1 overflow-y-auto p-0 pr-0.5">
            {stations.features.map((station, index) => <StationRow key={`${String(station.properties?.station ?? '')}-${index}`} station={station} index={index} map={map} />)}
          </ul>
        ) : map && <p className="m-0 text-[11.5px] text-fg-subtle">Chưa tải được danh sách trạm.</p>}
      </div>
    </Panel>
  )
}

function StationRow({ station, index, map }: { station: GeoJSON.Feature; index: number; map: AquacultureMap }) {
  const [open, setOpen] = useState(false)
  const info = station.properties ?? {}
  const advisory = advisoryForStation(map, info.station, index)?.properties ?? {}
  const severity = toSeverity(advisory.severity)
  const style = SEVERITY_STYLE[severity]
  const drivers: Driver[] = advisory.drivers ?? []
  return (
    <li className="rounded-[var(--radius-sm)] border border-line bg-surface/60">
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="flex w-full items-center gap-2 px-2 py-1.5 text-left">
        <span className="size-2 flex-none rounded-full" style={{ background: style.color }} aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-fg" title={String(info.name ?? '')}>Trạm {String(info.station ?? '?')}</span>
        <Chip size="xs" tone={style.tone}>{style.label}</Chip>
        <ChevronRight size={14} className={`flex-none text-fg-subtle transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-line px-2 pb-2 pt-1.5 text-[11.5px] text-fg-muted">
          <div><span className="text-fg-subtle">Khu vực:</span> {String(info.name ?? 'Chưa có tên')}</div>
          {Object.keys(advisory).length > 0 && <>
            <div className="flex justify-between gap-2"><span><span className="text-fg-subtle">Áp dụng:</span> {String(advisory.species_applied ?? '—')}</span><span><span className="text-fg-subtle">Dữ liệu:</span> {String(advisory.data_status ?? 'unknown')}</span></div>
            {advisory.pilot_reference && <div><span className="text-fg-subtle">Nguồn (pilot):</span> <span className="font-mono">{String(advisory.pilot_reference?.source_station_serial ?? '')}</span></div>}
            <div className="grid grid-cols-2 gap-1 tabular">
              <MiniValue label="NH3" value={advisory.nh3_derived_mg_l} />
              <MiniValue label="Nhiệt độ" value={advisory.metrics?.Temperature} />
              <MiniValue label="Mưa 6h" value={advisory.weather?.rain_6h_mm} />
              <MiniValue label="Gió 6h" value={advisory.weather?.wind_6h_kmh} />
            </div>
          </>}
          {drivers.length > 0 && (
            <div className="rounded-[6px] bg-warn-bg px-2 py-1 text-warn">
              <b>Nguyên nhân:</b> {drivers.map(driver => `${driver.metric}: ${driver.value} ${driver.unit}`).join(' · ')}
            </div>
          )}
          {map.mode === 'live' && <div className="text-[10.5px] text-fg-subtle">Một cảm biến vật lý; các trạm khác dùng trạng thái vùng của trạm pilot.</div>}
        </div>
      )}
    </li>
  )
}

const MiniValue = ({ label, value }: { label: string; value: unknown }) => (
  <div className="flex justify-between rounded-[6px] bg-surface-2 px-1.5 py-1"><span className="text-fg-subtle">{label}</span><b className="font-semibold text-fg">{value === undefined || value === null ? '—' : String(value)}</b></div>
)

/* -------------------------------------------------------------- provenance */

function ProvenanceCard({ snapshot, contextError, layers, enabled, flow, bathymetry, network, zones }: { snapshot: Snapshot | null; contextError: string | null; layers: Layer[]; enabled: EnabledLayers; flow: FlowArtifact | null; bathymetry: BathymetryManifest | null; network: StationNetwork | null; zones: HsiZones | null }) {
  const active = layers.filter(layer => (enabled[layer.layer as keyof EnabledLayers] || (layer.layer === 'current' && enabled.flow_streamlines) || (layer.layer === 'wind' && enabled.wind_particles)))
  const bathyOn = enabled.bathymetry_bands || enabled.bathymetry_contours || enabled.bathymetry_slope
  return (
    <Panel variant="glass" icon={<Info size={15} />} title="Nguồn & độ tin cậy" collapsible defaultOpen={false}>
      <div className="space-y-3">
        <div>
          <div className="mb-1 flex items-center justify-between"><span className="text-[11.5px] font-semibold text-fg">Snapshot context</span>{snapshot ? <StateChip size="xs" state={contextError ? 'stale' : snapshot.status} /> : <StateChip size="xs" state={contextError ? 'unavailable' : 'loading'} />}</div>
          {snapshot ? <KeyValue items={[
            ['ID', <span className="font-mono">{snapshot.snapshot_id.slice(0, 12)}</span>],
            ['Lấy lúc', formatTime(snapshot.retrieved_at, true)],
            ['Tuổi', formatAge(snapshot.age_seconds)],
            ['Số lớp', snapshot.layers.length],
          ]} /> : <p className="m-0 text-[11.5px] text-fg-subtle">{contextError ? describeApiError(contextError) : 'Đang tải…'}</p>}
        </div>
        {active.map(layer => (
          <div key={layer.layer}>
            <div className="mb-1 flex items-center justify-between"><span className="text-[11.5px] font-semibold text-fg">{LABEL[layer.layer]}</span><StateChip size="xs" state={layer.status} /></div>
            <KeyValue items={[
              ['Nguồn', layer.provenance?.source],
              ['Nhà cung cấp', layer.provenance?.provider],
              layer.provenance?.product_id ? ['Sản phẩm', layer.provenance.product_id] : null,
              ['Lưới', layer.provenance?.source_grid_resolution ?? layer.provenance?.grid_resolution],
              layer.provenance?.display_grid_resolution ? ['Lưới hiển thị', layer.provenance.display_grid_resolution] : null,
              ['Hiệu lực', formatTime(layer.provenance?.valid_at, true)],
            ]} />
          </div>
        ))}
        {enabled.flow_streamlines && flow && (
          <div>
            <div className="mb-1 flex items-center justify-between"><span className="text-[11.5px] font-semibold text-fg">Artifact dòng chảy</span><StateChip size="xs" state={flow.status} /></div>
            <KeyValue items={[['Thuật toán', flow.algorithm_version], ['Chế độ', flow.mode], ['Số tia', flow.ray_count ?? flow.streamline_count], ['Cạnh tương thích', `${flow.current_supported_station_edge_count} (research only)`]]} />
            <p className="m-0 mt-1 text-[10.5px] text-fg-subtle">Lưới hiển thị không làm tăng độ phân giải mô hình dòng chảy gốc (~8 km).</p>
          </div>
        )}
        {bathyOn && bathymetry && (
          <div>
            <div className="mb-1 flex items-center justify-between"><span className="text-[11.5px] font-semibold text-fg">Độ sâu</span><StateChip size="xs" state={bathymetry.status} /></div>
            <KeyValue items={[['Nguồn', bathymetry.source], ['Độ phân giải', bathymetry.source_resolution], bathymetry.coverage_fraction != null ? ['Độ phủ', `${Math.round(bathymetry.coverage_fraction * 100)}%`] : null, ['Quy tắc chất lượng', bathymetry.quality_rule]]} />
            {bathymetry.disclaimer && <p className="m-0 mt-1 text-[10.5px] text-fg-subtle">{bathymetry.disclaimer}</p>}
          </div>
        )}
        {enabled.station_network && network && (
          <div>
            <div className="mb-1 flex items-center justify-between"><span className="text-[11.5px] font-semibold text-fg">Mạng trạm</span><StateChip size="xs" state={network.network_status} /></div>
            <KeyValue items={[['Cạnh', network.edge_count], ['Ảnh hưởng dòng chảy', network.influence_status === 'exploratory' ? 'thăm dò' : network.influence_reason ?? 'không khả dụng']]} />
          </div>
        )}
        {enabled.hsi_zones && (
          <Note tone="warn">HSI là kết quả lịch sử của luận văn — <b>{HSI_LEGACY_LABEL}</b>: độ mặn/nhiệt độ Hải Phòng trong bảng tỉnh là lưới mô hình CMEMS/GLORYS, không phải đo đạc. Không thay đổi bán kính, độ tin cậy hay cảnh báo.{zones?.observed_at ? ` Quan sát: ${formatTime(zones.observed_at, true)}.` : ''}</Note>
        )}
        <p className="m-0 text-[10.5px] text-fg-subtle">Copernicus/GEBCO chỉ xuất hiện khi đã cấu hình — không bao giờ suy ra từ nhà cung cấp khác. Thời tiết chỉ để quan sát, không kích hoạt cảnh báo.</p>
      </div>
    </Panel>
  )
}

/* -------------------------------------------------------------- bathymetry */

function SampleCard({ sample, onClose }: { sample: BathymetrySample; onClose: () => void }) {
  return (
    <Panel variant="glass" icon={<MapPin size={15} />} title="Điểm đo độ sâu" actions={<IconButton label="Đóng" onClick={onClose} className="!size-6"><X size={14} /></IconButton>}>
      {sample.status === 'available' ? (
        <>
          <div className="grid grid-cols-2 gap-1.5">
            <Stat label="Độ sâu" value={sample.copernicus_depth_m ?? '—'} unit="m" />
            <Stat label="Độ dốc" value={sample.slope_degrees ?? '—'} unit="°" />
          </div>
          <p className="m-0 mt-1.5 text-[11px] text-fg-subtle tabular">Q={sample.quality_indicator ?? '—'} · SDB={sample.sdb_type ?? '—'}{sample.depth_source ? ` · ${sample.depth_source}` : ''}</p>
          <p className="m-0 mt-0.5 text-[10.5px] text-fg-subtle">{sample.disclaimer ?? 'Chỉ dùng nghiên cứu; không dùng cho hàng hải.'}</p>
        </>
      ) : <EmptyState compact title="Không có giá trị tại điểm này" description={sample.reason_code ?? 'unavailable'} />}
    </Panel>
  )
}

/* ------------------------------------------------------------------- shell */

export type InspectorProps = {
  sensor: PollState<SensorLatest>
  station: string
  aquaculture: PollState<AquacultureMap>
  stations: Stations | null
  mode: DataMode
  onMode: (mode: DataMode) => void
  scenario: string
  onScenario: (value: string) => void
  snapshot: Snapshot | null
  contextError: string | null
  layers: Layer[]
  enabled: EnabledLayers
  flow: FlowArtifact | null
  bathymetry: BathymetryManifest | null
  network: StationNetwork | null
  zones: HsiZones | null
  sample: BathymetrySample | null
  onCloseSample: () => void
}

/** Right inspector: sensor latest, advisory (live/mock), bathymetry sample, provenance. */
export const Inspector = memo(function Inspector(props: InspectorProps) {
  return (
    <div className="scroll-thin pointer-events-auto flex max-h-full flex-col gap-2.5 overflow-y-auto pb-1 pr-0.5">
      {props.sample && <SampleCard sample={props.sample} onClose={props.onCloseSample} />}
      <SensorCard sensor={props.sensor} station={props.station} />
      <AdvisoryCard aquaculture={props.aquaculture} stations={props.stations} mode={props.mode} onMode={props.onMode} scenario={props.scenario} onScenario={props.onScenario} />
      <ProvenanceCard snapshot={props.snapshot} contextError={props.contextError} layers={props.layers} enabled={props.enabled} flow={props.flow} bathymetry={props.bathymetry} network={props.network} zones={props.zones} />
    </div>
  )
})
