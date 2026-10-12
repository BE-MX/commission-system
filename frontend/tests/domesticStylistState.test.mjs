import test from 'node:test'
import assert from 'node:assert/strict'
import { stylistTotals, groupStylistFacts } from '../src/views/domestic_decision/stylistState.js'

const rows = [
  { id: 1, item_id: 10, order_id: 3, report_qty: 2, reported_at: '2026-09-01T00:00:00', user_id: 1, length: '15厘米' },
  { id: 2, item_id: 10, order_id: 3, report_qty: 3, reported_at: '2026-09-01T23:59:59', user_id: 2, length: '15厘米' },
  { id: 3, item_id: 11, order_id: 3, report_qty: 1, reported_at: '2026-09-02T00:00:00', user_id: 1, length: '25厘米' },
]
test('multiple workers and batches count quantities, with distinct item and date grains', () => {
  assert.deepEqual(stylistTotals(rows), { quantity: 6, item_count: 2, order_count: 1, report_count: 3, active_days: 2 })
  assert.equal(stylistTotals(rows.filter(row => row.user_id === 1)).quantity, 3)
})
test('dimension grouping unions lines while keeping every report evidence', () => {
  const groups = groupStylistFacts(rows, row => row.length)
  assert.equal(groups[0].quantity, 5)
  assert.equal(groups[0].item_count, 1)
  assert.deepEqual(groups[0].evidence_refs, [{ type: 'reports', id: 1 }, { type: 'reports', id: 2 }])
  assert.deepEqual(stylistTotals([]), { quantity: 0, item_count: 0, order_count: 0, report_count: 0, active_days: 0 })
})
