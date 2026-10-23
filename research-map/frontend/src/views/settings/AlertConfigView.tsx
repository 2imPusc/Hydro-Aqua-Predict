import { useCallback, useEffect, useMemo, useState } from 'react'
import { BellOff, CircleCheck, LockOpen, SlidersHorizontal, TriangleAlert, X } from 'lucide-react'
import { getAlertConfig, getAlertConfigVersions } from '../../api/admin'
import { describeApiError, isAbortError } from '../../api/client'
import { getStations } from '../../api/monitor'
import { Chip, EmptyState, Segmented, Select, Skeleton, Tabs } from '../../components/ui'
import type { AlertConfig, AlertConfigResponse, AlertConfigVersion, AlertConfigVersionDetail, EditableField, ExposureClass } from '../../types/alerts'
import { PageScroll } from '../shared/research'
import { HazardCard } from './HazardCard'
import { EditPanel, HistoryPanel, secondaryButton } from './SidePanels'
import {
  CLASSES, CLASS_LABEL, clone, countOverrides, diffConfig, mergedHazard, resetHazardOverride, restoreFrom, setLeaf, validateConfig, type Scope,
} from './model'

type ScopeTab = 'default' | 'class' | 'station'
type Station = { id: string; name: string }
type Toast = { tone: 'ok' | 'info'; message: string } | null

const LEAVE_PROMPT = 'Có thay đổi chưa lưu. Rời trang và bỏ các thay đổi này?'

/** Blocks leaving with unsaved edits: tab close/reload and in-app hash links. */
function useLeaveGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return undefined
    const onBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    const onClick = (event: MouseEvent) => {
      const anchor = (event.target as Element | null)?.closest?.('a[href^="#/"]')
      const href = anchor?.getAttribute('href')
      if (!href || href.startsWith('#/settings')) return
      if (!window.confirm(LEAVE_PROMPT)) { event.preventDefault(); event.stopPropagation() }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('click', onClick, true)
    return () => { window.removeEventListener('beforeunload', onBeforeUnload); document.removeEventListener('click', onClick, true) }
  }, [dirty])
}

