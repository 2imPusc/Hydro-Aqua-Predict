import type { ReactNode } from 'react'

export type Tone = 'ok' | 'warn' | 'danger' | 'info' | 'mock' | 'neutral' | 'accent'

const TONE_CLASS: Record<Tone, string> = {
  ok: 'text-ok bg-ok-bg border-[var(--ok-line)]',
  warn: 'text-warn bg-warn-bg border-[var(--warn-line)]',
  danger: 'text-danger bg-danger-bg border-[var(--danger-line)]',
  info: 'text-info bg-info-bg border-[var(--info-line)]',
  mock: 'text-mock bg-mock-bg border-[var(--mock-line)]',
  neutral: 'text-neutral bg-neutral-bg border-[var(--neutral-line)]',
  accent: 'text-accent bg-accent-soft border-transparent',
}

/** Maps every provenance/freshness state used across views to a tone + Vietnamese label. */
export const STATE_META: Record<string, { tone: Tone; label: string }> = {
  live: { tone: 'ok', label: 'Trực tiếp' },
  fresh: { tone: 'ok', label: 'Mới' },
  ready: { tone: 'ok', label: 'Sẵn sàng' },
  available: { tone: 'ok', label: 'Có dữ liệu' },
  stale: { tone: 'warn', label: 'Cũ' },
  cache: { tone: 'warn', label: 'Bộ đệm' },
  building: { tone: 'info', label: 'Đang dựng' },
  loading: { tone: 'neutral', label: 'Đang tải' },
  exploratory: { tone: 'info', label: 'Thăm dò' },
  research_only: { tone: 'info', label: 'Chỉ nghiên cứu' },
  mock: { tone: 'mock', label: 'Mô phỏng' },
  legacy: { tone: 'neutral', label: 'Legacy' },
  withdrawn: { tone: 'neutral', label: 'Đã rút' },
  unavailable: { tone: 'danger', label: 'Không khả dụng' },
  offline: { tone: 'danger', label: 'Mất kết nối' },
}

export function stateMeta(state: string | null | undefined) {
  return STATE_META[state ?? 'loading'] ?? { tone: 'neutral' as Tone, label: String(state) }
}

type ChipProps = {
  tone?: Tone
  children: ReactNode
  icon?: ReactNode
  dot?: boolean
  pulse?: boolean
  size?: 'xs' | 'sm'
  title?: string
  className?: string
}

/** Compact status chip. Text always carries the meaning; colour only reinforces it. */
export function Chip({ tone = 'neutral', children, icon, dot, pulse, size = 'sm', title, className = '' }: ChipProps) {
  const sizing = size === 'xs' ? 'h-5 px-1.5 text-[10.5px] gap-1' : 'h-6 px-2 text-[11.5px] gap-1.5'
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-full border font-semibold leading-none tracking-[.01em] ${sizing} ${TONE_CLASS[tone]} ${className}`}>
      {dot && <span className={`live-dot ${pulse ? 'is-pulsing' : ''}`} aria-hidden />}
      {icon}
      {children}
    </span>
  )
}

/** Chip for a known data state (fresh/stale/mock/…), optional suffix such as an age. */
export function StateChip({ state, suffix, size, title, label, prefix }: { state: string | null | undefined; suffix?: ReactNode; size?: 'xs' | 'sm'; title?: string; label?: string; prefix?: ReactNode }) {
  const meta = stateMeta(state)
  return (
    <Chip tone={meta.tone} dot pulse={state === 'live' || state === 'fresh'} size={size} title={title}>
      {prefix ? <span className="font-medium opacity-75">{prefix}</span> : null}{label ?? meta.label}{suffix ? <span className="font-medium opacity-80">· {suffix}</span> : null}
    </Chip>
  )
}
