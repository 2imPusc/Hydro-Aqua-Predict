import type { ReactNode } from 'react'
import { CloudSun, Grid2x2, Map as MapIcon, Moon, ShieldCheck, Sun, TrendingUp, Waves } from 'lucide-react'
import { NAV, type Route, type ViewId } from './routes'
import { TopBarStatus } from './TopBarStatus'
import { IconButton } from '../components/ui'
import type { Theme } from '../hooks/useTheme'

const ICON: Record<ViewId, ReactNode> = {
  monitor: <MapIcon size={19} strokeWidth={1.9} />,
  forecast: <TrendingUp size={19} strokeWidth={1.9} />,
  weather: <CloudSun size={19} strokeWidth={1.9} />,
  zoning: <Grid2x2 size={19} strokeWidth={1.9} />,
  reliability: <ShieldCheck size={19} strokeWidth={1.9} />,
}

function NavRail({ route }: { route: Route }) {
  return (
    <nav aria-label="Điều hướng chính" className="flex w-[var(--rail-w)] flex-none flex-col items-center gap-1 bg-[var(--rail)] py-3">
      <a href="#/monitor" className="mb-3 grid size-10 place-items-center rounded-[var(--radius-md)] bg-gradient-to-br from-sky-400 to-teal-500 text-white shadow-lg shadow-sky-900/40" aria-label="Hydro-Aqua · Trang giám sát">
        <Waves size={21} strokeWidth={2.2} />
      </a>
      {NAV.map(item => {
        const active = route.view === item.view
        return (
          <a key={item.view} href={item.hash} aria-current={active ? 'page' : undefined} title={item.label}
            className={`group relative flex w-[64px] flex-col items-center gap-1 rounded-[var(--radius-md)] px-1 py-2 text-center no-underline transition-colors duration-150 ${active ? 'bg-[var(--rail-active)] text-sky-700 dark:text-sky-300' : 'text-[var(--rail-fg)] hover:bg-white/5 hover:text-white'}`}>
            {active && <span className="absolute -left-[6px] top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-full bg-sky-400" aria-hidden />}
            <span className="relative">
              {ICON[item.view]}
              {item.code && <span className={`absolute -right-2.5 -top-1.5 rounded px-[3px] text-[8.5px] font-bold leading-[12px] ${active ? 'bg-sky-600 text-white dark:bg-sky-400 dark:text-slate-900' : 'bg-white/10 text-[var(--rail-fg)] group-hover:text-white'}`}>{item.code}</span>}
            </span>
            <span className="text-[10.5px] font-semibold leading-tight">{item.short}</span>
          </a>
        )
      })}
    </nav>
  )
}

export function Shell({ route, theme, onToggleTheme, children }: { route: Route; theme: Theme; onToggleTheme: () => void; children: ReactNode }) {
  const current = NAV.find(item => item.view === route.view) ?? NAV[0]
  return (
    <div className="flex h-full min-h-0 bg-bg text-fg">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[2000] focus:rounded focus:bg-surface focus:px-3 focus:py-2">Bỏ qua điều hướng</a>
      <NavRail route={route} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="z-[1100] flex h-[var(--topbar-h)] flex-none items-center gap-3 border-b border-line bg-surface px-4">
          <div className="min-w-0 flex-none">
            <div className="text-[10px] font-bold uppercase tracking-[.14em] text-accent">Hydro-Aqua · Research Map</div>
            <h1 className="m-0 truncate text-[15px] font-semibold leading-tight tracking-tight">{current.label}</h1>
          </div>
          <div className="ml-auto flex min-w-0 items-center gap-2">
            <TopBarStatus />
            <span className="mx-1 h-6 w-px bg-line" aria-hidden />
            <IconButton label={theme === 'dark' ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối'} onClick={onToggleTheme} data-testid="theme-toggle">
              {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            </IconButton>
          </div>
        </header>
        <main id="main" className="relative min-h-0 flex-1">{children}</main>
      </div>
    </div>
  )
}
