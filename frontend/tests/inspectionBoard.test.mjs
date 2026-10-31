import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ageLabel, ageLevel, detectNewDeals, maskCustomer, pageRows, sortPending, summarize,
} from '../src/views/shipping/composables/inspectionBoard.js'

const NOW = Date.parse('2026-10-28T12:00:00+08:00')
const row = (id, hoursAgo, extra = {}) => ({
  outbound_record_id: id,
  created_at: new Date(NOW - hoursAgo * 3600e3).toISOString(),
  total_qty: 10,
  ...extra,
})

test('new deals first (newest on top), then S, A, then oldest plain', () => {
  const rows = [
    row('plain-new', 1), row('plain-old', 30), row('a', 5, { customer_grade: 'A' }),
    row('s', 2, { customer_grade: 'S' }), row('deal-old', 6, { is_new_deal: true }),
    row('deal-new', 0.2, { is_new_deal: true, customer_grade: 'C' }),
  ]
  assert.deepEqual(sortPending(rows, NOW).map(r => r.outbound_record_id),
    ['deal-new', 'deal-old', 's', 'a', 'plain-old', 'plain-new'])
})

test('summary counts priority buckets, quantities and late documents', () => {
  const s = summarize([row('x', 25, { is_new_deal: true }), row('y', 3, { customer_grade: 'S', total_qty: 5 }), row('z', 40)], NOW)
  assert.deepEqual(s.counts, [1, 1, 0, 1])
  assert.equal(s.totalQty, 25)
  assert.equal(s.late, 2)
})

test('naive backend time is read as Beijing time', () => {
  const s = summarize([{ created_at: '2026-10-27 12:00:00', total_qty: 1 }], NOW)
  assert.equal(s.late, 1)
})

test('age labels and levels', () => {
  assert.deepEqual(ageLabel(0.2), { value: '12', unit: 'm' })
  assert.deepEqual(ageLabel(3.14), { value: '3.1', unit: 'h' })
  assert.deepEqual(ageLabel(41.4), { value: '41', unit: 'h' })
  assert.deepEqual([ageLevel(2), ageLevel(12), ageLevel(30)], ['fresh', 'mid', 'late'])
})

test('customer names are masked for the shared screen', () => {
  assert.equal(maskCustomer('Glamour Locks'), 'Gla***')
  assert.equal(maskCustomer(''), '—')
})

test('first run alerts only recent deals; later polls alert each new deal once', () => {
  const first = detectNewDeals([row('old', 3, { is_new_deal: true }), row('recent', 0.2, { is_new_deal: true })], null, NOW)
  assert.deepEqual(first.alerts.map(r => r.outbound_record_id), ['recent'])
  const second = detectNewDeals([row('old', 3, { is_new_deal: true }), row('b', 0, { is_new_deal: true })], first.known, NOW)
  assert.deepEqual(second.alerts.map(r => r.outbound_record_id), ['b'])
  assert.deepEqual([...second.known].sort(), ['b', 'old'])
  const third = detectNewDeals([row('b', 0, { is_new_deal: true })], second.known, NOW)
  assert.equal(third.alerts.length, 0)
})

test('priority rows stay pinned while plain rows page', () => {
  const sorted = sortPending([
    row('s', 1, { customer_grade: 'S' }), ...Array.from({ length: 7 }, (_, i) => row(`p${i}`, 10 - i)),
  ], NOW)
  const first = pageRows(sorted, 4, 0)
  assert.deepEqual(first.pinned.map(r => r.outbound_record_id), ['s'])
  assert.equal(first.rest.length, 3)
  assert.equal(first.pages, 3)
  assert.equal(pageRows(sorted, 4, 3).page, 0)
})
