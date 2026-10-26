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

/** Describe observed facts, rather than infer an active workflow from 0%. */
export function detailProgressLabel(panel, kind) {
  if (panel.state === 'loading') return '正在核验'
  if (panel.state === 'restricted') return '无查看权限'
  if (panel.state !== 'ready') return '待核对'
  const summary = panel.summary || {}
  const progress = progressValue(kind === 'receipt' ? summary.effective_amount : summary.shipped_quantity,
    kind === 'receipt' ? summary.total_amount : summary.ordered_quantity, panel.state)
  const states = [...(panel.tasks || []), ...(panel.batches || []).filter(row => !['cancelled', 'cancelled_keep_freight'].includes(row.state))].flatMap(row => [row.state, row.outbound_state])
  const needsReview = states.some(state => ['uncertain', 'failed', 'blocked', 'outbound_uncertain', 'review_required', 'confirm_uncertain', 'shipped_unfunded'].includes(state))
    || (panel.items || []).some(row => kind === 'receipt'
      ? row.status === 'active' && ['uncertain', 'failed'].includes(row.sync_status)
      : Boolean(row.anomaly))
  let label
  if (needsReview) label = '待核对'
  else if (!progress) label = (kind === 'receipt' ? summary.total_amount : summary.ordered_quantity) != null && Number(kind === 'receipt' ? summary.total_amount : summary.ordered_quantity) === 0 ? '无统计基数' : '待核对'
  else if (progress.over > 0) label = kind === 'receipt' ? '超额待核对' : '超量待核对'
  else if (progress.complete) label = '已完成'
  else if (kind === 'receipt' && Number(summary.pending_amount) > 0) label = '待生效'
  else if (kind === 'outbound' && states.includes('waiting_stock')) label = '等待补货'
  else if (kind === 'outbound' && states.some(state => ['pending', 'running', 'retrying'].includes(state))) label = '生成中'
  else if (kind === 'outbound' && states.includes('awaiting_sync')) label = '待同步'
  else if (progress.percentage > 0) label = '进行中'
  else if (kind === 'outbound' && panel.items?.length) label = '待完成检验'
  else if (kind === 'outbound' && panel.batches?.some(row => !['cancelled', 'cancelled_keep_freight'].includes(row.state))) label = '待出库'
  else if (kind === 'receipt' && panel.items?.some(row => row.status === 'active')) label = '已登记待核验'
  else label = '未开始'
  return panel.source === 'background_snapshot' ? `快照 · ${label}` : label
}

export function createDetailSession() {
  let version = 0, controller
  return {
    begin() { controller?.abort(); controller = new AbortController(); return { version: ++version, signal: controller.signal } },
    current(value) { return value === version },
    cancel() { version++; controller?.abort() },
  }
}
