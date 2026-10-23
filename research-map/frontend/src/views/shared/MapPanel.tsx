import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { ChevronUp } from 'lucide-react'
import { StatusWord, type VerdictStatus } from '../../components/ui'

const NARROW = '(max-width: 767px)'

/** One-off check (initial state): below the md breakpoint, i.e. phones. */
export const isNarrowScreen = () => typeof window !== 'undefined' && window.matchMedia(NARROW).matches

/** True below the md breakpoint (phones): map panels become a bottom sheet. */
export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia(NARROW).matches)
  useEffect(() => {
    const query = window.matchMedia(NARROW)
    const onChange = () => setNarrow(query.matches)
    query.addEventListener('change', onChange)
    onChange()
    return () => query.removeEventListener('change', onChange)
  }, [])
  return narrow
}

/** Map padding for fitBounds: desktop keeps the right panel free, phones keep the collapsed sheet free. */
export function mapInset(narrow: boolean, panelWidth: number) {
  return narrow ? { top: 56, right: 16, bottom: 240, left: 16 } : { top: 20, right: panelWidth + 30, bottom: 20, left: 20 }
}

/** Wrapper style that moves Leaflet's right/bottom controls clear of the panel (see `.map-with-panel`). */
export function mapPanelStyle(narrow: boolean, panelWidth: number): CSSProperties {
  return narrow ? {} : { ['--panel-offset' as string]: `${panelWidth + 12}px` }
}

/**
 * Panel header for map views: question → hero answer + status → one line.
 * Span-only markup because on phones it sits inside the sheet's toggle button.
 */
export function MapVerdict({ code, question, value, unit, status, answer, chips }: { code: string; question: ReactNode; value: ReactNode; unit?: ReactNode; status: VerdictStatus; answer?: ReactNode; chips?: ReactNode }) {
  return (
    <span className="block">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="rounded-[var(--radius-xs)] bg-accent-soft px-1.5 py-0.5 text-[11.5px] font-bold text-accent">{code}</span>
        <span className="text-[13px] font-medium text-fg-muted">{question}</span>
      </span>
      <span className="mt-1 flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
        <span className="text-[30px] font-semibold leading-none tracking-tight text-fg">{value}</span>
        {unit && <span className="text-[12.5px] text-fg-muted">{unit}</span>}
        <StatusWord status={status} />
      </span>
      {answer && <span className="mt-1 line-clamp-2 block text-[12.5px] leading-snug text-fg">{answer}</span>}
      {chips && <span className="mt-1.5 flex flex-wrap gap-1">{chips}</span>}
    </span>
  )
}

type Props = {
  label: string
  /** Header row: always visible, also when the phone sheet is collapsed. */
  header: ReactNode
  children: ReactNode
  width: number
}

/**
 * Floating panel over a research map. Desktop: a glass column on the right.
 * Phones: a bottom sheet whose header (title + verdict) stays visible and
 * whose body opens on demand, so the map is never fully covered.
 */
export function MapPanel({ label, header, children, width }: Props) {
  const narrow = useNarrow()
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  const sheet = useRef<HTMLElement | null>(null)
  // Phones: keep Leaflet's bottom controls just above the sheet, whatever its height.
  useEffect(() => {
    const element = sheet.current
    if (!narrow || !element?.parentElement) return undefined
    const parent = element.parentElement
    const observer = new ResizeObserver(() => parent.style.setProperty('--panel-bottom', `${element.offsetHeight}px`))
    observer.observe(element)
    return () => { observer.disconnect(); parent.style.removeProperty('--panel-bottom') }
  }, [narrow])
  if (!narrow) {
    return (
      <aside aria-label={label} style={{ width }} className="glass panel-enter scroll-thin absolute bottom-3 right-3 top-3 z-[800] flex flex-col gap-3 overflow-y-auto rounded-[var(--radius-lg)] p-3.5">
        {header}
        {children}
      </aside>
    )
  }
  return (
    <aside ref={sheet} aria-label={label} className="glass panel-enter absolute inset-x-0 bottom-0 z-[800] flex max-h-[72%] flex-col rounded-t-[var(--radius-lg)]">
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls={bodyId}
        className="flex flex-none flex-col items-stretch gap-2 px-3.5 pb-2 pt-2 text-left">
        <span className="sheet-handle self-center" aria-hidden />
        <span className="flex items-start gap-2">
          <span className="min-w-0 flex-1">{header}</span>
          <ChevronUp size={18} aria-hidden className={`mt-0.5 flex-none text-fg-subtle transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
        </span>
        <span className="sr-only">{open ? 'Thu gọn bảng' : 'Mở bảng chi tiết'}</span>
      </button>
      {open && <div id={bodyId} className="scroll-thin flex min-h-0 flex-col gap-3 overflow-y-auto border-t border-line px-3.5 pb-4 pt-3">{children}</div>}
    </aside>
  )
}
