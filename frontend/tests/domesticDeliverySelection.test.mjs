import test from 'node:test'
import assert from 'node:assert/strict'
import { deliveryTotal, deliveryPayload, filterDeliveryRows } from '../src/views/domestic/deliverySelection.js'

const rows = Array.from({ length: 61 }, (_, i) => ({ item_id: i + 1, guest_name: i === 60 ? '张女士' : '顾客' + i,
  domestic_no: 'DO' + i, order_no: '客户单' + i, line_code: 'A1', product_name: '型号甲',
  available_qty: 6, unit_price: 123.45, units: [{ id: 1 }, { id: 2 }, { id: 3 }] }))

test('search and cross-page selections preserve all selected quantities and exact cents', () => {
  const selected = { 1: { quantity: 2 }, 61: { quantity: 3 } }
  assert.equal(filterDeliveryRows(rows, '张女士', selected, false).length, 1)
  assert.equal(filterDeliveryRows(rows, '', selected, true).length, 2)
  assert.deepEqual(deliveryTotal(rows, selected), { lines: 2, quantity: 5, cents: 61725 })
  assert.equal(deliveryPayload(rows, selected).length, 2)
})

test('stale/duplicated explicit unit selections and excess quantity fail before submission', () => {
  assert.throws(() => deliveryPayload(rows, { 1: { quantity: 7 } }), /超出/)
  assert.throws(() => deliveryPayload(rows, { 1: { quantity: 2, unit_ids: [1, 1] } }), /单件/)
  assert.throws(() => deliveryPayload(rows, { 1: { quantity: 1, unit_ids: [99] } }), /单件/)
  assert.deepEqual(deliveryPayload(rows, { 1: { quantity: 2, unit_ids: [3, 1] } })[0].unit_ids, [3, 1])
})
