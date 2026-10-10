import assert from 'node:assert/strict'
import test from 'node:test'
import { cents, validateAllocations, latestRequest, allocationForRow, purposeForBalance } from '../src/views/receipt/batchReceiptState.js'
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

test('equal allocation and total still require an unpaid balance for the selected shipment', () => {
  const payment = row(1, '38', { invoice_no: 'PI-38', purpose: 'ordinary', bank_charge: 0,
    balance: { funding_mode: 'presale_pool', version: 'pool-v1', remaining_amount: '2605.48',
      active_settlement: { settlement_id: 9, funding_version: 2, version: 'batch-v1',
        remaining_amount: '0.00', charge_remaining: '0.00' } } })
  assert.match(validateAllocations([payment], '38'), /PI-38.*本批可补款余额为 0.*已登记回款或预付款抵扣/)
  payment.balance.active_settlement.remaining_amount = '38.00'
  assert.equal(validateAllocations([payment], '38'), '')
  assert.equal(allocationForRow(payment).balance_version, 'batch-v1')
  payment.amount = '38.01'
  assert.match(validateAllocations([payment], '38.01'), /PI-38.*分配金额超过.*余额/)
  assert.equal(validateAllocations([row(2, '38', { balance: { remaining_amount: '38.00', version: 'v1' } })], '38'), '')
})

test('missing quotes and invalid allocations explain the failing condition', () => {
  assert.match(validateAllocations([row(1, '1', { balance: null })], '1'), /余额尚未核验.*刷新/)
  assert.match(validateAllocations([row(1, '1', { balance: { version: 'v1' } })], '1'), /余额尚未核验/)
  assert.match(validateAllocations([row(1, '0')], '1'), /分配金额须大于 0/)
  assert.match(validateAllocations([row(1, '1', { balance: { remaining_amount: '0.00', version: 'v1' } })], '1'), /可登记余额为 0/)
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

test('presale advances allow cash above current goods and freeze actual fee', () => {
  const advance = row(1, '1077', { purpose: 'presale_advance', bank_charge: '12',
    balance: { funding_mode: 'presale_pool', version: 'pool-v1', remaining_amount: '0' } })
  assert.equal(validateAllocations([advance], '1077'), '')
  assert.deepEqual(allocationForRow(advance), { invoice_id: 1, settlement_id: null, amount: '1077',
    purpose: 'presale_advance', bank_charge: '12', balance_version: 'pool-v1' })
  advance.bank_charge = '1077'
  assert.notEqual(validateAllocations([advance], '1077'), '')
  advance.bank_charge = '0'
  advance.balance.active_settlement = { version: 'batch-v1', remaining_amount: '10' }
  assert.notEqual(validateAllocations([advance], '1077'), '')
})

test('current supplement uses batch version and actual fee while legacy remains proportional', () => {
  const payment = row(1, '20', { purpose: 'ordinary', bank_charge: '3', balance: {
    funding_mode: 'presale_pool', version: 'pool-v1', remaining_amount: '0',
    active_settlement: { funding_version: 2, settlement_id: 9, version: 'batch-v1',
      remaining_amount: '100', charge_remaining: '5' } } })
  assert.equal(validateAllocations([payment], '20'), '')
  assert.equal(allocationForRow(payment).bank_charge, '3')
  assert.equal(allocationForRow(payment).balance_version, 'batch-v1')
  assert.equal(allocationForRow(payment).settlement_id, 9)
  payment.bank_charge = '6'
  assert.notEqual(validateAllocations([payment], '20'), '')
  payment.balance.active_settlement.funding_version = 1
  assert.equal(allocationForRow(payment).bank_charge, '0')
})

test('new cash joins the pool during a current batch without changing its allocations', () => {
  const payment = row(1, '38', { purpose: 'presale_advance', bank_charge: 0, balance: {
    funding_mode: 'presale_pool', version: 'pool-v1', pool_available_amount: '412.00', remaining_amount: '0',
    active_settlement: { funding_version: 2, settlement_id: 9, version: 'batch-v1',
      remaining_amount: '0.00', charge_remaining: '0' } } })
  assert.equal(validateAllocations([payment], '38'), '')
  assert.deepEqual(allocationForRow(payment), { invoice_id: 1, settlement_id: null, amount: '38',
    purpose: 'presale_advance', bank_charge: '0', balance_version: 'pool-v1' })
  assert.equal(purposeForBalance(payment.balance), 'presale_advance')
  payment.balance.active_settlement.remaining_amount = '38.00'
  assert.equal(purposeForBalance(payment.balance), 'ordinary')
  assert.equal(purposeForBalance(payment.balance, 'presale_advance'), 'presale_advance')
  payment.purpose = 'presale_deposit'
  assert.equal(validateAllocations([payment], '38'), '')
  assert.equal(purposeForBalance(payment.balance, 'presale_deposit'), 'presale_deposit')
  payment.balance.active_settlement.funding_version = 1
  assert.notEqual(validateAllocations([payment], '38'), '')
  assert.equal(purposeForBalance(payment.balance, 'presale_advance'), 'ordinary')
  delete payment.balance.active_settlement
  assert.equal(purposeForBalance(payment.balance, 'ordinary'), 'presale_advance')
})
