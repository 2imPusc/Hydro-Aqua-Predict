import { useCallback, useEffect, useRef, useState } from 'react'
import { isAbortError } from '../api/client'

export type PollStatus = 'idle' | 'loading' | 'ready' | 'building' | 'gave_up' | 'error'

export type PollOptions<T> = {
  /** Regular refresh interval once data is ready; `null` = fetch once. */
  intervalMs?: number | null
  /** When false nothing is fetched (and in-flight requests are aborted). */
  enabled?: boolean
  /** Restart (and by default reset data) when any of these change. */
  deps?: readonly unknown[]
  /** Server-side artifact still being produced → retry on `buildingIntervalMs`. */
  isBuilding?: (data: T) => boolean
  buildingIntervalMs?: number
  /** Stop the fast "building" retries after this many attempts. */
  maxBuildingRetries?: number
  /** Error retries use exponential backoff from `retryBaseMs` up to `maxBackoffMs`. */
  retryBaseMs?: number
  maxBackoffMs?: number
  /** Give up after this many consecutive errors (`Infinity` keeps trying with backoff). */
  maxErrorRetries?: number
  /** Keep the last good value when a deps change restarts polling. */
  keepPreviousData?: boolean
  /** Drop the last good value on error (e.g. advisory maps that must not look current). */
  clearOnError?: boolean
}

export type PollState<T> = {
  data: T | null
  error: string | null
  status: PollStatus
  /** epoch ms of the last successful response */
  updatedAt: number | null
  refresh: () => void
}

/**
 * Visibility-aware polling:
 * - one AbortController per request; aborted on unmount / deps change / tab hidden
 * - paused while `document.hidden`, refetches immediately when visible again
 * - exponential backoff on errors, bounded retries for "building" artifacts
 * - never sets state after unmount
 */
export function usePolling<T>(fetcher: (signal: AbortSignal) => Promise<T>, options: PollOptions<T> = {}): PollState<T> {
  const {
    intervalMs = null, enabled = true, deps = [], isBuilding, buildingIntervalMs = 10_000, maxBuildingRetries = 30,
    retryBaseMs = 4_000, maxBackoffMs = 120_000, maxErrorRetries = Infinity, keepPreviousData = false, clearOnError = false,
  } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<PollStatus>(enabled ? 'loading' : 'idle')
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [nonce, setNonce] = useState(0)

  // Latest callbacks without restarting the effect on every render.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const isBuildingRef = useRef(isBuilding)
  isBuildingRef.current = isBuilding

  useEffect(() => {
    if (!keepPreviousData) { setData(null); setUpdatedAt(null) }
    setError(null)
    if (!enabled) { setStatus('idle'); return undefined }
    setStatus('loading')

    let disposed = false
    let timer: number | undefined
    let controller: AbortController | null = null
    let pausedWhileHidden = false
    let errorCount = 0
    let buildingCount = 0

    const schedule = (delay: number | null) => {
      if (disposed || delay === null) return
      timer = window.setTimeout(tick, delay)
    }

    async function tick() {
      timer = undefined
      if (disposed) return
      if (document.hidden) { pausedWhileHidden = true; return }
      controller = new AbortController()
      try {
        const value = await fetcherRef.current(controller.signal)
        if (disposed) return
        errorCount = 0
        setData(value)
        setError(null)
        setUpdatedAt(Date.now())
        if (isBuildingRef.current?.(value)) {
          buildingCount += 1
          if (buildingCount > maxBuildingRetries) { setStatus('gave_up'); schedule(intervalMs) }
          else { setStatus('building'); schedule(buildingIntervalMs) }
        } else {
          buildingCount = 0
          setStatus('ready')
          schedule(intervalMs)
        }
      } catch (caught) {
        if (disposed || isAbortError(caught)) return
        errorCount += 1
        setError(caught instanceof Error ? caught.message : String(caught))
        setStatus('error')
        if (clearOnError) setData(null)
        if (errorCount <= maxErrorRetries) schedule(Math.min(maxBackoffMs, retryBaseMs * 2 ** (errorCount - 1)))
      } finally {
        controller = null
      }
    }

    const onVisibility = () => {
      if (document.hidden) {
        // Abort and pause; the next tick happens when the tab is visible again.
        if (controller) { controller.abort(); controller = null; pausedWhileHidden = true }
        if (timer !== undefined) { window.clearTimeout(timer); timer = undefined; pausedWhileHidden = true }
      } else if (pausedWhileHidden) {
        pausedWhileHidden = false
        tick()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    tick()

    return () => {
      disposed = true
      document.removeEventListener('visibilitychange', onVisibility)
      if (timer !== undefined) window.clearTimeout(timer)
      controller?.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, nonce, ...deps])

  const refresh = useCallback(() => setNonce(value => value + 1), [])
  return { data, error, status, updatedAt, refresh }
}
