export const ANOMALY_LABELS = Object.freeze({ order: '订单异常', outbound: '出库单异常', receipt: '回款异常' })

/** Keep a successful indicator on transient failures; discard it on scope changes. */
export function mergeAnomalyOverview(previous, incoming) {
  return Object.fromEntries(Object.keys(ANOMALY_LABELS).map(key => {
    const next = incoming?.[key] || { state: 'unavailable' }
    return [key, next.state === 'ready' || next.state === 'restricted'
      ? { ...next, has_anomaly: next.state === 'ready' && next.has_anomaly === true }
      : { ...previous?.[key], state: 'unavailable' }]
  }))
}

/** State is decided from exact totals, independently of the rounded display. */
export function progressValue(numerator, denominator, state) {
  const n = Number(numerator), d = Number(denominator)
  if (state !== 'ready' || numerator == null || denominator == null || !Number.isFinite(n) || !Number.isFinite(d) || d <= 0 || n < 0) return null
  return { percentage: Math.min(100, Math.floor(n / d * 1000) / 10), complete: n >= d, over: Math.max(0, n - d) }
}

export function createDetailSession() {
  let version = 0, controller
  return {
    begin() { controller?.abort(); controller = new AbortController(); return { version: ++version, signal: controller.signal } },
    current(value) { return value === version },
    cancel() { version++; controller?.abort() },
  }
}
