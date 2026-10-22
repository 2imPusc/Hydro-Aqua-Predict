import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PanelRightClose, PanelRightOpen, RefreshCw, WifiOff } from 'lucide-react'
import { useLiveData } from '../../app/LiveDataContext'
import { getBathymetrySample } from '../../api/monitor'
import { API_BASE, describeApiError, isAbortError } from '../../api/client'
import { IconButton } from '../../components/ui'
import { lodForZoom, MAP_ZOOM, type BasemapId, type Lod } from '../../components/map/mapConfig'
import type { BathymetrySample } from '../../types/monitor'
import type { Theme } from '../../hooks/useTheme'
import { Inspector } from './Inspector'
import { LayerControl } from './LayerControl'
import { MapLegends } from './MapLegends'
import { MonitorMap } from './MonitorMap'
import { DEFAULT_LAYERS, ENVIRONMENT_LAYERS, useMonitorData, type EnabledLayers, type LayerKey } from './useMonitorData'

const INSPECTOR_W = 344
const readBasemap = (): BasemapId => { try { return localStorage.getItem('hap-basemap') === 'street' ? 'street' : 'canvas' } catch { return 'canvas' } }

export default function MonitorView({ theme }: { theme: Theme }) {
  const { context, sensor, pilotStation, mode, setMode, scenario, setScenario } = useLiveData()
  const [enabled, setEnabled] = useState<EnabledLayers>(DEFAULT_LAYERS)
  const [lod, setLod] = useState<Lod>(lodForZoom(MAP_ZOOM))
  const [basemap, setBasemap] = useState<BasemapId>(readBasemap)
  const [inspectorOpen, setInspectorOpen] = useState(() => window.innerWidth >= 1280)
  const [sample, setSample] = useState<BathymetrySample | null>(null)
  const sampleController = useRef<AbortController | null>(null)

  const data = useMonitorData({ enabled, lod, mode, scenario })
  const snapshot = context.data?.snapshot ?? null
  const flow = context.data?.flow ?? null

  const allLayers = useMemo(() => snapshot?.layers ?? [], [snapshot?.layers])
  const environmentLayers = useMemo(() => allLayers.filter(layer => layer.layer !== 'wind' && layer.layer !== 'current' && layer.layer !== 'bathymetry'), [allLayers])
  const currentLayer = useMemo(() => allLayers.find(layer => layer.layer === 'current'), [allLayers])
  const windLayer = useMemo(() => allLayers.find(layer => layer.layer === 'wind'), [allLayers])

  const onToggle = useCallback((key: LayerKey, value: boolean) => setEnabled(current => {
    if ((ENVIRONMENT_LAYERS as readonly string[]).includes(key)) {
      return { ...current, ...Object.fromEntries(ENVIRONMENT_LAYERS.map(layer => [layer, layer === key ? value : false])) }
    }
    return { ...current, [key]: value }
  }), [])

  const onSample = useCallback((latitude: number, longitude: number) => {
    sampleController.current?.abort()
    const controller = new AbortController()
    sampleController.current = controller
    getBathymetrySample(longitude, latitude, controller.signal).then(setSample).catch(error => {
      if (!isAbortError(error)) setSample({ status: 'unavailable', reason_code: 'sample_request_failed' })
    })
  }, [])
  useEffect(() => () => sampleController.current?.abort(), [])
  const closeSample = useCallback(() => setSample(null), [])

  const onBasemap = useCallback((value: BasemapId) => {
    setBasemap(value)
    try { localStorage.setItem('hap-basemap', value) } catch { /* not remembered */ }
  }, [])

  const backendDown = context.error === 'api_unreachable' && !snapshot
  const retry = useCallback(() => { context.refresh(); sensor.refresh(); data.refreshAll() }, [context, sensor, data])

  return (
    <div className="monitor-map absolute inset-0 overflow-hidden" style={{ ['--inspector-offset' as string]: inspectorOpen ? `${INSPECTOR_W + 12}px` : '0px' }}>
      <MonitorMap
        theme={theme} basemap={basemap} enabled={enabled} snapshotId={snapshot?.snapshot_id ?? null}
        environmentLayers={environmentLayers} currentLayer={currentLayer} windLayer={windLayer} flow={flow}
        stations={data.stations.data} aquacultureMap={data.aquaculture.data} domain={data.domain.data} network={data.network.data}
        zones={data.zones.data} bands={data.bands.data} contours={data.contours.data}
        isobands={data.isobands.data} isobaths={data.isobaths.data} depthFlags={data.depthFlags.data}
        lod={lod} onLod={setLod} onSample={onSample}
      />

      {/* Left column: layer control (shrinks/scrolls) above legends. */}
      <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-[800] flex flex-col justify-between gap-3">
        <LayerControl enabled={enabled} onToggle={onToggle} environmentLayers={environmentLayers} snapshotLoaded={!!snapshot}
          flow={flow} currentLayer={currentLayer} windLayer={windLayer} network={data.network.data} zones={data.zones.data}
          bathymetry={data.bathymetry.data} bathymetryError={data.bathymetry.error} etopo={data.etopo.data} lod={lod} basemap={basemap} onBasemap={onBasemap} />
        <MapLegends enabled={enabled} environmentLayers={environmentLayers} mockMode={mode === 'mock'} theme={theme} etopo={data.etopo.data} />
      </div>

      {backendDown && (
        <div role="alert" className="glass panel-enter absolute left-1/2 top-3 z-[850] flex max-w-[min(520px,calc(100%-700px))] min-w-[300px] -translate-x-1/2 items-start gap-2.5 rounded-[var(--radius-md)] px-3.5 py-2.5">
          <WifiOff size={16} className="mt-0.5 flex-none text-danger" />
          <div className="min-w-0 flex-1 text-[12px] leading-snug">
            <div className="font-semibold text-fg">{describeApiError(context.error)}</div>
            <div className="text-fg-muted">Không có snapshot context, trạm hay khuyến nghị — chỉ hiện bản đồ nền. Tự thử lại theo chu kỳ. <span className="font-mono text-[11px] text-fg-subtle">{API_BASE}</span></div>
          </div>
          <IconButton label="Thử lại ngay" onClick={retry} className="!size-7"><RefreshCw size={14} /></IconButton>
        </div>
      )}

      {/* Right inspector */}
      <div className="pointer-events-none absolute bottom-3 right-3 top-3 z-[800] flex flex-col items-end gap-2">
        <IconButton variant="glass" label={inspectorOpen ? 'Ẩn bảng thông tin' : 'Hiện bảng thông tin'} pressed={inspectorOpen} onClick={() => setInspectorOpen(value => !value)} className="pointer-events-auto flex-none">
          {inspectorOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
        </IconButton>
        {inspectorOpen && (
          <div className="panel-enter min-h-0 flex-1" style={{ width: INSPECTOR_W }}>
            <Inspector
              sensor={sensor} station={pilotStation} aquaculture={data.aquaculture} stations={data.stations.data}
              mode={mode} onMode={setMode} scenario={scenario} onScenario={setScenario}
              snapshot={snapshot} contextError={context.error} layers={allLayers} enabled={enabled} flow={flow}
              bathymetry={data.bathymetry.data} network={data.network.data} zones={data.zones.data}
              sample={sample} onCloseSample={closeSample}
            />
          </div>
        )}
      </div>
    </div>
  )
}
