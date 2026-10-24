/**
 * Fixed-scale colour ramps for the regional weather / ocean fields (Windy-style: the same colour always
 * means the same value, so two snapshots can be compared by eye). Stops are [value, r, g, b, alpha 0–1].
 */
export type FieldId = 'rain' | 'rain6h' | 'wind' | 'wave' | 'current' | 'sea_level'
type Stop = [number, number, number, number, number]
export type Palette = { id: FieldId; title: string; unit: string; stops: Stop[]; ticks: number[]; digits: number }

export const PALETTES: Record<FieldId, Palette> = {
  // 0 mm/h is transparent: a dry map stays readable instead of being washed in the lowest colour.
  rain: { id: 'rain', title: 'Mưa (giờ hiện tại)', unit: 'mm/h', digits: 1, ticks: [0, 5, 10, 15, 20], stops: [
    [0, 120, 190, 235, 0], [0.1, 120, 190, 235, 0.35], [1, 70, 150, 225, 0.6], [3, 40, 90, 200, 0.7], [6, 110, 60, 190, 0.75], [10, 190, 55, 150, 0.8], [20, 225, 70, 70, 0.85]] },
  rain6h: { id: 'rain6h', title: 'Mưa cộng dồn 6 giờ tới', unit: 'mm', digits: 1, ticks: [0, 10, 20, 30, 40], stops: [
    [0, 120, 190, 235, 0], [0.5, 120, 190, 235, 0.35], [5, 70, 150, 225, 0.6], [10, 40, 90, 200, 0.72], [20, 150, 60, 180, 0.8], [40, 225, 70, 70, 0.85]] },
  wind: { id: 'wind', title: 'Gió 10 m', unit: 'm/s', digits: 0, ticks: [0, 5, 10, 15, 20, 25], stops: [
    [0, 98, 113, 183, 0.7], [3, 57, 163, 176, 0.72], [6, 74, 181, 87, 0.72], [9, 216, 193, 74, 0.65], [12, 233, 138, 61, 0.7], [16, 208, 64, 60, 0.72], [21, 166, 59, 140, 0.75], [28, 91, 42, 112, 0.78]] },
  // Finer steps below 1 m: sheltered bays sit at 0.05–0.5 m most days and would otherwise be one flat colour.
  wave: { id: 'wave', title: 'Sóng (độ cao Hs)', unit: 'm', digits: 2, ticks: [0, 0.5, 1, 1.5, 2, 2.5, 3], stops: [
    [0, 52, 72, 150, 0.72], [0.1, 45, 105, 190, 0.74], [0.25, 40, 150, 200, 0.76], [0.5, 60, 185, 160, 0.78], [0.75, 140, 200, 90, 0.78],
    [1, 215, 205, 70, 0.8], [1.5, 235, 150, 55, 0.82], [2, 220, 90, 55, 0.84], [3, 160, 45, 110, 0.86]] },
  current: { id: 'current', title: 'Dòng chảy', unit: 'm/s', digits: 2, ticks: [0, 0.2, 0.4, 0.6, 0.8, 1], stops: [
    [0, 40, 50, 110, 0.7], [0.05, 45, 90, 175, 0.72], [0.1, 40, 140, 200, 0.75], [0.2, 60, 185, 165, 0.78], [0.3, 140, 205, 95, 0.8],
    [0.45, 225, 205, 70, 0.82], [0.6, 235, 145, 55, 0.84], [0.8, 215, 75, 60, 0.86], [1, 160, 40, 105, 0.88]] },
  sea_level: { id: 'sea_level', title: 'Mực nước so với mực TB', unit: 'm', digits: 2, ticks: [-1.5, -0.75, 0, 0.75, 1.5], stops: [
    [-1.5, 43, 90, 168, 0.65], [-0.75, 91, 149, 209, 0.6], [0, 232, 238, 242, 0.45], [0.75, 232, 161, 106, 0.6], [1.5, 196, 80, 47, 0.68]] },
}

/** RGBA (0–255) for a value; clamps outside the ramp. */
export function paletteRgba(palette: Palette, value: number): [number, number, number, number] {
  const stops = palette.stops
  if (!(value > stops[0][0])) return [stops[0][1], stops[0][2], stops[0][3], Math.round(stops[0][4] * 255)]
  for (let i = 1; i < stops.length; i++) {
    const [v1, r1, g1, b1, a1] = stops[i]
    if (value <= v1) {
      const [v0, r0, g0, b0, a0] = stops[i - 1]
      const t = (value - v0) / (v1 - v0)
      return [Math.round(r0 + (r1 - r0) * t), Math.round(g0 + (g1 - g0) * t), Math.round(b0 + (b1 - b0) * t), Math.round((a0 + (a1 - a0) * t) * 255)]
    }
  }
  const last = stops[stops.length - 1]
  return [last[1], last[2], last[3], Math.round(last[4] * 255)]
}

/** CSS gradient over the tick range, for the legend bar (alpha raised so pale stops stay visible). */
export function paletteGradient(palette: Palette): string {
  const lo = palette.ticks[0], hi = palette.ticks[palette.ticks.length - 1]
  const parts = palette.stops.filter(([v]) => v >= lo && v <= hi).map(([v, r, g, b, a]) => `rgba(${r},${g},${b},${Math.max(a, 0.55)}) ${((v - lo) / (hi - lo)) * 100}%`)
  return `linear-gradient(90deg, ${parts.join(', ')})`
}
