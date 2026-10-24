import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE, ApiError } from '../api/client'

export type RefreshResult = { status: 'fresh' | 'requested' | 'pending'; snapshot_age_minutes?: number | null; requested_at?: string }
type RefreshState = { pending: boolean; requested_at: string | null; latest_retrieved_at: string | null }

/** Fired after a sync so every view re-reads its feeds (monitor layers, research pages…). */
export const SYNC_EVENT = 'hap-sync'

async function call<T>(method: 'GET' | 'POST'): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/refresh`, { method, headers: { Accept: 'application/json' } })
  } catch {
    throw new ApiError('api_unreachable', 0)
  }
  if (!response.ok) throw new ApiError(`api_${response.status}`, response.status)
  return response.json() as Promise<T>
}

export type SyncPhase = 'idle' | 'requesting' | 'waiting' | 'done' | 'fresh' | 'error'

/**
 * Ask the worker for a new environment snapshot (throttled server-side to one per 10 min), wait for it, then
 * tell every view to re-fetch. Runs once when the app opens; `sync()` is the manual "Đồng bộ" button.
 */
export function useSync(): { phase: SyncPhase; sync: () => void; lastSyncedAt: Date | null } {
  const [phase, setPhase] = useState<SyncPhase>('idle')
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null)
  const running = useRef(false)

  const finish = useCallback((next: SyncPhase) => {
    window.dispatchEvent(new Event(SYNC_EVENT))
    setLastSyncedAt(new Date())
    setPhase(next)
    running.current = false
  }, [])

  const sync = useCallback(async () => {
    if (running.current) return
    running.current = true
    setPhase('requesting')
    try {
      const result = await call<RefreshResult>('POST')
      if (result.status === 'fresh') { finish('fresh'); return }
      setPhase('waiting')
      // The worker checks every ~5 s; a regional snapshot (+ CMEMS on first use) takes up to ~2 min.
      for (let i = 0; i < 36; i++) {
        await new Promise(resolve => setTimeout(resolve, 5_000))
        const state = await call<RefreshState>('GET')
        if (!state.pending) { finish('done'); return }
      }
      finish('done')
    } catch {
      window.dispatchEvent(new Event(SYNC_EVENT))
      setPhase('error')
      running.current = false
    }
  }, [finish])

  // Opening (or reloading) the app always checks for newer data.
  useEffect(() => { void sync() }, [sync])

  return { phase, sync, lastSyncedAt }
}
