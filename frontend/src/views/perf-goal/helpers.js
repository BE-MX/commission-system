/**
 * 绩效目标管理 · 纯逻辑 helpers（组件与 node --test 共用）。
 * 指标 key 与后端契约一致：gmv / new_sign / repeat_customers / repeat_amount。
 */
import { formatMoney } from '../../utils/money.js'

export const METRICS = [
  { key: 'gmv', name: 'GMV', unit: 'USD', money: true },
  { key: 'new_sign', name: '新签客户', unit: '个', money: false },
  { key: 'repeat_customers', name: '复购客户', unit: '个', money: false },
  { key: 'repeat_amount', name: '复购金额', unit: 'USD', money: true },
]
export const MKEYS = METRICS.map(m => m.key)
export const metricMeta = key => METRICS.find(m => m.key === key) || { key, name: key, unit: '', money: false }

export const round2 = value => Math.round((Number(value) + Number.EPSILON) * 100) / 100

/* ---------------- 格式化 ---------------- */
export const fmtUsd = (value, { cents = false } = {}) =>
  value == null || !Number.isFinite(Number(value)) ? '—' : `$${formatMoney(value, cents ? 2 : 0)}`
export const fmtInt = value =>
  value == null || !Number.isFinite(Number(value)) ? '—' : formatMoney(value, { precision: 0, missing: '—' })
export const fmtMetric = (key, value, { withUnit = false } = {}) => {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const meta = metricMeta(key)
  if (meta.money) return fmtUsd(value)
  return withUnit ? `${fmtInt(value)} ${meta.unit}` : fmtInt(value)
}
export const rateOf = (achieved, target) =>
  target ? Math.round((Number(achieved) / Number(target)) * 1000) / 10 : null
export const fmtRate = rate => (rate == null ? '—' : `${Number(rate).toFixed(1)}%`)
export const fmtPp = value => `${value >= 0 ? '+' : ''}${Number(value).toFixed(1)}pp`
export const deltaPp = (rate, timeProgress) =>
  rate == null || timeProgress == null ? null : round2(rate - timeProgress)

/* ---------------- 状态判定 ---------------- */
export const STATUS = {
  completed: { key: 'completed', text: '已完成', tag: 'green' },
  on_track: { key: 'on_track', text: '进行中', tag: 'blue' },
  lagging: { key: 'lagging', text: '落后', tag: 'red' },
  critical: { key: 'critical', text: '严重落后', tag: 'darkred' },
  no_target: { key: 'no_target', text: '未设目标', tag: 'gray' },
}
export function statusOf(rate, timeProgress = 100) {
  if (rate == null) return STATUS.no_target
  if (rate >= 100) return STATUS.completed
  if (rate >= timeProgress - 0.05) return STATUS.on_track
  if (rate >= timeProgress - 30) return STATUS.lagging
  return STATUS.critical
}
export const normalizeStatus = status => STATUS[status] || STATUS.no_target

/* ---------------- 排名排序 ---------------- */
export const RANK_SORTS = {
  gmv_target: row => row.gmv?.target ?? -1,
  gmv_achieved: row => row.gmv?.achieved ?? -1,
  gmv_rate: row => row.gmv?.rate ?? -1,
  new_sign_rate: row => row.new_sign?.rate ?? -1,
  repeat_customers_rate: row => row.repeat_customers?.rate ?? -1,
  repeat_amount_rate: row => row.repeat_amount?.rate ?? -1,
  delta_pp: row => row.delta_pp ?? Number.NEGATIVE_INFINITY,
}
export function sortRanking(rows, sort = 'gmv_rate', order = 'desc') {
  const pick = RANK_SORTS[sort] || RANK_SORTS.gmv_rate
  const dir = order === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const diff = (pick(a) - pick(b)) * dir
    if (diff) return diff
    return String(a.user_id ?? '').localeCompare(String(b.user_id ?? ''))
  })
}

/* ---------------- 汇总 ---------------- */
/** 汇总一组含四指标 {target, achieved} 的行（ranking/teams 行），返回 {gmv:{target,achieved,rate}, ...} */
export function sumMetricCells(rows) {
  const total = {}
  MKEYS.forEach(key => { total[key] = { target: 0, achieved: 0 } })
  rows.forEach(row => {
    MKEYS.forEach(key => {
      const cell = row[key]
      if (!cell) return
      total[key].target = round2(total[key].target + (Number(cell.target) || 0))
      total[key].achieved = round2(total[key].achieved + (Number(cell.achieved) || 0))
    })
  })
  MKEYS.forEach(key => { total[key].rate = rateOf(total[key].achieved, total[key].target) })
  return total
}

