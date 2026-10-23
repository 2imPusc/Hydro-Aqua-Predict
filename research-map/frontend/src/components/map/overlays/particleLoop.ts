/**
 * requestAnimationFrame loop that pauses while the tab is hidden and resumes
 * on return. Returns a disposer that stops the loop and removes listeners.
 */
export function startVisibleLoop(frame: (time: number, deltaMs: number) => void): () => void {
  let handle: number | null = null
  let last = performance.now()
  const tick = (time: number) => {
    const delta = time - last
    last = time
    frame(time, delta)
    handle = requestAnimationFrame(tick)
  }
  const start = () => {
    if (handle !== null) return
    last = performance.now()
    handle = requestAnimationFrame(tick)
  }
  const stop = () => {
    if (handle === null) return
    cancelAnimationFrame(handle)
    handle = null
  }
  const onVisibility = () => (document.hidden ? stop() : start())
  document.addEventListener('visibilitychange', onVisibility)
  if (!document.hidden) start()
  return () => {
    stop()
    document.removeEventListener('visibilitychange', onVisibility)
  }
}

/** Canvas sized to the map container (device-pixel aware, capped at 2x). */
export function fitCanvas(canvas: HTMLCanvasElement, context: CanvasRenderingContext2D, container: HTMLElement) {
  const ratio = Math.min(2, window.devicePixelRatio || 1)
  canvas.width = Math.max(1, Math.floor(container.clientWidth * ratio))
  canvas.height = Math.max(1, Math.floor(container.clientHeight * ratio))
  canvas.style.width = `${container.clientWidth}px`
  canvas.style.height = `${container.clientHeight}px`
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
}
