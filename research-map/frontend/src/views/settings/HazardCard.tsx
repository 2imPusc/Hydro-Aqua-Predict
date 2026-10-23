import { useEffect, useId, useState } from 'react'
import { BookOpen, RotateCcw } from 'lucide-react'
import { Chip, Disclosure } from '../../components/ui'
import type { AlertConfig, EditableField, HazardConfig } from '../../types/alerts'
import { EVIDENCE_SUMMARY } from './evidence'
import { fmt, isOverridden, tierKeys, validateHazard, type FieldErrors, type Scope } from './model'

type TierMeta = AlertConfig['tiers'][number]
type ToneKey = 'ok' | 'info' | 'warn' | 'danger' | 'neutral'

/** Literal class strings per status tone (Tailwind needs them verbatim). */
const TINT: Record<ToneKey, string> = {
  ok: 'bg-ok-bg text-ok border-[var(--ok-line)]',
  info: 'bg-info-bg text-info border-[var(--info-line)]',
  warn: 'bg-warn-bg text-warn border-[var(--warn-line)]',
  danger: 'bg-danger-bg text-danger border-[var(--danger-line)]',
  neutral: 'bg-neutral-bg text-neutral border-[var(--neutral-line)]',
}
const SOLID: Record<ToneKey, string> = {
  ok: 'bg-ok text-[var(--fg-inverse)] border-transparent',
  info: 'bg-info text-[var(--fg-inverse)] border-transparent',
  warn: 'bg-warn text-[var(--fg-inverse)] border-transparent',
  danger: 'bg-danger text-[var(--fg-inverse)] border-transparent',
  neutral: 'bg-neutral text-[var(--fg-inverse)] border-transparent',
}
const toneOf = (color: string | undefined): ToneKey => (color && color in TINT ? color as ToneKey : 'neutral')

/**
 * Tier styling from config `tiers`. A tier whose colour repeats a lower tier's
 * (3 and 4 are both "danger") is drawn solid, so the two never differ by text alone.
 */
export function tierClass(tiers: TierMeta[], tier: number): string {
  const meta = tiers.find(item => item.tier === tier)
  const tone = toneOf(meta?.color)
  const repeated = tiers.some(item => item.tier < tier && toneOf(item.color) === tone)
  return repeated ? SOLID[tone] : TINT[tone]
}
export const tierLabel = (tiers: TierMeta[], tier: number) => tiers.find(item => item.tier === tier)?.label_vi ?? `Bậc ${tier}`

export function TierBadge({ tiers, tier, compact }: { tiers: TierMeta[]; tier: number | null; compact?: boolean }) {
  if (tier == null) return <span className="inline-flex h-5 items-center rounded-full border border-line px-1.5 text-[11px] font-semibold text-fg-muted">Không xếp bậc</span>
  return (
    <span className={`inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full border px-1.5 text-[11px] font-semibold ${tierClass(tiers, tier)}`}>
      <span className="tabular">{tier}</span>{!compact && <span>{tierLabel(tiers, tier)}</span>}
    </span>
  )
}

const sign = (direction: HazardConfig['direction']) => (direction === 'ge' ? '≥' : '≤')
const below = (direction: HazardConfig['direction']) => (direction === 'ge' ? '<' : '>')

