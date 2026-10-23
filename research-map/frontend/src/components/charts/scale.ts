/** Minimal linear scale + "nice" ticks for the hand-written SVG charts. */
export function linear(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0 || 1
  return (value: number) => r0 + ((value - d0) / span) * (r1 - r0)
}

export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return []
  if (min === max) return [min]
  const raw = (max - min) / Math.max(1, count)
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map(f => f * magnitude).find(s => s >= raw) ?? raw
  const start = Math.ceil(min / step - 1e-9) * step
  const ticks: number[] = []
  for (let value = start; value <= max + step * 1e-6; value += step) ticks.push(Number(value.toFixed(10)))
  return ticks
}

/** Expands [min, max] (plus `include`) outward to whole tick steps. */
export function niceDomain(values: number[], include: number[] = [], count = 5): [number, number] {
  const all = [...values, ...include].filter(Number.isFinite)
  if (!all.length) return [0, 1]
  let min = Math.min(...all), max = Math.max(...all)
  if (min === max) { min -= 1; max += 1 }
  const ticks = niceTicks(min, max, count)
  const step = ticks.length > 1 ? ticks[1] - ticks[0] : (max - min)
  return [Math.floor(min / step + 1e-9) * step, Math.ceil(max / step - 1e-9) * step]
}
