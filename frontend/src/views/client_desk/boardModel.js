// Pure board logic: lane grouping, tag filtering and fan seating. No Vue, no I/O.

export const DIMENSIONS = {
  grade: { label: '等级', tone: 'gold' },
  stage: { label: '阶段', tone: 'info' },
  type: { label: '客户类型', tone: 'neutral' },
  ai: { label: 'AI 标签', tone: 'violet' },
  risk: { label: '风险', tone: 'danger' },
  channel: { label: '渠道', tone: 'success' },
}
export const TAG_TONES = Object.fromEntries(Object.entries(DIMENSIONS).map(([key, value]) => [key, value.tone]))
const EMPTY_LANES = { grade: '未分级', stage: '未判定', type: '类型未知', ai: '暂无 AI 标签', risk: '暂无风险', channel: '渠道未知' }
const STAGE_ORDER = ['active', 'repeat', 'nurture', 'dormant', 'churn']

export function tagTone(tag) {
  return TAG_TONES[tag.kind] || 'neutral'
}

/** Tag values of one card on one dimension; a card can sit in several AI/risk lanes. */
export function laneValues(card, dimension) {
  const tags = (card.tags || []).filter(tag => tag.kind === dimension)
  if (dimension === 'grade') return [{ key: card.grade || '', label: card.grade || EMPTY_LANES.grade }]
  if (dimension === 'stage') return tags.length ? tags.map(t => ({ key: t.code.replace('stage:', ''), label: t.label })) : [{ key: '', label: EMPTY_LANES.stage }]
  return tags.length ? tags.map(t => ({ key: t.code, label: t.label })) : [{ key: '', label: EMPTY_LANES[dimension] }]
}

function laneOrder(dimension, options) {
  if (dimension === 'grade') return [...(options.grades || []), '']
  if (dimension === 'stage') return [...STAGE_ORDER, '']
  const vocabulary = options.vocabulary?.[dimension] || []
  return [...vocabulary.map(item => item.code), '']
}

export function sortCards(cards) {
  return [...cards].sort((a, b) => (Number(b.todo) - Number(a.todo))
    || ((b.orders?.amount_usd || 0) - (a.orders?.amount_usd || 0))
    || String(a.name || '').localeCompare(String(b.name || '')))
}

export function groupLanes(cards, dimension, options = {}) {
  const lanes = new Map()
  for (const card of cards) {
    for (const value of laneValues(card, dimension)) {
      if (!lanes.has(value.key)) lanes.set(value.key, { key: value.key, label: value.label, items: [] })
      lanes.get(value.key).items.push(card)
    }
  }
  const order = laneOrder(dimension, options)
  const rank = key => { const index = order.indexOf(key); return index < 0 ? order.length - 1 : index }
  return [...lanes.values()]
    .map(lane => ({ ...lane, items: sortCards(lane.items), todo: lane.items.filter(c => c.todo).length, priority: lane.items.filter(c => ['S', 'A'].includes(c.grade)).length }))
    .sort((a, b) => rank(a.key) - rank(b.key) || a.label.localeCompare(b.label))
}

export function filterCards(cards, { tagCodes = [], todoOnly = false, keyword = '' } = {}) {
  const folded = keyword.trim().toLocaleLowerCase()
  return cards.filter(card => (!todoOnly || card.todo)
    && tagCodes.every(code => (card.tags || []).some(tag => tag.code === code))
    && (!folded || [card.name, card.country, card.contact_name].some(value => String(value || '').toLocaleLowerCase().includes(folded))))
}

/** Tag options for the filter menu, grouped by dimension and limited to tags present on cards. */
export function tagOptions(cards) {
  const seen = new Map()
  for (const card of cards) for (const tag of card.tags || []) if (!seen.has(tag.code)) seen.set(tag.code, tag)
  return Object.keys(DIMENSIONS).map(kind => ({ kind, label: DIMENSIONS[kind].label, tags: [...seen.values()].filter(tag => tag.kind === kind) })).filter(group => group.tags.length)
}

/** The first card sits on top in the middle; the rest alternate outwards. */
export function fanSeats(count, maxCards = 5, step = 4.2) {
  const n = Math.min(count, maxCards)
  const mid = (n - 1) / 2, center = Math.floor(mid)
  const seats = [center]
  for (let k = 1; seats.length < n; k++) {
    if (center + k < n) seats.push(center + k)
    if (seats.length < n && center - k >= 0) seats.push(center - k)
  }
  return seats.map(seat => ({ angle: Math.round((seat - mid) * step * 100) / 100, z: 10 - Math.round(Math.abs(seat - mid) * 2) }))
}

export function initials(name) {
  return String(name || '?').trim().split(/\s+/).map(part => part[0]).slice(0, 2).join('').toUpperCase()
}
