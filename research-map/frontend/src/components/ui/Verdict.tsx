import type { ReactNode } from 'react'
import { ToneIcon, type Tone } from './Chip'

export type VerdictStatus = { tone: Tone; label: string; icon?: ReactNode }

type VerdictProps = {
  /** The one question this view answers, in plain words. */
  question: ReactNode
  status: VerdictStatus
  /** Hero figure or word (exactly one per view). */
  value: ReactNode
  unit?: ReactNode
  /** One line: what the figure means. */
  answer?: ReactNode
  /** Secondary facts, rendered as small tiles beside/below the hero. */
  facts?: Array<{ label: ReactNode; value: ReactNode; status?: VerdictStatus; hint?: ReactNode }>
  children?: ReactNode
  compact?: boolean
  className?: string
}

const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-ok', warn: 'text-warn', danger: 'text-danger', info: 'text-info', mock: 'text-mock', neutral: 'text-neutral', accent: 'text-accent',
}
const TONE_BAR: Record<Tone, string> = {
  ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger', info: 'bg-info', mock: 'bg-mock', neutral: 'bg-neutral', accent: 'bg-accent',
}

/** Status word with its shape icon; colour reinforces, text carries the meaning. */
export function StatusWord({ status, size = 'sm' }: { status: VerdictStatus; size?: 'sm' | 'xs' }) {
  return (
    <span className={`inline-flex items-center gap-1 font-semibold ${TONE_TEXT[status.tone]} ${size === 'xs' ? 'text-[11.5px]' : 'text-[12.5px]'}`}>
      {status.icon ?? <ToneIcon tone={status.tone} size={size === 'xs' ? 12 : 14} />}
      {status.label}
    </span>
  )
}

/**
 * The answer card that opens every view: question → status → one hero figure
 * → one line of meaning, with a few secondary facts. Details live in a
 * Disclosure passed as children, never as prose on the card.
 */
export function Verdict({ question, status, value, unit, answer, facts = [], children, compact, className = '' }: VerdictProps) {
  return (
    <section className={`relative overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-sm)] ${className}`}>
      <span className={`absolute inset-y-0 left-0 w-1 ${TONE_BAR[status.tone]}`} aria-hidden />
      <div className={`flex flex-wrap items-stretch gap-x-6 gap-y-3 ${compact ? 'px-3.5 py-3' : 'px-5 py-4'}`}>
        <div className="min-w-[220px] flex-[2_1_320px]">
          <h2 className="m-0 text-[13px] font-medium text-fg-muted">{question}</h2>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={`hero-figure text-fg ${compact ? '!text-[36px]' : ''}`}>{value}</span>
            {unit && <span className="text-[14px] font-medium text-fg-muted">{unit}</span>}
            <StatusWord status={status} />
          </div>
          {answer && <p className="m-0 mt-1.5 line-clamp-2 max-w-[62ch] text-[13px] leading-snug text-fg">{answer}</p>}
        </div>
        {facts.length > 0 && (
          <dl className="m-0 grid min-w-0 flex-[3_1_360px] grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2 self-center">
            {facts.map((fact, index) => (
              <div key={index} className="min-w-0 rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2">
                <dt className="truncate text-[12px] text-fg-muted">{fact.label}</dt>
                <dd className="m-0 mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[18px] font-semibold leading-tight text-fg">
                  {fact.value}
                  {fact.status && <StatusWord status={fact.status} size="xs" />}
                </dd>
                {fact.hint && <div className="mt-0.5 truncate text-[11.5px] text-fg-subtle">{fact.hint}</div>}
              </div>
            ))}
          </dl>
        )}
      </div>
      {children && <div className={`border-t border-line ${compact ? 'px-3.5 py-2' : 'px-5 py-2.5'}`}>{children}</div>}
    </section>
  )
}
