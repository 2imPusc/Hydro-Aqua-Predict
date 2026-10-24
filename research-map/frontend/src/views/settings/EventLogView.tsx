import { useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { CircleCheck, Download, NotebookPen, Pencil, TriangleAlert, X } from 'lucide-react'
import { createEvent, eventsCsvUrl, listEvents } from '../../api/events'
import { describeApiError, isAbortError } from '../../api/client'
import { getStations } from '../../api/monitor'
import { Chip, EmptyState, Note, Panel, Select, Skeleton } from '../../components/ui'
import type { FieldEvent, FieldEventList, MeasurementKey } from '../../types/events'
import { PageScroll } from '../shared/research'
import {
  EVENT_TYPES, EVENT_TYPE_LABEL, MEASUREMENTS, MIN_EVENTS_FALLBACK, NOTE_MAX, OTHER_STATION, REJECT_REASON_VI, SEVERITIES, SEVERITY_LABEL,
  SOURCES, SOURCE_LABEL, checkDraft, describeServerError, draftFromEvent, emptyDraft, formatObserved, measurementSummary, nowVnInput,
  type Draft, type FieldKey,
} from './eventModel'

type Station = { id: string; name: string }
type Toast = { tone: 'ok' | 'danger'; message: string } | null

// Big tap targets: 44px controls, 16px text on phones (no iOS zoom on focus).
const control = 'h-11 w-full min-w-0 rounded-[var(--radius-sm)] border bg-surface px-3 text-[16px] text-fg outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] md:text-[14px]'
const bigButton = 'inline-flex h-11 items-center justify-center gap-1.5 rounded-[var(--radius-sm)] px-4 text-[14px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)] disabled:cursor-not-allowed disabled:opacity-50'
const primary = `${bigButton} bg-accent text-[var(--accent-fg)] hover:bg-accent-hover`
const secondary = `${bigButton} border border-line-strong bg-surface text-fg hover:bg-surface-2`
const SEVERITY_TONE = { 1: 'info', 2: 'warn', 3: 'danger' } as const

function Field({ label, hint, error, children, htmlFor }: { label: ReactNode; hint?: ReactNode; error?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[13px] font-semibold text-fg">{label}</label>
      {children}
      {error ? <p role="alert" className="m-0 text-[12.5px] font-medium text-danger">{error}</p> : hint ? <p className="m-0 text-[12px] text-fg-subtle">{hint}</p> : null}
    </div>
  )
}

/** Radio group of large buttons (event type, severity, source). */
function ChoiceGrid<T extends string | number>({ label, value, onChange, options, columns, error }: {
  label: string; value: T | '' | 0; onChange: (value: T) => void; options: Array<{ value: T; label: ReactNode; hint?: string }>; columns: string; error?: string
}) {
  const id = useId()
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0">
      <legend id={id} className="mb-1.5 p-0 text-[13px] font-semibold text-fg">{label}</legend>
      <div role="radiogroup" aria-labelledby={id} className={`grid gap-2 ${columns}`}>
        {options.map(option => {
          const active = option.value === value
          return (
            <button key={String(option.value)} type="button" role="radio" aria-checked={active} onClick={() => onChange(option.value)} title={option.hint}
              className={`flex min-h-11 flex-col items-start justify-center rounded-[var(--radius-sm)] border px-3 py-2 text-left text-[14px] font-semibold leading-snug transition-colors ${active ? 'border-accent bg-accent-soft text-accent' : 'border-line bg-surface text-fg hover:bg-surface-2'}`}>
              {option.label}
              {option.hint && <span className="mt-0.5 text-[11.5px] font-normal text-fg-muted">{option.hint}</span>}
            </button>
          )
        })}
      </div>
      {error && <p role="alert" className="m-0 text-[12.5px] font-medium text-danger">{error}</p>}
    </fieldset>
  )
}

