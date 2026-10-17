import type { ReactNode } from 'react'

type EmptyStateProps = {
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  compact?: boolean
  tone?: 'neutral' | 'danger' | 'info'
}

/** Explicit "nothing to show" state with the reason. Never replaced by fabricated values. */
export function EmptyState({ icon, title, description, children, compact, tone = 'neutral' }: EmptyStateProps) {
  const iconTone = tone === 'danger' ? 'text-danger bg-danger-bg' : tone === 'info' ? 'text-info bg-info-bg' : 'text-fg-subtle bg-surface-3'
  return (
    <div role="status" className={`flex flex-col items-center text-center ${compact ? 'gap-1.5 py-4' : 'gap-3 py-12'}`}>
      {icon && <div className={`grid place-items-center rounded-full ${iconTone} ${compact ? 'size-8' : 'size-12'}`} aria-hidden>{icon}</div>}
      <div className={`font-semibold text-fg ${compact ? 'text-[12.5px]' : 'text-[16px]'}`}>{title}</div>
      {description && <div className={`max-w-md text-fg-muted ${compact ? 'text-[11.5px]' : 'text-[13px]'}`}>{description}</div>}
      {children}
    </div>
  )
}
