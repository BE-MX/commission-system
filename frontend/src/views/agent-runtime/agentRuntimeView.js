import { formatBeijingDateTime } from '../../utils/datetime.js'

export const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'ambiguous'])

export const STATUS_META = {
  queued: { label: '排队中', type: 'info' },
  leased: { label: '已领取', type: 'warning' },
  running: { label: '执行中', type: 'warning' },
  completed: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
  ambiguous: { label: '待核查', type: 'danger' },
}

export const PROFILE_LABELS = {
  customer_order_copilot: '客户与订单经营副驾驶',
  repurchase_risk_analyst: '复购与流失干预分析',
  sales_discovery_shadow: '新客户开发影子评测',
}

export function statusMeta(status) {
  return STATUS_META[status] || { label: status || '未知', type: 'info' }
}

export function evaluationCaseMeta(item) {
  if (item?.completed_run_id) return { label: '已完成', type: 'success' }
  if (item?.latest_status && item.latest_status !== 'not_started') {
    return statusMeta(item.latest_status)
  }
  return { label: '未开始', type: 'info' }
}

export function evaluationProgress(completed, total) {
  const safeTotal = Math.max(0, Number(total || 0))
  const safeCompleted = Math.min(safeTotal, Math.max(0, Number(completed || 0)))
  return safeTotal ? Math.round((safeCompleted / safeTotal) * 100) : 0
}

export function formatTime(value) {
  return formatBeijingDateTime(value)
}

export function formatPayload(value) {
  if (value == null || value === '') return '-'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

export function artifactFieldLabel(key) {
  const labels = {
    summary: '结论摘要', key_findings: '关键发现', risks: '风险',
    recommended_actions: '建议行动', open_questions: '待确认问题',
    action_reason: '行动理由', suggested_next_action: '下一步建议',
    suggested_message: '沟通草稿', candidates: '候选企业', evidence: '证据引用',
  }
  return labels[key] || key
}
