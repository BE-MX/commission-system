// 发货检验看板的纯逻辑：排序、等待时长、新签提醒去重。与 Vue 无关，便于 node:test。
import { parseApiDateTime } from '../../../utils/datetime.js'

const HOUR = 3600e3
export const LATE_HOURS = 24
export const HEAVY_LINES = 30

export function priorityOf(row) {
  if (row.is_new_deal) return 0
  if (row.customer_grade === 'S') return 1
  if (row.customer_grade === 'A') return 2
  return 3
}

export function ageHours(row, now = Date.now()) {
  const created = parseApiDateTime(row.created_at)
  return created ? Math.max(0, (now - created.getTime()) / HOUR) : null
}

// 新签最新的在上；S/A 与普通单都按等待最久优先
export function sortPending(rows, now = Date.now()) {
  return [...rows].sort((a, b) => {
    const pa = priorityOf(a), pb = priorityOf(b)
    if (pa !== pb) return pa - pb
    const ha = ageHours(a, now) ?? 0, hb = ageHours(b, now) ?? 0
    return pa === 0 ? ha - hb : hb - ha
  })
}

export function summarize(rows, now = Date.now()) {
  const counts = [0, 0, 0, 0], qty = [0, 0, 0, 0]
  let late = 0
  for (const row of rows) {
    const p = priorityOf(row)
    counts[p] += 1
    qty[p] += Number(row.total_qty) || 0
    if ((ageHours(row, now) ?? 0) >= LATE_HOURS) late += 1
  }
  return { total: rows.length, counts, qty, totalQty: qty.reduce((s, v) => s + v, 0), late }
}

export function ageLabel(hours) {
  if (hours == null) return { value: '—', unit: '' }
  if (hours < 1) return { value: String(Math.max(1, Math.round(hours * 60))), unit: 'm' }
  if (hours < 10) return { value: hours.toFixed(1), unit: 'h' }
  return { value: String(Math.round(hours)), unit: 'h' }
}

export function ageLevel(hours) {
  if (hours == null || hours < 8) return 'fresh'
  return hours < LATE_HOURS ? 'mid' : 'late'
}

export function maskCustomer(name) {
  const value = String(name || '').trim()
  return value ? `${value.slice(0, 3)}***` : '—'
}

export const FIRST_RUN_ALERT_HOURS = 0.5

/**
 * 返回需要弹框的新签单，并给出新的已知集合（由调用方持久化，刷新页面不重复弹）。
 * known 为 null 表示这台大屏从未记录过：只弹最近 30 分钟内生成的，避免开机一连串历史弹框。
 */
export function detectNewDeals(rows, known, now = Date.now()) {
  const deals = rows.filter(row => row.is_new_deal)
  const alerts = deals.filter(row => (known == null
    ? (ageHours(row, now) ?? Infinity) <= FIRST_RUN_ALERT_HOURS
    : !known.has(row.outbound_record_id)))
  // 只保留仍在待检列表里的 id，存储不会无限增长
  return { alerts, known: new Set(deals.map(row => row.outbound_record_id)) }
}

// 主页面分页：优先单固定在上，普通单按剩余格数分页轮播
export function pageRows(sorted, slots, page) {
  const pinned = sorted.filter(row => priorityOf(row) < 3)
  const rest = sorted.filter(row => priorityOf(row) === 3)
  const pinnedShown = pinned.slice(0, slots)
  const per = Math.max(1, slots - pinnedShown.length)
  const pages = rest.length ? Math.ceil(rest.length / per) : 1
  const current = ((page % pages) + pages) % pages
  const shown = slots > pinnedShown.length ? rest.slice(current * per, current * per + per) : []
  return { pinned: pinnedShown, rest: shown, pages, page: current, restOffset: current * per,
    hiddenPinned: pinned.length - pinnedShown.length }
}
