import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fanSeats, filterCards, groupLanes, laneValues, sortCards, tagOptions } from '../src/views/client_desk/boardModel.js'

const card = (id, extra = {}) => ({ company_id: String(id), name: `C${id}`, grade: null, todo: false, orders: { amount_usd: 0 }, tags: [], ...extra })
const tag = (kind, code, label = code) => ({ kind, code, label })

test('grade lanes follow the dictionary order and ungraded goes last', () => {
  const cards = [card(1, { grade: 'B' }), card(2), card(3, { grade: 'S' })]
  const lanes = groupLanes(cards, 'grade', { grades: ['S', 'A', 'B'] })
  assert.deepEqual(lanes.map(l => l.label), ['S', 'B', '未分级'])
})

test('a card with two AI tags appears in both AI lanes; no tag lands in the empty lane', () => {
  const cards = [card(1, { tags: [tag('ai', 'custom_need'), tag('ai', 'price_sensitive')] }), card(2)]
  const lanes = groupLanes(cards, 'ai', { vocabulary: { ai: [{ code: 'price_sensitive' }, { code: 'custom_need' }] } })
  assert.deepEqual(lanes.map(l => [l.key, l.items.length]), [['price_sensitive', 1], ['custom_need', 1], ['', 1]])
  assert.deepEqual(laneValues(card(3), 'risk'), [{ key: '', label: '暂无风险' }])
})

test('stage lanes use the fixed business order', () => {
  const s = code => tag('stage', `stage:${code}`, code)
  const lanes = groupLanes([card(1, { tags: [s('churn')] }), card(2, { tags: [s('active')] }), card(3, { tags: [s('repeat')] })], 'stage')
  assert.deepEqual(lanes.map(l => l.key), ['active', 'repeat', 'churn'])
})

test('todo cards come first, then larger accounts', () => {
  const sorted = sortCards([card(1, { orders: { amount_usd: 900 } }), card(2, { todo: true }), card(3, { orders: { amount_usd: 5000 } })])
  assert.deepEqual(sorted.map(c => c.company_id), ['2', '3', '1'])
})

test('tag filters are conjunctive and combine with todo and keyword', () => {
  const cards = [card(1, { tags: [tag('ai', 'a'), tag('risk', 'r')], todo: true }), card(2, { tags: [tag('ai', 'a')] }), card(3, { name: 'Lueur Paris', country: 'France' })]
  assert.deepEqual(filterCards(cards, { tagCodes: ['a', 'r'] }).map(c => c.company_id), ['1'])
  assert.deepEqual(filterCards(cards, { tagCodes: ['a'], todoOnly: true }).map(c => c.company_id), ['1'])
  assert.deepEqual(filterCards(cards, { keyword: 'france' }).map(c => c.company_id), ['3'])
  assert.deepEqual(tagOptions(cards).map(g => g.kind), ['ai', 'risk'])
})

test('fan seats put the first card on top in the middle and stay symmetric', () => {
  const seats = fanSeats(5)
  assert.equal(seats.length, 5)
  assert.equal(seats[0].angle, 0)
  assert.equal(Math.max(...seats.map(s => s.z)), seats[0].z)
  assert.deepEqual(seats.map(s => s.angle).sort((a, b) => a - b), [-8.4, -4.2, 0, 4.2, 8.4])
  assert.equal(fanSeats(9).length, 5)
  assert.deepEqual(fanSeats(1), [{ angle: 0, z: 10 }])
})