function EventForm({ draft, setDraft, stations, stationsError, onSubmit, onCancelEdit, saving, errors, serverErrors, editing }: {
  draft: Draft; setDraft: (update: (draft: Draft) => Draft) => void; stations: Station[] | null; stationsError: boolean
  onSubmit: () => void; onCancelEdit: () => void; saving: boolean; errors: Partial<Record<FieldKey, string>>; serverErrors: string[]; editing: FieldEvent | null
}) {
  const ids = { time: useId(), station: useId(), other: useId(), note: useId(), reporter: useId() }
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft(current => ({ ...current, [key]: value }))
  const setMeasurement = (key: MeasurementKey, value: string) => setDraft(current => ({ ...current, measurements: { ...current.measurements, [key]: value } }))
  const border = (key: FieldKey) => (errors[key] ? 'border-danger' : 'border-line')
  return (
    <form noValidate onSubmit={event => { event.preventDefault(); onSubmit() }} className="flex flex-col gap-4">
      {editing && (
        <Note tone="info" icon={<Pencil size={13} />}>
          Đang sửa sự kiện lúc <b>{formatObserved(editing.observed_at)}</b>. Lưu sẽ tạo <b>bản ghi mới</b> thay thế; bản cũ không bị xóa và vẫn có trong file CSV.
        </Note>
      )}
      <Field label="Thời điểm quan sát (giờ Việt Nam)" htmlFor={ids.time} error={errors.observed_at} hint="Lúc thật sự thấy sự kiện, không phải lúc nhập.">
        <div className="flex gap-2">
          <input id={ids.time} type="datetime-local" required value={draft.observed_at} max={nowVnInput()} onChange={event => set('observed_at', event.target.value)} className={`${control} ${border('observed_at')}`} />
          <button type="button" className={`${secondary} flex-none`} onClick={() => set('observed_at', nowVnInput())}>Bây giờ</button>
        </div>
      </Field>

      <Field label="Điểm nuôi" htmlFor={ids.station} error={errors.station} hint={stationsError ? 'Không tải được danh sách trạm — chọn "Khác" và ghi tên.' : undefined}>
        {stations === null && !stationsError ? <Skeleton className="h-11" /> : (
          <select id={ids.station} value={draft.station_id} onChange={event => set('station_id', event.target.value)} className={`${control} ${border('station')}`}>
            <option value="">— Chọn điểm nuôi —</option>
            {(stations ?? []).map(item => <option key={item.id} value={item.id}>{item.name !== item.id ? `${item.name} (${item.id})` : item.id}</option>)}
            <option value={OTHER_STATION}>Khác (ghi tên bên dưới)</option>
          </select>
        )}
        {draft.station_id === OTHER_STATION && (
          <input id={ids.other} aria-label="Tên điểm nuôi khác" placeholder="Ví dụ: bè ông Tư, Gia Luận" maxLength={120} value={draft.station_other}
            onChange={event => set('station_other', event.target.value)} className={`${control} ${border('station')}`} />
        )}
      </Field>

      <ChoiceGrid label="Loại sự kiện" value={draft.event_type} onChange={value => set('event_type', value)} error={errors.event_type}
        columns="grid-cols-1 min-[420px]:grid-cols-2" options={EVENT_TYPES} />

      <ChoiceGrid label="Mức độ" value={draft.severity} onChange={value => set('severity', value)} error={errors.severity}
        columns="grid-cols-3" options={SEVERITIES.map(item => ({ value: item.value, label: `${item.value} · ${item.label}`, hint: item.hint }))} />

      <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
        <legend className="mb-1.5 p-0 text-[13px] font-semibold text-fg">
          Số đo tay <span className="font-normal text-fg-muted">{draft.event_type === 'do_tay' ? '(cần ít nhất một số)' : '(không bắt buộc)'}</span>
        </legend>
        <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2">
          {MEASUREMENTS.map(spec => (
            <label key={spec.key} className="flex min-w-0 flex-col gap-1">
              <span className="text-[12.5px] font-medium text-fg-muted">{spec.label} ({spec.unit})</span>
              <input type="text" inputMode="decimal" autoComplete="off" placeholder={`${spec.min}–${spec.max}`} value={draft.measurements[spec.key]}
                onChange={event => setMeasurement(spec.key, event.target.value)} aria-invalid={Boolean(errors[spec.key])} className={`${control} ${border(spec.key)} tabular`} />
              {errors[spec.key] && <span role="alert" className="text-[12px] font-medium text-danger">{errors[spec.key]}</span>}
            </label>
          ))}
        </div>
        <p className="m-0 text-[12px] text-fg-subtle">Dùng dấu phẩy cho số thập phân (5,2). Chỉ ghi số đo thật, không ước lượng.</p>
      </fieldset>

      <Field label="Ghi chú" htmlFor={ids.note} error={errors.note} hint={`${draft.note.length}/${NOTE_MAX} ký tự · lồng nào, số cá chết, màu nước, đã xử lý gì…`}>
        <textarea id={ids.note} rows={3} maxLength={NOTE_MAX} value={draft.note} onChange={event => set('note', event.target.value)}
          className={`${control} ${border('note')} h-auto min-h-[88px] py-2`} />
      </Field>

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Người báo (không bắt buộc)" htmlFor={ids.reporter} error={errors.reporter}>
          <input id={ids.reporter} maxLength={120} autoComplete="name" value={draft.reporter} onChange={event => set('reporter', event.target.value)} className={`${control} ${border('reporter')}`} />
        </Field>
        <ChoiceGrid label="Nguồn tin" value={draft.source} onChange={value => set('source', value)} error={errors.source} columns="grid-cols-3" options={SOURCES} />
      </div>

      {serverErrors.length > 0 && (
        <Note tone="danger" icon={<TriangleAlert size={13} />}>
          <div className="font-semibold">Máy chủ chưa lưu sự kiện:</div>
          <ul className="m-0 list-disc pl-4">{serverErrors.map(message => <li key={message}>{message}</li>)}</ul>
        </Note>
      )}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        {editing && <button type="button" className={secondary} onClick={onCancelEdit}>Hủy sửa</button>}
        <button type="submit" className={`${primary} sm:min-w-44`} disabled={saving}>{saving ? 'Đang lưu…' : editing ? 'Lưu bản sửa' : 'Lưu sự kiện'}</button>
      </div>
    </form>
  )
}

