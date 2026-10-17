import { useEffect, useRef, useState } from 'react'

/** Width of an element, kept in sync with ResizeObserver (charts redraw on resize). */
export function useElementWidth<T extends HTMLElement>(fallback = 480) {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const element = ref.current
    if (!element) return undefined
    setWidth(element.clientWidth || fallback)
    const observer = new ResizeObserver(entries => {
      const next = Math.round(entries[0]?.contentRect.width ?? 0)
      if (next > 0) setWidth(next)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [fallback])
  return [ref, width] as const
}
