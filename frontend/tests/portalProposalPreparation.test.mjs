import test from 'node:test'
import assert from 'node:assert/strict'
import { proposalLine, validateProposalPreview } from '../src/views/portal/proposalPreparation.mjs'
const item = { item_id: 'sku-1', min_order_qty: 3, step_qty: 2, display_snapshot: { item_id: 'sku-1', model_name: 'Model', color_name: 'Natural', length: '20', weight: '20g' } }
test('new line starts at a valid minimum multiple and never carries a price', () => {
  const line = proposalLine(item, [])
  assert.equal(line.quantity, 4); assert.equal(line.step_qty, 2); assert.equal(line.min_order_qty, 4)
  assert.equal('unit_price' in line, false)
  assert.throws(() => proposalLine(item, [line]))
  assert.throws(() => proposalLine({ ...item, step_qty: 0 }, []))
  assert.throws(() => proposalLine({ ...item, min_order_qty: 10001 }, []))
  assert.throws(() => proposalLine(item, Array(100).fill({ item_id: 'another' })))
})
test('preview must match request, version, currency and exact items/quantity', () => {
  const line = { item_id: item.item_id, quantity: 4, display_snapshot: item.display_snapshot, unit_price: '27.0000', line_amount: '108.00' }
  const result = { request_id: 'request', row_version: 3, currency: 'USD', binding: false, requires_customer_acceptance: true, items: [line], changes: [{ kind: 'added', changed_fields: [], after: line }], product_amount: '108.00', total_amount: '128.00' }
  const body = { items: [{ item_id: 'sku-1', quantity: 4 }] }
  assert.equal(validateProposalPreview(result, 'request', 3, body, 'USD'), result)
  for (const patch of [{ request_id: 'other' }, { row_version: 4 }, { currency: 'EUR' }, { binding: true }, { total_amount: null }, { items: [line, line] }, { items: [{ ...line, quantity: 2 }] }, { changes: [{ kind: 'unexpected' }] }]) assert.throws(() => validateProposalPreview({ ...result, ...patch }, 'request', 3, body, 'USD'))
})
