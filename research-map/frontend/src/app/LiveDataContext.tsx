import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { getFlowArtifact, getLatestContext, getSensorLatest } from '../api/monitor'
import { getApiStatus } from '../api/research'
import { isAbortError } from '../api/client'
import { usePolling, type PollState } from '../hooks/usePolling'
import type { DataMode, FlowArtifact, Layer, SensorLatest, Snapshot } from '../types/monitor'
import type { ApiStatus } from '../types/research'

export type ContextBundle = { snapshot: Snapshot; flow: FlowArtifact | null }

type LiveData = {
  pilotStation: string
  /** Light shell status (`/api/v1/status`), polled on every view for the top bar. */
  status: PollState<ApiStatus>
  /** Full context snapshot + sensor feeds: only polled while the monitoring view is open. */
  context: PollState<ContextBundle>
  sensor: PollState<SensorLatest>
  mode: DataMode
  setMode: (mode: DataMode) => void
  scenario: string
  setScenario: (scenario: string) => void
}

const LiveDataContext = createContext<LiveData | null>(null)

export const PILOT_STATION: string = import.meta.env.VITE_SENSOR_STATION_SERIAL || '06M26042804'
const CONTEXT_POLL_MS = 20_000
const SENSOR_POLL_MS = 60_000
const STATUS_POLL_MS = 20_000

/**
 * Re-use layer objects from the previous poll when the snapshot is unchanged,
 * so memoized overlays and particle canvases are not rebuilt every 20 s.
 */
function stabilizeLayers(next: Snapshot, previous: Snapshot | null): Snapshot {
  if (!previous || previous.snapshot_id !== next.snapshot_id) return next
  const byName = new Map<string, Layer>(previous.layers.map(layer => [layer.layer, layer]))
  let reused = 0
  const layers = next.layers.map(layer => {
    const old = byName.get(layer.layer)
    if (old && old.status === layer.status && old.kind === layer.kind && old.reason_code === layer.reason_code) { reused += 1; return old }
    return layer
  })
  return { ...next, layers: reused === next.layers.length && layers.length === previous.layers.length ? previous.layers : layers }
}

/**
 * App-wide live feeds. The light `/status` poll always runs (top bar); the full
 * environmental snapshot (+ flow artifact) and the pilot sensor are polled only
 * while the monitoring view is mounted, so research views do not download the
 * whole snapshot every 20 s.
 */
export function LiveDataProvider({ children, monitorActive }: { children: ReactNode; monitorActive: boolean }) {
  const [mode, setMode] = useState<DataMode>('live')
  const [scenario, setScenario] = useState('normal')
  const previous = useRef<ContextBundle | null>(null)

  const context = usePolling<ContextBundle>(async signal => {
    const snapshot = stabilizeLayers(await getLatestContext(signal), previous.current?.snapshot ?? null)
    let flow: FlowArtifact | null = null
    // The flow artifact is immutable per snapshot; fetch it only when the snapshot changes.
    if (previous.current?.flow && previous.current.flow.snapshot_id === snapshot.snapshot_id) flow = previous.current.flow
    else {
      try {
        const artifact = await getFlowArtifact(snapshot.snapshot_id, signal)
        if (artifact.snapshot_id === snapshot.snapshot_id) flow = artifact
      } catch (error) {
        if (isAbortError(error)) throw error
      }
    }
    const bundle = { snapshot, flow }
    previous.current = bundle
    return bundle
  }, { intervalMs: CONTEXT_POLL_MS, enabled: monitorActive, keepPreviousData: true, retryBaseMs: 5_000, maxBackoffMs: 60_000 })

  const sensor = usePolling(signal => getSensorLatest(PILOT_STATION, signal), { intervalMs: SENSOR_POLL_MS, enabled: monitorActive, keepPreviousData: true, retryBaseMs: 10_000 })

  const status = usePolling(signal => getApiStatus(PILOT_STATION, signal), { intervalMs: STATUS_POLL_MS, keepPreviousData: true, retryBaseMs: 5_000, maxBackoffMs: 60_000 })

  const value = useMemo<LiveData>(() => ({ pilotStation: PILOT_STATION, status, context, sensor, mode, setMode, scenario, setScenario }), [status, context, sensor, mode, scenario])
  return <LiveDataContext.Provider value={value}>{children}</LiveDataContext.Provider>
}

export function useLiveData(): LiveData {
  const value = useContext(LiveDataContext)
  if (!value) throw new Error('useLiveData must be used inside LiveDataProvider')
  return value
}
