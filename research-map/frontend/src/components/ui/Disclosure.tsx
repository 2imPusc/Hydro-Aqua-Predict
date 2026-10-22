import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'

type DisclosureProps = {
  /** What opens, in a few words ("Chi tiết", "Cách đọc bảng", "Nguồn & giấy phép"). */
  summary: ReactNode
  /** Optional muted hint after the label (a count, a one-word state). */
  hint?: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  className?: string
}

/**
 * Progressive disclosure on native <details>: keyboard and screen-reader
 * behaviour for free, closed by default. Used for every "Chi tiết" so
 * definitions, provenance and long notes stay one click away instead of on screen.
 */
export function Disclosure({ summary, hint, children, defaultOpen, className = '' }: DisclosureProps) {
  return (
    <details className={`disclosure group ${className}`} open={defaultOpen}>
      <summary className="inline-flex cursor-pointer select-none items-center gap-1 rounded-md py-0.5 text-[12px] font-semibold text-fg-muted hover:text-fg">
        <ChevronRight size={14} className="disclosure-chevron flex-none" aria-hidden />
        <span>{summary}</span>
        {hint != null && <span className="font-normal text-fg-subtle">{hint}</span>}
      </summary>
      <div className="mt-1.5 space-y-2 text-[12px] leading-snug text-fg-muted">{children}</div>
    </details>
  )
}
