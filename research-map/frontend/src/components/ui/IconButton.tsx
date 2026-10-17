import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode; variant?: 'ghost' | 'glass'; pressed?: boolean }

/** Square icon-only button; `label` becomes aria-label and tooltip. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton({ label, children, variant = 'ghost', pressed, className = '', ...rest }, ref) {
  const surface = variant === 'glass' ? 'glass text-fg hover:text-accent' : 'text-fg-muted hover:bg-surface-3 hover:text-fg'
  return (
    <button ref={ref} type="button" aria-label={label} title={label} aria-pressed={pressed}
      className={`grid size-8 flex-none place-items-center rounded-[var(--radius-sm)] transition-colors duration-150 ${surface} ${pressed ? 'text-accent' : ''} ${className}`} {...rest}>
      {children}
    </button>
  )
})

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />
}