export default function AlertConfigView() {
  const [response, setResponse] = useState<AlertConfigResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [draft, setDraft] = useState<AlertConfig | null>(null)
  const [versions, setVersions] = useState<AlertConfigVersion[] | null>(null)
  const [versionsError, setVersionsError] = useState<string | null>(null)
  const [stations, setStations] = useState<Station[] | null>(null)
  const [stationsError, setStationsError] = useState(false)
  const [tab, setTab] = useState<ScopeTab>('default')
  const [classId, setClassId] = useState<ExposureClass>('exposed')
  const [stationId, setStationId] = useState('')
  const [toast, setToast] = useState<Toast>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const base = response?.status === 'ready' ? response.effective ?? null : null

  useEffect(() => {
    const controller = new AbortController()
    setLoadError(null)
    getAlertConfig(controller.signal)
      .then(result => { setResponse(result); setDraft(result.effective ? clone(result.effective) : null) })
      .catch(error => { if (!isAbortError(error)) setLoadError((error as Error).message) })
    getAlertConfigVersions(controller.signal)
      .then(result => { setVersions(result.versions ?? []); setVersionsError(result.status === 'ready' ? null : result.reason ?? 'Không đọc được lịch sử') })
      .catch(error => { if (!isAbortError(error)) setVersionsError(describeApiError((error as Error).message)) })
    return () => controller.abort()
  }, [reloadKey])

  useEffect(() => {
    const controller = new AbortController()
    getStations(controller.signal)
      .then(collection => {
        const list = collection.features
          .map(feature => ({ id: String(feature.properties?.station ?? ''), name: String(feature.properties?.name ?? feature.properties?.station ?? '') }))
          .filter(item => item.id)
        setStations(list)
        setStationId(current => current || list[0]?.id || '')
      })
      .catch(error => { if (!isAbortError(error)) setStationsError(true) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!toast) return undefined
    const timer = window.setTimeout(() => setToast(null), 7000)
    return () => window.clearTimeout(timer)
  }, [toast])

  const stationName = useCallback((id: string) => stations?.find(item => item.id === id)?.name ?? id, [stations])
  const changes = useMemo(() => (base && draft ? diffConfig(base, draft) : []), [base, draft])
  const issues = useMemo(() => (draft ? validateConfig(draft) : []), [draft])
  const dirty = changes.length > 0
  useLeaveGuard(dirty)

  const scope: Scope = tab === 'class' ? { kind: 'class', id: classId } : tab === 'station' && stationId ? { kind: 'station', id: stationId } : { kind: 'default' }
  const scopeKey = scope.kind === 'default' ? 'default' : `${scope.kind}:${scope.id}`

  if (loadError || (response && response.status !== 'ready')) {
    return (
      <PageScroll>
        <EmptyState tone="danger" icon={<TriangleAlert size={22} />} title="Không đọc được cấu hình cảnh báo"
          description={loadError ? describeApiError(loadError) : `Máy chủ trả về: ${response?.reason ?? response?.status}`}>
          <button type="button" className={secondaryButton} onClick={() => setReloadKey(key => key + 1)}>Thử lại</button>
        </EmptyState>
      </PageScroll>
    )
  }
  if (!base || !draft) {
    return <PageScroll><div aria-busy="true" aria-label="Đang tải cấu hình" className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-48" /><Skeleton className="h-48" /></div></PageScroll>
  }

  const classCounts = Object.fromEntries(CLASSES.map(id => [id, countOverrides(draft.scopes?.exposure_class?.[id])])) as Record<ExposureClass, number>
  const stationCounts = Object.fromEntries(Object.entries(draft.scopes?.station ?? {}).map(([id, overrides]) => [id, countOverrides(overrides)]))
  const totalClass = Object.values(classCounts).reduce((sum, value) => sum + value, 0)
  const totalStation = Object.values(stationCounts).reduce((sum, value) => sum + value, 0)
  const badge = (count: number) => count > 0 ? <span className="rounded-full bg-accent-soft px-1.5 text-[10.5px] font-bold text-accent tabular">{count}</span> : null

  const set = (id: string) => (field: EditableField, tier: string, value: number | string | undefined) =>
    setDraft(current => (current ? setLeaf(current, scope, id, field, tier, value) : current))
  const restore = (version: AlertConfigVersionDetail) => {
    if (dirty && !window.confirm('Thay các chỉnh sửa chưa lưu bằng nội dung phiên bản này?')) return
    setDraft(restoreFrom(base, version))
    setToast({ tone: 'info', message: `Đã nạp ${version.config_version} vào trình chỉnh. Lưu để áp dụng thành phiên bản mới.` })
  }
  const onSaved = (version: string) => {
    setToast({ tone: 'ok', message: `Đã lưu phiên bản ${version}` })
    setReloadKey(key => key + 1)
  }

  return (
    <PageScroll>
      {/* Answer first: which thresholds are live, and that nothing is sent. */}
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h2 className="m-0 text-[19px] font-semibold tracking-tight text-fg">
            Đang áp dụng <span className="font-mono text-[16px]">{response?.config_version ?? base.config_version}</span>
          </h2>
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip tone={response?.source === 'runtime' ? 'accent' : 'neutral'} title={response?.source === 'runtime' ? 'Phiên bản admin đã lưu (runtime/alert-config/)' : 'Ngưỡng mặc định (config/alert_tiers.default.json)'}>
              {response?.source === 'runtime' ? 'Đã chỉnh' : 'Mặc định'}
            </Chip>
            <Chip tone="info" icon={<BellOff size={12} aria-hidden />} title="Cảnh báo chỉ ghi log để chấm điểm, không gửi tới người nuôi">Shadow · không gửi thông báo</Chip>
            {dirty && <Chip tone="warn" icon={<TriangleAlert size={12} aria-hidden />}>Chưa lưu · {changes.length}</Chip>}
          </div>
        </div>
        <p className="m-0 flex items-center gap-1.5 text-[12px] text-fg-subtle">
          <LockOpen size={13} aria-hidden className="flex-none" />Chưa có phân quyền — mọi người mở trang đều chỉnh được (giai đoạn shadow)
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <div className="flex min-w-0 flex-col gap-3">
          <Tabs<ScopeTab> label="Phạm vi áp dụng" value={tab} onChange={setTab} tabs={[
            { value: 'default', label: 'Mặc định' },
            { value: 'class', label: 'Theo lớp vị trí', badge: badge(totalClass) },
            { value: 'station', label: 'Theo trạm', badge: badge(totalStation) },
          ]} />

          {tab === 'class' && (
            <div className="flex flex-col gap-1.5">
              <div className="max-w-md">
                <Segmented<ExposureClass> label="Lớp vị trí" value={classId} onChange={setClassId}
                  options={CLASSES.map(id => ({ value: id, label: <span>{CLASS_LABEL[id]}{classCounts[id] ? <span className="ml-1 text-accent tabular">· {classCounts[id]}</span> : null}</span> }))} />
              </div>
              <p className="m-0 text-[12px] text-fg-subtle">Chỉ ghi đè ô cần khác; ô viền xanh khác mặc định.</p>
            </div>
          )}
          {tab === 'station' && (
            <div className="flex flex-col gap-1.5">
              {stations && stations.length > 0 ? (
                <div className="max-w-sm">
                  <Select label="Trạm" value={stationId} onChange={setStationId}
                    options={stations.map(item => ({ value: item.id, label: `${stationCounts[item.id] ? '● ' : ''}${item.name}${item.name !== item.id ? ` (${item.id})` : ''}` }))} />
                </div>
              ) : stationsError ? (
                <p role="alert" className="m-0 text-[12px] text-danger">Không tải được danh sách trạm.</p>
              ) : <Skeleton className="h-[30px] max-w-sm" />}
              <p className="m-0 text-[12px] text-fg-subtle">Trạm ưu tiên hơn lớp vị trí. Ở đây so với mặc định; lớp của trạm do máy chủ ghép.</p>
            </div>
          )}

          <div role="tabpanel" aria-label="Các loại nguy cơ" className="grid gap-3 xl:grid-cols-2">
            {(tab !== 'station' || scope.kind === 'station') && Object.keys(draft.hazards).map(id => (
              <HazardCard key={`${scopeKey}:${id}`} id={id} config={draft} scope={scope} tiers={draft.tiers}
                hazard={mergedHazard(draft, scope, id)} base={draft.hazards[id]} onSet={set(id)}
                onResetOverride={scope.kind === 'default' ? undefined : () => setDraft(current => (current ? resetHazardOverride(current, scope, id) : current))} />
            ))}
          </div>
        </div>

        <aside className="flex min-w-0 flex-col gap-3 lg:sticky lg:top-0" aria-label="Lưu và lịch sử">
          <EditPanel draft={draft} base={base} changes={changes} issues={issues} stationName={stationName}
            onDiscard={() => { if (window.confirm('Bỏ mọi thay đổi chưa lưu?')) setDraft(clone(base)) }} onSaved={onSaved}
            onJump={target => {
              if (target.kind === 'class') { setTab('class'); setClassId(target.id) }
              else if (target.kind === 'station') { setTab('station'); setStationId(target.id) }
              else setTab('default')
            }} />
          <HistoryPanel versions={versions} error={versionsError} current={response?.config_version} base={base} stationName={stationName} onRestore={restore} />
        </aside>
      </div>

      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[1500] flex justify-center px-4 md:bottom-6 md:justify-end md:px-6" role="status" aria-live="polite">
        {toast && (
          <div className={`pointer-events-auto flex max-w-md items-start gap-2 rounded-[var(--radius-md)] border px-3 py-2.5 text-[13px] font-medium shadow-[var(--shadow-panel)] ${toast.tone === 'ok' ? 'border-[var(--ok-line)] bg-ok-bg text-ok' : 'border-[var(--info-line)] bg-info-bg text-info'}`}>
            {toast.tone === 'ok' ? <CircleCheck size={16} className="mt-px flex-none" aria-hidden /> : <SlidersHorizontal size={16} className="mt-px flex-none" aria-hidden />}
            <span className="min-w-0 flex-1">{toast.message}</span>
            <button type="button" onClick={() => setToast(null)} aria-label="Đóng thông báo" className="-mr-1 rounded p-0.5 opacity-80 hover:opacity-100"><X size={14} aria-hidden /></button>
          </div>
        )}
      </div>
    </PageScroll>
  )
}