function EventCard({ event, stationLabel, onEdit }: { event: FieldEvent; stationLabel: string; onEdit: () => void }) {
  const measured = measurementSummary(event)
  return (
    <li className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[14px] font-semibold text-fg">{EVENT_TYPE_LABEL[event.event_type] ?? event.event_type}</span>
            <Chip size="xs" tone={SEVERITY_TONE[event.severity] ?? 'neutral'}>Mức {event.severity} · {SEVERITY_LABEL[event.severity]}</Chip>
            {event.supersedes && <Chip size="xs" tone="neutral" title={`Thay cho ${event.supersedes}`}>Đã sửa</Chip>}
          </div>
          <div className="mt-0.5 text-[12.5px] text-fg-muted tabular">{formatObserved(event.observed_at)} · {stationLabel}</div>
        </div>
        <button type="button" onClick={onEdit} className="inline-flex h-10 flex-none items-center gap-1 rounded-[var(--radius-sm)] border border-line px-3 text-[13px] font-semibold text-fg hover:bg-surface-2" aria-label={`Sửa sự kiện lúc ${formatObserved(event.observed_at)}`}>
          <Pencil size={14} aria-hidden />Sửa
        </button>
      </div>
      {measured.length > 0 && <div className="mt-1.5 text-[13px] font-medium text-fg tabular">{measured.join(' · ')}</div>}
      {event.note && <p className="m-0 mt-1.5 whitespace-pre-wrap break-words text-[13px] leading-snug text-fg">{event.note}</p>}
      <div className="mt-1.5 text-[11.5px] text-fg-subtle">{SOURCE_LABEL[event.source] ?? event.source}{event.reporter ? ` · ${event.reporter}` : ''}</div>
    </li>
  )
}

