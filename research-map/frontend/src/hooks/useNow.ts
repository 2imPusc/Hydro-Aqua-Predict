import { useEffect, useState } from 'react'

/** Current time, re-rendering every `intervalMs` while the tab is visible (for relative ages). */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    let timer: number | undefined
    const start = () => { if (timer === undefined) timer = window.setInterval(() => setNow(Date.now()), intervalMs) }
    const stop = () => { if (timer !== undefined) { window.clearInterval(timer); timer = undefined } }
    const onVisibility = () => { if (document.hidden) stop(); else { setNow(Date.now()); start() } }
    document.addEventListener('visibilitychange', onVisibility)
    if (!document.hidden) start()
    return () => { stop(); document.removeEventListener('visibilitychange', onVisibility) }
  }, [intervalMs])
  return now
}

/** "45 giây", "12 phút", "3 giờ", "2 ngày". */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} giây`
  if (s < 3600) return `${Math.round(s / 60)} phút`
  if (s < 86_400) return `${Math.round(s / 3600)} giờ`
  return `${Math.round(s / 86_400)} ngày`
}

export function formatTime(iso: string | null | undefined, withDate = false): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('vi-VN', withDate
    ? { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }
    : { hour: '2-digit', minute: '2-digit' })
}
