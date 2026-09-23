import assert from 'node:assert/strict'
import test from 'node:test'
import { cents, validateAllocations, latestRequest } from '../src/views/receipt/batchReceiptState.js'
const row = (id, amount, extra = {}) => ({ id, amount, customer_id: 'customer-1', currency: 'USD', balance: { remaining_amount: '10.00', version: 'v1' }, ...extra })
test('decimal allocations compare exact cents rather than float sums', () => {
  assert.equal(validateAllocations([row(1, '0.10'), row(2, '0.20')], '0.30'), '')
  assert.notEqual(validateAllocations([row(1, '0.10'), row(2, '0.20')], '0.31'), '')
  for (const input of ['1.001', '-1', '', NaN, Infinity, '1e3']) assert.equal(cents(input), null)
})
test('batch rejects mixed identities, duplicate invoices, and stale or excess balances', () => {
  assert.notEqual(validateAllocations([row(1, '1'), row(2, '1', { customer_id: 'other' })], '2'), '')
  assert.notEqual(validateAllocations([row(1, '1'), row(2, '1', { currency: 'EUR' })], '2'), '')
  assert.notEqual(validateAllocations([row(1, '1'), row(1, '1')], '2'), '')
  assert.notEqual(validateAllocations([row(1, '10.01')], '10.01'), '')
  assert.notEqual(validateAllocations([row(1, '1', { balance: null })], '1'), '')
  assert.notEqual(validateAllocations([row(1, '1', { customer_id: null })], '1'), '')
})
test('superseded searches and quotes cannot update current UI', () => {
  const requests = latestRequest(), old = requests.next(), current = requests.next()
  assert.equal(requests.isCurrent(old), false)
  assert.equal(requests.isCurrent(current), true)
  requests.next()
  assert.equal(requests.isCurrent(current), false)
})
import { remainingShipmentQuantity, hasActiveShipment } from '../src/views/invoice/composables/shipmentSettlementState.js'
import { buildInvoicePayload, emptyInvoiceForm } from '../src/views/invoice/composables/invoiceEditorState.js'
test('shipment quantity excludes consumed allocations and restores cancelled batches', () => {
  const rows = [{ state: 'shipped', quote: { items: [{ invoice_item_id: 7, quantity: 3 }] } },
    { state: 'cancelled', quote: { items: [{ invoice_item_id: 7, quantity: 2 }] } },
    { state: 'awaiting_payment', quote: { items: [{ invoice_item_id: 7, quantity: 1 }, { invoice_item_id: 8, quantity: 9 }] } }]
  assert.equal(remainingShipmentQuantity({ id: 7, quantity: 10 }, rows), 6)
  assert.equal(hasActiveShipment(rows), true)
  assert.equal(hasActiveShipment(rows.slice(0, 2)), false)
})
test('presale payload cannot carry order-level freight or invent a deposit', () => {
  const form = { ...emptyInvoiceForm(), order_type: 'presale', shipping_fee: 25 }
  assert.equal(buildInvoicePayload(form, 0).shipping_fee, 0)
  assert.equal(buildInvoicePayload(form, 0).receipt_draft, null)
  form.receipt_draft = { amount: 12.34, attachment_ids: [9] }
  assert.equal(buildInvoicePayload(form, 0).receipt_draft.amount, '12.34')
})
