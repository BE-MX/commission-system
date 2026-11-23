/** 方舟开发动态的纯展示规则：文案、颜色语义、日期范围（北京时间日历）。 */
export const STATUS_LABELS = {
  dev: '开发中', pending_merge: '待合并', pending_push: '待推送', pending_release: '待发布', released: '已发布',
}
export const COLUMN_LABELS = { dev: '开发中', committed: '已提交', released: '已发布' }
export const TYPE_META = {
  feature: { label: '新功能', tone: 'gold' },
  improve: { label: '改进', tone: 'info' },
  bug: { label: 'BUG 修复', tone: 'danger' },
  data: { label: '数据修复', tone: 'violet' },
  ops: { label: '运维发布', tone: 'neutral' },
  docs: { label: '规范文档', tone: 'neutral' },
}
export const AGENT_LABELS = { codex: 'Codex', claude: 'Claude', kimi: 'Kimi', accio: 'Accio', unknown: '未标注' }
export const SUB_TONE = { pending_merge: 'info', pending_push: 'gold', pending_release: 'warning' }

function shift(isoDate, days) {
  const [y, m, d] = isoDate.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d + days))
  return date.toISOString().slice(0, 10)   // 纯日历运算，UTC 午夜不涉及时区换算
}

export function rangeFor(kind, today) {
  if (kind === 'day') return { start: today, end: today }
  if (kind === 'week') return { start: shift(today, -6), end: today }
  if (kind === 'month') return { start: `${today.slice(0, 7)}-01`, end: today }
  throw new Error(`unknown range ${kind}`)
}

export function readinessLabel(item) {
  if (item.status === 'pending_merge') return '先合入 main'
  if (item.status === 'pending_push') return '先推送'
  return item.ready ? '可以' : '先完成前提'
}

export function preconditionTags(pre = {}) {
  return [
    ...(pre.migrations || []).map(text => ({ text: `迁移 ${text}`, tone: 'warning' })),
    ...(pre.config_keys || []).map(text => ({ text: `配置 ${text}`, tone: 'gold' })),
    ...(pre.permissions || []).map(text => ({ text: `权限 ${text}`, tone: 'info' })),
  ]
}

export function shortSha(value) {
  return /^[0-9a-f]{40}$/.test(value || '') ? value.slice(0, 8) : value
}