export default function EventLogView() {
  const [data, setData] = useState<FieldEventList | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [stations, setStations] = useState<Station[] | null>(null)
  const [stationsError, setStationsError] = useState(false)
  const [filterStation, setFilterStation] = useState('')
  const [filterType, setFilterType] = useState('')
  const [draft, setDraftState] = useState<Draft>(() => emptyDraft())
  const [editing, setEditing] = useState<FieldEvent | null>(null)
  const [showErrors, setShowErrors] = useState(false)
  const [serverErrors, setServerErrors] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<Toast>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoadError(null)
    listEvents({ station: filterStation || undefined, event_type: filterType || undefined }, controller.signal)
      .then(setData)
      .catch(error => { if (!isAbortError(error)) setLoadError((error as Error).message) })
    return () => controller.abort()
  }, [reloadKey, filterStation, filterType])

  useEffect(() => {
    const controller = new AbortController()
    getStations(controller.signal)
      .then(collection => setStations(collection.features
        .map(feature => ({ id: String(feature.properties?.station ?? ''), name: String(feature.properties?.name ?? feature.properties?.station ?? '') }))
        .filter(item => item.id)))
      .catch(error => { if (!isAbortError(error)) setStationsError(true) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!toast) return undefined
    const timer = window.setTimeout(() => setToast(null), 7000)
    return () => window.clearTimeout(timer)
  }, [toast])

  const setDraft = (update: (draft: Draft) => Draft) => { setDraftState(update); setServerErrors([]) }
  const { errors, payload } = useMemo(() => checkDraft(draft), [draft])
  const stationLabel = (event: FieldEvent) => event.station_id === OTHER_STATION
    ? `Khác: ${event.station_other ?? ''}`
    : stations?.find(item => item.id === event.station_id)?.name ?? event.station_id
  const minEvents = data?.min_events_for_calibration ?? MIN_EVENTS_FALLBACK
  const total = data?.total_active ?? 0
  const filtered = Boolean(filterStation || filterType)

  const submit = async () => {
    setShowErrors(true)
    if (!payload) return
    setSaving(true)
    setServerErrors([])
    try {
      const result = await createEvent(payload)
      if (result.status === 'ready') {
        setToast({ tone: 'ok', message: editing ? 'Đã lưu bản sửa (bản cũ vẫn giữ trong file CSV).' : 'Đã lưu sự kiện.' })
        // Keep where/who for the next entry from the same cage.
        setDraftState(emptyDraft({ station_id: draft.station_id, station_other: draft.station_other, reporter: draft.reporter, source: draft.source }))
        setEditing(null)
        setShowErrors(false)
        setReloadKey(key => key + 1)
      } else if (result.status === 'invalid') {
        setServerErrors(result.errors.map(describeServerError))
      } else {
        setServerErrors([REJECT_REASON_VI[result.reason] ?? result.reason])
      }
    } catch (error) {
      setServerErrors([describeApiError((error as Error).message) || 'Không gửi được'])
    } finally {
      setSaving(false)
    }
  }

  const startEdit = (event: FieldEvent) => {
    setEditing(event)
    setDraftState(draftFromEvent(event))
    setShowErrors(false)
    setServerErrors([])
    document.getElementById('event-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const cancelEdit = () => {
    setEditing(null)
    setDraftState(current => emptyDraft({ station_id: current.station_id, station_other: current.station_other, reporter: current.reporter, source: current.source }))
    setShowErrors(false)
    setServerErrors([])
  }

  const stationOptions = [
    { value: '', label: 'Tất cả điểm nuôi' },
    ...(stations ?? []).map(item => ({ value: item.id, label: item.name !== item.id ? `${item.name} (${item.id})` : item.id })),
    { value: OTHER_STATION, label: 'Khác' },
  ]
  const typeOptions = [{ value: '', label: 'Tất cả loại' }, ...EVENT_TYPES.map(item => ({ value: item.value, label: item.label }))]

  return (
    <PageScroll>
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h2 className="m-0 text-[19px] font-semibold tracking-tight text-fg">Nhật ký sự kiện ngoài lồng nuôi</h2>
          {data && (
            <Chip tone={total >= minEvents ? 'ok' : 'warn'} title="Số sự kiện hiện hành (không tính bản đã bị sửa)">
              {total} / {minEvents} sự kiện cần để hiệu chỉnh ngưỡng
            </Chip>
          )}
        </div>
        <p className="m-0 max-w-3xl text-[13px] leading-snug text-fg-muted">
          Ghi lại điều thật sự xảy ra ở lồng (cá chết, bỏ ăn, nước đổi màu, số đo tay…). Đây là dữ liệu đối chứng để biết cảnh báo shadow báo đúng, sớm hay muộn.
          Sự kiện không bao giờ bị xóa: “Sửa” tạo bản ghi mới thay thế.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
        <div id="event-form" className="scroll-mt-4">
          <Panel title={editing ? 'Sửa sự kiện' : 'Ghi sự kiện mới'} icon={<NotebookPen size={15} />}>
            <EventForm draft={draft} setDraft={setDraft} stations={stations} stationsError={stationsError} onSubmit={submit} onCancelEdit={cancelEdit}
              saving={saving} errors={showErrors ? errors : {}} serverErrors={serverErrors} editing={editing} />
          </Panel>
        </div>

        <Panel title="Đã ghi" summary={data ? `${data.count} sự kiện${filtered ? ' khớp bộ lọc' : ''} · mới nhất trước` : undefined}
          actions={<a href={eventsCsvUrl({ station: filterStation || undefined, event_type: filterType || undefined })} className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] border border-line-strong px-3 text-[13px] font-semibold text-fg no-underline hover:bg-surface-2" title="Gồm cả bản đã bị sửa (cột superseded)"><Download size={14} aria-hidden />Xuất CSV</a>}>
          <div className="mb-3 grid grid-cols-1 gap-2 min-[420px]:grid-cols-2">
            <Select label="Điểm nuôi" value={filterStation} onChange={setFilterStation} options={stationOptions} />
            <Select label="Loại sự kiện" value={filterType} onChange={setFilterType} options={typeOptions} />
          </div>
          {loadError ? (
            <EmptyState compact tone="danger" icon={<TriangleAlert size={16} />} title="Không tải được nhật ký" description={REJECT_REASON_VI[loadError] ?? describeApiError(loadError)}>
              <button type="button" className={secondary} onClick={() => setReloadKey(key => key + 1)}>Thử lại</button>
            </EmptyState>
          ) : !data ? (
            <div aria-busy="true" aria-label="Đang tải nhật ký" className="space-y-2"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
          ) : total === 0 ? (
            <EmptyState icon={<NotebookPen size={20} />} title="Chưa có sự kiện nào"
              description={<>Ngưỡng cảnh báo hiện là ngưỡng lý thuyết, chưa được kiểm chứng ngoài thực tế. Mỗi sự kiện ghi ở đây (kể cả “không có gì lạ” khi đo tay) giúp so cảnh báo với thực tế. <b>Cần ≥ {minEvents} sự kiện để hiệu chỉnh ngưỡng cảnh báo.</b></>} />
          ) : data.events.length === 0 ? (
            <EmptyState compact title="Không có sự kiện khớp bộ lọc" description="Bỏ bộ lọc để xem toàn bộ nhật ký." />
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {data.events.map(event => <EventCard key={event.event_id} event={event} stationLabel={stationLabel(event)} onEdit={() => startEdit(event)} />)}
            </ul>
          )}
          {data && data.total_superseded > 0 && (
            <p className="m-0 mt-3 text-[12px] text-fg-subtle">{data.total_superseded} bản cũ đã được sửa — ẩn ở đây, vẫn có trong file CSV.</p>
          )}
        </Panel>
      </div>

      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[1500] flex justify-center px-4 md:bottom-6 md:justify-end md:px-6" role="status" aria-live="polite">
        {toast && (
          <div className={`pointer-events-auto flex max-w-md items-start gap-2 rounded-[var(--radius-md)] border px-3 py-2.5 text-[13px] font-medium shadow-[var(--shadow-panel)] ${toast.tone === 'ok' ? 'border-[var(--ok-line)] bg-ok-bg text-ok' : 'border-[var(--danger-line)] bg-danger-bg text-danger'}`}>
            {toast.tone === 'ok' ? <CircleCheck size={16} className="mt-px flex-none" aria-hidden /> : <TriangleAlert size={16} className="mt-px flex-none" aria-hidden />}
            <span className="min-w-0 flex-1">{toast.message}</span>
            <button type="button" onClick={() => setToast(null)} aria-label="Đóng thông báo" className="-mr-1 rounded p-0.5 opacity-80 hover:opacity-100"><X size={14} aria-hidden /></button>
          </div>
        )}
      </div>
    </PageScroll>
  )
}