/* ---------------- ECharts 调色板 ---------------- */
/** canvas 不支持 var()：从 .perf-goal-page CSS 变量解析实际颜色，fallback 为 rgb 字面量 */
export function chartPalette(el) {
  const styles = el && typeof getComputedStyle === 'function' ? getComputedStyle(el) : null
  const token = (name, fallback) => styles?.getPropertyValue(name).trim() || fallback
  return {
    primary: token('--pg-primary', 'rgb(37,99,235)'),
    target: token('--pg-target', 'rgb(148,163,184)'),
    green: token('--pg-green', 'rgb(22,163,74)'),
    red: token('--pg-red', 'rgb(220,38,38)'),
    amber: token('--pg-amber', 'rgb(245,158,11)'),
    orange: token('--pg-orange', 'rgb(234,88,12)'),
    muted: token('--pg-muted', 'rgb(107,114,128)'),
    faint: token('--pg-faint', 'rgb(156,163,175)'),
    ink2: token('--pg-ink-2', 'rgb(75,85,99)'),
    line: token('--pg-line', 'rgb(229,231,235)'),
    grayline: token('--pg-grayline', 'rgb(203,213,225)'),
    gridline: token('--pg-gridline', 'rgb(240,242,245)'),
    axisline: token('--pg-axisline', 'rgb(209,213,219)'),
  }
}

/* ---------------- 目标拆分权重 ---------------- */
export const SEASON_WEIGHTS = [0.2, 0.25, 0.25, 0.3]

/** 金额按权重拆分（两位小数，末位调差，保证合计精确） */
export function splitWeighted(total, weights) {
  const value = Number(total) || 0
  const wsum = weights.reduce((a, b) => a + b, 0) || 1
  const parts = weights.map(w => round2((value * w) / wsum))
  parts[parts.length - 1] = round2(parts[parts.length - 1] + (value - parts.reduce((a, b) => a + b, 0)))
  return parts
}

/** 整数按权重拆分（最大余数法，保证合计精确） */
export function allocInt(total, weights) {
  const value = Math.round(Number(total) || 0)
  const wsum = weights.reduce((a, b) => a + b, 0) || 1
  const raw = weights.map(w => (w / wsum) * value)
  const base = raw.map(Math.floor)
  let remainder = value - base.reduce((a, b) => a + b, 0)
  const order = raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0])
  for (let k = 0; k < remainder; k++) base[order[k % order.length][1]] += 1
  return base
}

/** 年度 → 季度：金额走 splitWeighted，个数走 allocInt */
export function splitYearToQuarters(value, { integer = false, weights = SEASON_WEIGHTS } = {}) {
  return integer ? allocInt(value, weights) : splitWeighted(value, weights)
}

/** 季度 → 月度：均分三份，金额末月调差，个数最大余数法 */
export function splitQuarterToMonths(value, { integer = false } = {}) {
  return integer ? allocInt(value, [1, 1, 1]) : splitWeighted(value, [1, 1, 1])
}

/* ---------------- 目标校验 ---------------- */
/** 同级子项之和 vs 父项；差异超 tolerance 返回 {sum, diff}，否则 null */
export function validateChildSum(parent, children, tolerance = 0.005) {
  const sum = round2(children.reduce((a, b) => a + (Number(b) || 0), 0))
  const diff = round2(sum - (Number(parent) || 0))
  return Math.abs(diff) > tolerance ? { sum, diff } : null
}

/* ---------------- 目标行索引 ---------------- */
export const goalKey = (userId, metric, granularity, quarter, month) =>
  [userId, metric, granularity, quarter || '', month || ''].join('|')

/** GET goals rows → Map(goalKey → target_value) */
export function indexGoalRows(rows) {
  const map = new Map()
  ;(rows || []).forEach(row => {
    map.set(goalKey(row.user_id, row.metric, row.granularity, row.quarter, row.month), row.target_value)
  })
  return map
}

/** 编辑暂存 → PUT /goals payload rows */
export function goalRowsFromEdits(edits) {
  return Object.entries(edits || {}).map(([key, value]) => {
    const [user_id, metric, granularity, quarter, month] = key.split('|')
    return {
      user_id,
      metric,
      granularity,
      quarter: quarter === '' ? null : Number(quarter),
      month: month === '' ? null : Number(month),
      target_value: Number(value) || 0,
    }
  })
}
