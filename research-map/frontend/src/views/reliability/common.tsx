import L from 'leaflet'
import { escapeHtml } from '../../components/map/mapConfig'
import { SwatchLegend } from '../../components/ui'
import type { Theme } from '../../hooks/useTheme'
import { REGIME_LABEL, REGIME_ORDER, regimeColor, regimeLabel } from '../../lib/palette'
import type { RegimeClass } from '../../types/research'

export function RegimeLegend({ theme, classes, title = 'Chế độ mặn (trung vị mùa ướt)', note }: { theme: Theme; classes?: RegimeClass[]; title?: string; note?: string }) {
  const shown = classes?.length ? REGIME_ORDER.filter(c => classes.includes(c)) : REGIME_ORDER
  return <SwatchLegend title={title} columns={2} note={note} items={shown.map(regime => ({ color: regimeColor(regime, theme), label: REGIME_LABEL[regime], shape: 'dot' as const }))} />
}

/** Station dot coloured by regime class with a surface ring; dashed ring when the salinity is model-derived. */
export function stationMarker(lat: number, lon: number, regime: string, theme: Theme, renderer: L.Canvas, opts: { radius?: number; modelDerived?: boolean } = {}) {
  return L.circleMarker([lat, lon], {
    renderer, radius: opts.radius ?? 6, weight: opts.modelDerived ? 2.5 : 2,
    color: opts.modelDerived ? regimeColor(regime, theme) : theme === 'dark' ? '#0a1220' : '#ffffff',
    dashArray: opts.modelDerived ? '3 3' : undefined,
    fillColor: opts.modelDerived ? (theme === 'dark' ? '#0a1220' : '#ffffff') : regimeColor(regime, theme), fillOpacity: 1,
  })
}

export const regimeTooltip = (title: string, lines: Array<string | null | undefined>) =>
  `<b>${escapeHtml(title)}</b>${lines.filter(Boolean).map(line => `<br/>${line}`).join('')}`

export const regimeLine = (regime: string) => `Chế độ: <b>${escapeHtml(regimeLabel(regime))}</b>`
