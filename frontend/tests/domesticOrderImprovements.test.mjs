import test from 'node:test'
import assert from 'node:assert/strict'
import { loadOrderUnitLabels } from '../src/views/domestic/print/orderUnitLabels.js'
import { buildUnitLabelDoc } from '../src/views/domestic/print/printDocs.js'
import { effectiveDiscountPrice, buildCreateItems, buildDraftSubmitPayload } from '../src/views/domestic/composables/domesticMemberPricing.js'

test('sample zero remains explicit through display and payload', () => {
  const item = { key: 'a', attrs: {}, manualDiscountPrice: 0, quote: { discount_price: 900 } }
  assert.equal(effectiveDiscountPrice(item), 0)
  assert.equal(buildCreateItems([item], a => a)[0].manual_discount_price, 0)
  assert.equal(buildCreateItems([{ ...item, manualDiscountPrice: null }], a => a)[0].manual_discount_price, null)
  assert.equal(buildDraftSubmitPayload({ items: [{ unit_price: 950, labor_fee: 50 }] }, () => 'id').expected_quotes[0].discount_price, 900)
})

test('whole-order labels preserve product order and include pages beyond 200', async () => {
  const calls = []
  const data = await loadOrderUnitLabels({ domestic_no: 'DO1', items: [
    { id: 2, line_no: 2, order_qty: 1 }, { id: 1, line_no: 1, order_qty: 201 },
  ] }, async (id, range) => {
    calls.push([id, range.start_no, range.end_no])
    return { data: { order_qty: id === 1 ? 201 : 1, domestic_no: 'DO1', item: { attrs: { product_type: 'piece', craft: `PRODUCT-${id}` } },
      units: Array.from({ length: range.end_no - range.start_no + 1 }, (_, i) => ({ unit_no: range.start_no + i, unit_code: `A${id}-${range.start_no + i}` })),
    } }
  })
  assert.deepEqual(calls, [[1, 1, 200], [1, 201, 201], [2, 1, 1]])
  const doc = buildUnitLabelDoc({ data })
  assert.equal((doc.match(/class="label unit-label"/g) || []).length, 202)
  assert.ok(doc.lastIndexOf('PRODUCT-1') < doc.indexOf('PRODUCT-2'))
  assert.equal((doc.match(/<!doctype html>/gi) || []).length, 1)
})

test('incomplete batches fail instead of silently printing partial order', async () => {
  await assert.rejects(loadOrderUnitLabels({ items: [{ id: 1, line_no: 1, order_qty: 2 }] }, async () => ({ data: { units: [{}] } })), /数量已变化/)
  assert.equal(await loadOrderUnitLabels({ items: [{ id: 1, order_qty: 1 }] }, () => { throw new Error('must not load') }, () => false), null)
})