/** Horizontal tier scale in severity order (left = bình thường). Equal-width segments; each carries its number, label and boundary. */
function TierScale({ hazard, tiers, overridden, errors }: { hazard: HazardConfig; tiers: TierMeta[]; overridden: Set<string>; errors: FieldErrors }) {
  const keys = tierKeys(hazard)
  const first = hazard.thresholds[keys[0]]
  const segments = [
    { tier: 0, bound: `${below(hazard.direction)} ${fmt(first)}`, key: '0' },
    ...keys.map(key => ({ tier: Number(key), bound: `${sign(hazard.direction)} ${fmt(hazard.thresholds[key])}`, key })),
  ]
  const summary = segments.map(item => `bậc ${item.tier} ${tierLabel(tiers, item.tier)}: ${item.bound} ${hazard.unit}`).join('; ')
  return (
    <div>
      <div className="flex gap-[2px]" role="img" aria-label={`Thang bậc: ${summary}`}>
        {segments.map((item, index) => {
          const changed = overridden.has(item.key)
          const invalid = !!errors[`thresholds.${item.key}`]
          return (
            <div key={item.key} title={`Bậc ${item.tier} · ${tierLabel(tiers, item.tier)} · ${item.bound} ${hazard.unit}`}
              className={`relative min-w-0 flex-1 border px-1.5 py-1 ${tierClass(tiers, item.tier)} ${index === 0 ? 'rounded-l-[var(--radius-sm)]' : ''} ${index === segments.length - 1 ? 'rounded-r-[var(--radius-sm)]' : ''} ${invalid ? 'outline outline-2 -outline-offset-2 outline-[var(--danger)]' : ''}`}>
              <div className="flex min-w-0 items-baseline gap-1 text-[11px] font-semibold leading-tight">
                <span className="tabular">{item.tier}</span>
                {segments.length < 5 && <span className="hidden truncate sm:inline">{tierLabel(tiers, item.tier)}</span>}
              </div>
              <div className="truncate text-[12.5px] font-bold leading-tight tabular">{item.bound}</div>
              {changed && <span className="absolute right-1 top-1 size-1.5 rounded-full bg-current" aria-hidden />}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Text input that keeps in-progress text ("0,", "") but reports a number (NaN when not a number). */
function NumberInput({ value, onChange, label, invalid, describedBy, integer, placeholder, className = '' }: {
  value: number | undefined; onChange: (value: number | undefined) => void; label: string; invalid?: boolean; describedBy?: string; integer?: boolean; placeholder?: string; className?: string
}) {
  const toText = (number: number | null | undefined) => (number == null || Number.isNaN(number) ? '' : String(number).replace('.', ','))
  const [text, setText] = useState(() => toText(value))
  // Resync only when the value changed from outside (restore, reset, scope switch), not while typing.
  useEffect(() => {
    const parsed = text.trim() === '' ? undefined : Number(text.replace(',', '.'))
    const equal = parsed === value || (Number.isNaN(parsed ?? NaN) && Number.isNaN(value ?? NaN))
    if (!equal) setText(toText(value))
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <input type="text" inputMode={integer ? 'numeric' : 'decimal'} value={text} aria-label={label} aria-invalid={invalid || undefined} aria-describedby={describedBy} placeholder={placeholder}
      onChange={event => {
        const next = event.target.value
        setText(next)
        if (next.trim() === '') onChange(undefined)
        else onChange(Number(next.replace(',', '.')))
      }}
      className={`h-8 w-full min-w-0 rounded-[var(--radius-sm)] border bg-surface px-2 text-right text-[13px] font-semibold tabular text-fg outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] ${invalid ? 'border-[var(--danger)]' : 'border-line-strong'} ${className}`} />
  )
}

type Props = {
  id: string
  hazard: HazardConfig
  base: HazardConfig
  tiers: TierMeta[]
  config: AlertConfig
  scope: Scope
  onSet: (field: EditableField, tier: string, value: number | string | undefined) => void
  onResetOverride?: () => void
}

/** One hazard: scale → threshold rows (guardrails, persistence) → actions (collapsed) → evidence. */
export function HazardCard({ id, hazard, base, tiers, config, scope, onSet, onResetOverride }: Props) {
  const headingId = useId()
  const errors = validateHazard(hazard)
  const keys = tierKeys(hazard)
  const inScope = scope.kind !== 'default'
  const overridden = new Set(keys.filter(key => isOverridden(config, scope, id, 'thresholds', key) || isOverridden(config, scope, id, 'persistence_days', key)))
  const actionsOverridden = keys.filter(key => isOverridden(config, scope, id, 'actions_vi', key)).length
  const hasPersistence = !!base.persistence_days
  const errorCount = Object.keys(errors).length
  const anyOverride = overridden.size + actionsOverridden > 0

  return (
    <section aria-labelledby={headingId} className={`min-w-0 rounded-[var(--radius-lg)] border bg-surface p-3.5 shadow-[var(--shadow-sm)] md:p-4 ${errorCount ? 'border-[var(--danger-line)]' : 'border-line'}`}>
      <header className="mb-2.5 flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="m-0 text-[14.5px] font-semibold leading-snug text-fg">{hazard.label_vi}</h2>
          <p className="m-0 text-[12px] text-fg-subtle">
            Bậc tăng khi giá trị <strong className="font-semibold text-fg-muted">{sign(hazard.direction)} ngưỡng</strong> · đơn vị {hazard.unit}
          </p>
        </div>
        <div className="flex flex-none flex-wrap items-center gap-1.5">
          {errorCount > 0 && <Chip tone="danger" size="xs">{errorCount} lỗi</Chip>}
          {inScope && anyOverride && <Chip tone="accent" size="xs">Ghi đè {overridden.size + actionsOverridden}</Chip>}
          {inScope && anyOverride && onResetOverride && (
            <button type="button" onClick={onResetOverride} className="inline-flex h-6 items-center gap-1 rounded-full border border-line px-2 text-[11.5px] font-semibold text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-[var(--focus)]">
              <RotateCcw size={12} aria-hidden />Về mặc định
            </button>
          )}
        </div>
      </header>

      <TierScale hazard={hazard} tiers={tiers} overridden={overridden} errors={errors} />

      <div className="mt-3 divide-y divide-line">
        {keys.map(key => {
          const tier = Number(key)
          const thresholdError = errors[`thresholds.${key}`]
          const persistError = errors[`persistence_days.${key}`]
          const min = hazard.guardrails?.min?.[key], max = hazard.guardrails?.max?.[key]
          const thresholdOverridden = isOverridden(config, scope, id, 'thresholds', key)
          const persistOverridden = isOverridden(config, scope, id, 'persistence_days', key)
          const errorId = `${headingId}-err-${key}`
          return (
            <div key={key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2 sm:grid-cols-[8rem_7rem_minmax(0,1fr)_auto]">
              <div className="col-span-2 sm:col-span-1"><TierBadge tiers={tiers} tier={tier} /></div>
              <label className="flex min-w-0 items-center gap-1.5">
                <span className="w-4 flex-none text-center text-[13px] font-semibold text-fg-muted" aria-hidden>{sign(hazard.direction)}</span>
                <NumberInput value={hazard.thresholds[key]} onChange={value => onSet('thresholds', key, value ?? NaN)}
                  label={`Ngưỡng bậc ${tier} (${hazard.unit})`} invalid={!!thresholdError} describedBy={thresholdError ? errorId : undefined}
                  className={thresholdOverridden ? '!border-accent ring-1 ring-[var(--accent)]' : ''} />
              </label>
              <div className="min-w-0 text-[11.5px] leading-tight text-fg-subtle">
                {(min != null || max != null) && <span className="whitespace-nowrap tabular">Cho phép {fmt(min)}–{fmt(max)}</span>}
                {inScope && thresholdOverridden && <span className="block whitespace-nowrap text-accent">Mặc định {fmt(base.thresholds[key])}</span>}
              </div>
              {hasPersistence ? (
                <label className="flex items-center gap-1.5 justify-self-end">
                  <span className="w-16">
                    <NumberInput integer value={hazard.persistence_days?.[key]} onChange={value => onSet('persistence_days', key, value)}
                      label={`Số ngày liên tục bậc ${tier}`} placeholder="—" invalid={!!persistError}
                      className={persistOverridden ? '!border-accent ring-1 ring-[var(--accent)]' : ''} />
                  </span>
                  <span className="text-[11.5px] text-fg-subtle">ngày</span>
                </label>
              ) : <span className="hidden sm:block" />}
              {(thresholdError || persistError) && (
                <p id={errorId} role="alert" className="col-span-full m-0 text-[12px] font-medium text-danger">{thresholdError ?? persistError}</p>
              )}
            </div>
          )
        })}
      </div>
      {hasPersistence && <p className="m-0 mt-1 text-[11.5px] text-fg-subtle">“Ngày” = số ngày liên tục phải vượt ngưỡng mới lên bậc; để trống = không cần.</p>}

      <div className="mt-2 flex flex-col gap-1.5">
        <Disclosure summary="Hành động theo bậc" hint={actionsOverridden ? `· ghi đè ${actionsOverridden}` : `· ${keys.length} bậc`}>
          <div className="space-y-2.5">
            {keys.map(key => {
              const error = errors[`actions_vi.${key}`]
              const changed = isOverridden(config, scope, id, 'actions_vi', key)
              return (
                <label key={key} className="block">
                  <span className="mb-1 flex items-center gap-2"><TierBadge tiers={tiers} tier={Number(key)} />{changed && <span className="text-[11px] font-semibold text-accent">Ghi đè</span>}</span>
                  <textarea value={hazard.actions_vi?.[key] ?? ''} rows={2} onChange={event => onSet('actions_vi', key, event.target.value)}
                    aria-invalid={!!error || undefined}
                    className={`w-full resize-y rounded-[var(--radius-sm)] border bg-surface px-2 py-1.5 text-[12.5px] leading-snug text-fg outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] ${error ? 'border-[var(--danger)]' : changed ? 'border-accent' : 'border-line-strong'}`} />
                  {error && <span className="text-[12px] font-medium text-danger">{error}</span>}
                </label>
              )
            })}
          </div>
        </Disclosure>
        {!!hazard.evidence?.length && (
          <Disclosure summary={<span className="inline-flex items-center gap-1"><BookOpen size={13} aria-hidden />Bằng chứng</span>} hint={`· ${hazard.evidence.length} tài liệu`}>
            <ul className="m-0 list-none space-y-2 p-0">
              {hazard.evidence.map(path => (
                <li key={path}>
                  <code className="break-all font-mono text-[11.5px] text-fg">{path}</code>
                  {EVIDENCE_SUMMARY[path] && <p className="m-0 mt-0.5 text-[12px] leading-snug text-fg-muted">{EVIDENCE_SUMMARY[path]}</p>}
                </li>
              ))}
              <li className="text-[11.5px] text-fg-subtle">Lý thuyết, chưa kiểm chứng hiện trường.</li>
            </ul>
          </Disclosure>
        )}
      </div>
    </section>
  )
}
