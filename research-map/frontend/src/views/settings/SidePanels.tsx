import { useEffect, useId, useState } from 'react'
import { Eye, History, RotateCcw, Save, Undo2 } from 'lucide-react'
import { getAlertConfigVersion, isInvalid, previewAlertConfig, saveAlertConfig } from '../../api/admin'
import { describeApiError, isAbortError } from '../../api/client'
import { Chip, Panel, Skeleton } from '../../components/ui'
import type { AlertConfig, AlertConfigChange, AlertConfigVersion, AlertConfigVersionDetail, TierExample } from '../../types/alerts'
import { TierBadge } from './HazardCard'
import { describePath, fmt, scopeName, toPayload, type Scope, type ScopeIssue } from './model'

const timeFormat = new Intl.DateTimeFormat('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
export const formatTime = (iso: string | undefined) => {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : timeFormat.format(date)
}

const button = 'inline-flex h-8 items-center justify-center gap-1.5 rounded-[var(--radius-sm)] px-3 text-[12.5px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus)] disabled:cursor-not-allowed disabled:opacity-50'
export const primaryButton = `${button} bg-accent text-[var(--accent-fg)] hover:bg-accent-hover`
export const secondaryButton = `${button} border border-line-strong bg-surface text-fg hover:bg-surface-2`

/** Changes as old → new rows, grouped by nothing: the list is short and ordered by path. */
export function ChangeList({ changes, config, stationName, empty }: { changes: AlertConfigChange[]; config: AlertConfig | null; stationName: (id: string) => string; empty: string }) {
  if (!changes.length) return <p className="m-0 text-[12px] text-fg-subtle">{empty}</p>
  return (
    <ul className="m-0 max-h-72 list-none space-y-1.5 overflow-y-auto p-0 pr-1 scroll-thin">
      {changes.map(change => {
        const label = describePath(change.path, config, stationName)
        const text = typeof change.new === 'string' || typeof change.old === 'string'
        // Override paths: an absent side means "inherits the default", so show that value instead of a dash.
        const parts = change.path.split('.')
        const inherited = parts[0] === 'scopes'
          ? (config?.hazards[parts[3]]?.[parts[4] as 'thresholds'] as Record<string, unknown> | undefined)?.[parts[5]]
          : undefined
        const side = (value: unknown) => (value === null && parts[0] === 'scopes' ? `mặc định ${fmt(inherited)}` : fmt(value))
        return (
          <li key={change.path} className="rounded-[var(--radius-sm)] bg-surface-2 px-2 py-1.5 text-[12px] leading-snug">
            <div className="flex flex-wrap items-baseline gap-x-1.5">
              <span className="font-semibold text-fg">{label.hazard}</span>
              <span className="text-fg-muted">{label.field}</span>
              {label.scope !== 'Mặc định' && <span className="text-accent">· {label.scope}</span>}
            </div>
            {text
              ? <div className="mt-0.5 text-fg-muted"><span className="line-through decoration-fg-subtle">{side(change.old)}</span><br /><span className="text-fg">{side(change.new)}</span></div>
              : <div className="mt-0.5 tabular text-fg-muted">{side(change.old)} <span aria-label="thành">→</span> <strong className="text-fg">{side(change.new)}</strong></div>}
          </li>
        )
      })}
    </ul>
  )
}

type EditPanelProps = {
  draft: AlertConfig
  base: AlertConfig
  changes: AlertConfigChange[]
  issues: ScopeIssue[]
  stationName: (id: string) => string
  onDiscard: () => void
  onSaved: (version: string) => void
  /** Open the scope an issue belongs to (an edit to the default can break an override). */
  onJump: (scope: Scope) => void
}

/** Unsaved changes → preview (server) → save with a required reason. */
export function EditPanel({ draft, base, changes, issues, stationName, onDiscard, onSaved, onJump }: EditPanelProps) {
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const [changedBy, setChangedBy] = useState('')
  const [preview, setPreview] = useState<{ errors: string[]; examples: TierExample[]; forKey: string } | null>(null)
  const [busy, setBusy] = useState<'preview' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [serverErrors, setServerErrors] = useState<string[]>([])
  const draftKey = JSON.stringify(draft)
  const dirty = changes.length > 0
  const valid = issues.length === 0
  const stalePreview = preview && preview.forKey !== draftKey

  useEffect(() => { setServerErrors([]) }, [draftKey])

  const runPreview = async () => {
    setBusy('preview'); setError(null)
    try {
      const result = await previewAlertConfig(toPayload(draft))
      setPreview({ errors: result.errors ?? [], examples: isInvalid(result) ? [] : result.tier_examples ?? [], forKey: draftKey })
    } catch (caught) {
      if (!isAbortError(caught)) setError(describeApiError((caught as Error).message))
    } finally { setBusy(null) }
  }

  const save = async () => {
    setBusy('save'); setError(null); setServerErrors([])
    try {
      const result = await saveAlertConfig(toPayload(draft), reason.trim(), changedBy.trim() || undefined)
      if (isInvalid(result)) { setServerErrors(result.errors); return }
      setReason(''); setPreview(null)
      onSaved(result.config_version)
    } catch (caught) {
      setError(describeApiError((caught as Error).message))
    } finally { setBusy(null) }
  }

  const byHazard = new Map<string, TierExample[]>()
  for (const example of preview?.examples ?? []) byHazard.set(example.hazard, [...(byHazard.get(example.hazard) ?? []), example])

  return (
    <Panel title="Thay đổi chưa lưu" summary={dirty ? `${changes.length} mục` : 'Chưa có'} actions={dirty ? (
      <button type="button" onClick={onDiscard} className="inline-flex h-6 items-center gap-1 rounded-full px-2 text-[11.5px] font-semibold text-fg-muted hover:bg-surface-2 hover:text-fg"><Undo2 size={12} aria-hidden />Bỏ hết</button>
    ) : undefined}>
      <ChangeList changes={changes} config={base} stationName={stationName} empty="Chỉnh một ngưỡng hoặc hành động ở bên trái." />

      {issues.length > 0 && (
        <div role="alert" className="mt-2.5 rounded-[var(--radius-sm)] border border-[var(--danger-line)] bg-danger-bg px-2.5 py-2 text-[12px] text-danger">
          <strong className="font-semibold">{issues.length} lỗi cần sửa trước khi lưu</strong>
          <ul className="m-0 mt-1 list-disc space-y-0.5 pl-4">
            {issues.slice(0, 5).map((issue, index) => (
              <li key={index}>
                <button type="button" onClick={() => onJump(issue.scope)} className="text-left underline decoration-dotted underline-offset-2 hover:decoration-solid">
                  {draft.hazards[issue.hazard]?.label_vi ?? issue.hazard}{issue.scope.kind !== 'default' ? ` (${scopeName(issue.scope, stationName)})` : ''}
                </button>: {issue.message}
              </li>
            ))}
            {issues.length > 5 && <li>… và {issues.length - 5} lỗi khác</li>}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={secondaryButton} onClick={runPreview} disabled={!dirty || !valid || busy !== null} aria-busy={busy === 'preview'}>
          <Eye size={14} aria-hidden />{busy === 'preview' ? 'Đang xem trước…' : 'Xem trước'}
        </button>
      </div>

      {preview && (
        <div className={`mt-2.5 space-y-2 ${stalePreview ? 'opacity-60' : ''}`} aria-live="polite">
          {stalePreview && <p className="m-0 text-[11.5px] text-fg-subtle">Đã sửa sau lần xem trước — bấm Xem trước lại.</p>}
          {preview.errors.length > 0
            ? <ul role="alert" className="m-0 list-disc space-y-0.5 pl-4 text-[12px] text-danger">{preview.errors.map(item => <li key={item}>{item}</li>)}</ul>
            : <p className="m-0 text-[12px] font-semibold text-ok">Máy chủ kiểm tra: hợp lệ</p>}
          {byHazard.size > 0 && (
            <table className="w-full border-collapse text-[12px]">
              <caption className="pb-1 text-left text-[11.5px] text-fg-subtle">Giá trị ví dụ sẽ được xếp bậc</caption>
              <tbody>
                {[...byHazard.entries()].map(([hazard, examples]) => (
                  <tr key={hazard} className="border-t border-line align-top">
                    <th scope="row" className="py-1 pr-2 text-left font-medium text-fg-muted">{draft.hazards[hazard]?.label_vi ?? hazard}</th>
                    <td className="py-1">
                      <div className="flex flex-wrap gap-1">
                        {examples.map((example, index) => (
                          <span key={index} className="inline-flex items-center gap-1 tabular">
                            <span className="text-fg">{fmt(example.value)}</span><TierBadge tiers={draft.tiers} tier={example.tier} compact />
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <form className="mt-3 space-y-2 border-t border-line pt-3" onSubmit={event => { event.preventDefault(); if (dirty && valid && reason.trim() && busy === null) void save() }}>
        <label htmlFor={reasonId} className="block text-[12px] font-semibold text-fg-muted">Lý do thay đổi <span className="text-danger" aria-hidden>*</span></label>
        <textarea id={reasonId} required rows={2} value={reason} onChange={event => setReason(event.target.value)} placeholder="Ví dụ: hạ ngưỡng gió bậc 2 theo góp ý của người nuôi"
          className="w-full resize-y rounded-[var(--radius-sm)] border border-line-strong bg-surface px-2 py-1.5 text-[12.5px] text-fg outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]" />
        <label className="block">
          <span className="text-[12px] font-semibold text-fg-muted">Người sửa <span className="font-normal text-fg-subtle">(tuỳ chọn)</span></span>
          <input value={changedBy} onChange={event => setChangedBy(event.target.value)} placeholder="admin-ui" autoComplete="name"
            className="mt-1 h-8 w-full rounded-[var(--radius-sm)] border border-line-strong bg-surface px-2 text-[12.5px] text-fg outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]" />
        </label>
        {serverErrors.length > 0 && (
          <ul role="alert" className="m-0 list-disc space-y-0.5 pl-4 text-[12px] text-danger">{serverErrors.map(item => <li key={item}>{item}</li>)}</ul>
        )}
        {error && <p role="alert" className="m-0 text-[12px] font-medium text-danger">{error}</p>}
        <button type="submit" className={`${primaryButton} w-full`} disabled={!dirty || !valid || !reason.trim() || busy !== null} aria-busy={busy === 'save'}>
          <Save size={14} aria-hidden />{busy === 'save' ? 'Đang lưu…' : 'Lưu phiên bản'}
        </button>
        <p className="m-0 text-[11.5px] text-fg-subtle">Mỗi lần lưu tạo một phiên bản mới; phiên bản cũ giữ nguyên.</p>
      </form>
    </Panel>
  )
}

type HistoryProps = {
  versions: AlertConfigVersion[] | null
  error: string | null
  current: string | undefined
  base: AlertConfig | null
  stationName: (id: string) => string
  onRestore: (version: AlertConfigVersionDetail) => void
}

/** Saved versions newest first; open one to see its changes and load it into the editor. */
export function HistoryPanel({ versions, error, current, base, stationName, onRestore }: HistoryProps) {
  const [open, setOpen] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ id: string; data?: AlertConfigVersionDetail; error?: string } | null>(null)

  useEffect(() => {
    if (!open) return undefined
    const controller = new AbortController()
    setDetail({ id: open })
    getAlertConfigVersion(open, controller.signal)
      .then(result => setDetail(result.status === 'ready' && result.version ? { id: open, data: result.version } : { id: open, error: result.reason ?? 'Không đọc được phiên bản' }))
      .catch(caught => { if (!isAbortError(caught)) setDetail({ id: open, error: describeApiError((caught as Error).message) }) })
    return () => controller.abort()
  }, [open])

  const list = [...(versions ?? [])].reverse()
  return (
    <Panel title="Lịch sử phiên bản" icon={<History size={15} />} summary={versions ? `${versions.length} phiên bản đã lưu` : undefined} collapsible defaultOpen>
      {error && <p role="alert" className="m-0 text-[12px] text-danger">{error}</p>}
      {!versions && !error && <div className="space-y-1.5"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>}
      {versions && !list.length && <p className="m-0 text-[12px] text-fg-subtle">Chưa có phiên bản nào — đang dùng ngưỡng mặc định.</p>}
      <ol className="m-0 list-none space-y-1 p-0">
        {list.map(item => {
          const expanded = open === item.config_version
          return (
            <li key={item.config_version} className={`rounded-[var(--radius-sm)] border ${expanded ? 'border-line-strong bg-surface-2' : 'border-transparent'}`}>
              <button type="button" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : item.config_version)}
                className="flex w-full flex-col gap-0.5 rounded-[var(--radius-sm)] px-2 py-1.5 text-left hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-[var(--focus)]">
                <span className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[11.5px] font-semibold text-fg">{item.config_version}</span>
                  {item.config_version === current && <Chip tone="ok" size="xs">Đang dùng</Chip>}
                  <span className="ml-auto text-[11px] tabular text-fg-subtle">{item.n_changes} thay đổi</span>
                </span>
                <span className="line-clamp-2 text-[12px] text-fg-muted">{item.reason_vi || '—'}</span>
                <span className="text-[11px] text-fg-subtle">{formatTime(item.changed_at)} · {item.changed_by || 'không ghi'}</span>
              </button>
              {expanded && (
                <div className="space-y-2 px-2 pb-2">
                  {!detail?.data && !detail?.error && <Skeleton className="h-10" />}
                  {detail?.error && <p role="alert" className="m-0 text-[12px] text-danger">{describeApiError(detail.error)}</p>}
                  {detail?.data && (
                    <>
                      <ChangeList changes={detail.data.changes ?? []} config={base} stationName={stationName} empty="Phiên bản không ghi danh sách thay đổi." />
                      {detail.data.parent_version && <p className="m-0 text-[11px] text-fg-subtle">Từ <span className="font-mono">{detail.data.parent_version}</span></p>}
                      <button type="button" className={`${secondaryButton} w-full`} onClick={() => onRestore(detail.data!)}>
                        <RotateCcw size={14} aria-hidden />Khôi phục phiên bản này
                      </button>
                    </>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}
