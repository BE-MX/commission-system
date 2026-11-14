// 客户流失态势：接口数据 + 时间偏移 → 甲板坐标。纯函数，2D 缩略图、2D 降级与 3D 场景共用。
// 坐标系（甲板单位）：x 沿船长，z 横向（0 = 中线，±HALF = 船舷，|z| > HALF = 海面）。

export const DECK = Object.freeze({ HALF: 8.5, PITCH: 1.7, GAP: 0.7, MIN_COLS: 3, MAX_COLS: 9 })
// 车道：0 临界贴舷（≤3 天）… 4 中线（>22 天）
export const LANES = Object.freeze([8.15, 6.55, 5.1, 3.65, 2.2])
export const CRITICAL_DAYS = 3
export const WARNING_DAYS = 14
export const PROJECTION_DAYS = 14
export const REPLAY_DAYS = 7
const INDIVIDUAL_LEVELS = new Set(['S级', 'A级'])

export function tierOf(remaining) {
  if (remaining <= 0) return 'fallen'
  if (remaining <= CRITICAL_DAYS) return 'critical'
  if (remaining <= WARNING_DAYS) return 'warning'
  return 'stable'
}

function laneOf(remaining) {
  if (remaining <= 3) return 0
  if (remaining <= 7) return 1
  if (remaining <= 14) return 2
  if (remaining <= 22) return 3
  return 4
}

// 稳定的伪随机，同一客户每次落在同一侧、同一片海
function hash(id, salt) {
  let x = (id * 2654435761 + salt * 40503) >>> 0
  x ^= x >>> 15; x = Math.imul(x, 2246822519) >>> 0; x ^= x >>> 13
  return (x >>> 0) / 4294967296
}

/** 接口数据 → 静态条目（与时间无关的部分，数据刷新时算一次）。 */
export function buildModel(data) {
  const regions = (data?.regions || []).map(region => ({ ...region, items: [] }))
  const byKey = new Map(regions.map(region => [region.key, region]))
  const items = []
  const push = (row, rem0, fallen) => {
    const region = byKey.get(row.region)
    if (!region) return
    const item = {
      id: row.id, row, region: row.region, level: row.level || '', rem0, fallen,
      side: hash(row.id, 1) < 0.5 ? 1 : -1, h1: hash(row.id, 2), h2: hash(row.id, 3),
    }
    region.items.push(item)
    items.push(item)
  }
  for (const row of data?.customers || []) push(row, row.remaining_days, false)
  for (const row of data?.fallen || []) push(row, -row.fallen_days_ago, true)
  for (const region of regions) {
    const listedStable = region.items.filter(item => !item.fallen && item.rem0 > WARNING_DAYS).length
    region.stackCount = Math.max(0, region.stable - listedStable)
    region.cols = Math.max(DECK.MIN_COLS, Math.min(DECK.MAX_COLS,
      Math.ceil((region.items.filter(item => !item.fallen).length + region.stackCount / 4) / 5)))
    const used = { 1: 0, '-1': 0 }
    for (const item of region.items) item.col = used[item.side]++ % region.cols
  }
  let x = 0
  for (const region of regions) {
    region.len = region.cols * DECK.PITCH
    region.x0 = x
    x += region.len + DECK.GAP
  }
  const length = Math.max(0, x - DECK.GAP)
  for (const region of regions) {
    region.x0 -= length / 2
    region.xc = region.x0 + region.len / 2
  }
  return { regions, items, length }
}

/**
 * 条目在时间 t 的档位。还有归属、但倒计时已过（预演口径下超期，或今天的释放任务还没跑）的客户，
 * 在今天和回放里留在船上算临界；只有后端确认已落海的条目、或推演里才进海里。
 */
export function tierAt(item, t) {
  const tier = tierOf(item.rem0 - t)
  return tier === 'fallen' && !item.fallen && t <= 0 ? 'critical' : tier
}

/** 时间偏移 t（天，负 = 回放，正 = 推演）下每个条目的状态与目标位置。 */
export function layoutAt(model, t) {
  const cells = new Map()
  const summary = new Map(model.regions.map(region => [region.key, { owned: 0, critical: 0, warning: 0, fallen: 0 }]))
  for (const item of model.items) {
    const remaining = item.rem0 - t
    const tier = tierAt(item, t)
    const region = model.regions.find(r => r.key === item.region)
    const counts = summary.get(item.region)
    item.remaining = remaining
    item.tier = tier
    item.visible = tier !== 'stable' || INDIVIDUAL_LEVELS.has(item.level)
    if (tier === 'fallen') {
      counts.fallen += 1
      item.x = region.xc + (item.h1 - 0.5) * region.len * 0.85
      item.z = item.side * (DECK.HALF + 3.6 + item.h2 * 9)
      item.stack = 0
      continue
    }
    counts.owned += 1
    if (tier === 'critical') counts.critical += 1
    if (tier === 'warning') counts.warning += 1
    const lane = laneOf(remaining)
    const key = `${item.region}|${item.side}|${item.col}|${lane}`
    const stack = cells.get(key) || 0
    cells.set(key, stack + 1)
    item.x = region.x0 + (item.col + 0.5) * DECK.PITCH
    item.z = item.side * LANES[lane]
    item.stack = stack
  }
  return summary
}

/** 顶部三个数字，随时间偏移变化（推演 / 回放时同步）。 */
export function kpisAt(model, t) {
  let critical = 0, within14 = 0, fallen = 0
  for (const item of model.items) {
    const remaining = item.rem0 - t
    const tier = tierAt(item, t)
    if (tier === 'fallen') { if (remaining > -30) fallen += 1; continue }
    if (tier === 'critical') critical += 1
    if (tier !== 'stable') within14 += 1
  }
  return { critical, within14, fallen }
}
