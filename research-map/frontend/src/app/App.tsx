import { Component, lazy, Suspense, type ErrorInfo, type ReactNode } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Shell } from './Shell'
import { LiveDataProvider } from './LiveDataContext'
import { useHashRoute, type ReliabilityTab, type ViewId } from './routes'
import { useTheme, type Theme } from '../hooks/useTheme'
import { EmptyState, Skeleton } from '../components/ui'

export type ViewProps = { datasetId?: string; tab?: ReliabilityTab; theme: Theme }

// Each view is its own chunk; Leaflet only loads with the map views.
const VIEWS: Record<ViewId, React.LazyExoticComponent<React.ComponentType<ViewProps>>> = {
  monitor: lazy(() => import('../views/monitor/MonitorView')),
  alerts: lazy(() => import('../views/alerts/AlertsView')),
  forecast: lazy(() => import('../views/forecast/ForecastView')),
  weather: lazy(() => import('../views/weather/WeatherView')),
  zoning: lazy(() => import('../views/zoning/ZoningView')),
  reliability: lazy(() => import('../views/reliability/ReliabilityView')),
  settings: lazy(() => import('../views/settings/AlertConfigView')),
}

function ViewFallback() {
  return (
    <div className="grid h-full place-items-center p-8" aria-busy="true" aria-label="Đang tải giao diện">
      <div className="w-72 space-y-2"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-5/6" /></div>
    </div>
  )
}

class ViewErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('view crashed', error, info.componentStack) }
  componentDidUpdate(previous: { resetKey: string }) { if (previous.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <EmptyState tone="danger" icon={<TriangleAlert size={22} />} title="Không hiển thị được giao diện này" description={this.state.error.message}>
        <button type="button" onClick={() => window.location.reload()} className="rounded-[var(--radius-sm)] bg-accent px-3 py-1.5 text-[13px] font-semibold text-[var(--accent-fg)] hover:bg-accent-hover">Tải lại trang</button>
      </EmptyState>
    )
  }
}

export default function App() {
  const route = useHashRoute()
  const { theme, toggle } = useTheme()
  const View = VIEWS[route.view]
  return (
    <LiveDataProvider monitorActive={route.view === 'monitor'}>
      <Shell route={route} theme={theme} onToggleTheme={toggle}>
        <ViewErrorBoundary resetKey={route.view}>
          <Suspense fallback={<ViewFallback />}>
            <View datasetId={route.params.datasetId} tab={route.params.tab} theme={theme} />
          </Suspense>
        </ViewErrorBoundary>
      </Shell>
    </LiveDataProvider>
  )
}
