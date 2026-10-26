import test from 'node:test'
import assert from 'node:assert/strict'
import { canChangeShipment, shipmentActionReason, isShipmentStateReceipt, remainingShipmentQuantity, hasActiveShipment, retainedFreightForReplacement } from '../src/views/invoice/composables/shipmentSettlementState.js'

test('settlement actions disappear after outbound creation or uncertain remote state', () => {
  assert.equal(canChangeShipment({ state: 'outbound_pending', outbound: { status: 'pending' } }, 'pause'), false)
  assert.equal(canChangeShipment({ state: 'outbound_uncertain' }, 'cancel'), false)
  assert.equal(canChangeShipment({ state: 'review_required' }, 'pause'), false)
})

test('server permits cancelling a paused batch with an existing pool allocation', () => {
  const row = { state: 'paused', balance: { registered_amount: '1000.00' },
    actions: { cancel: { allowed: true, reason: '' }, resume: { allowed: true, reason: '' } } }
  assert.equal(canChangeShipment(row, 'cancel'), true)
  assert.equal(canChangeShipment(row, 'resume'), true)
  assert.equal(shipmentActionReason(row, 'cancel'), '')
})

test('server denial and missing action facts cannot be replaced by local amount guesses', () => {
  const reason = '已有真实付款或运费目标，仅支持原批暂停/恢复'
  const row = { state: 'paused', balance: { registered_amount: '0.00' },
    actions: { cancel: { allowed: false, reason } } }
  assert.equal(canChangeShipment(row, 'cancel'), false)
  assert.equal(shipmentActionReason(row, 'cancel'), reason)
  assert.equal(canChangeShipment({ state: 'awaiting_payment' }, 'cancel'), false)
  assert.match(shipmentActionReason({}, 'cancel'), /刷新原批次/)
})

test('cancellation releases quantity and active slot, while pause retains both', () => {
  const row = { state: 'paused', quote: { items: [{ invoice_item_id: 7, quantity: 4 }] } }
  assert.equal(hasActiveShipment([row]), true)
  assert.equal(remainingShipmentQuantity({ id: 7, quantity: 10 }, [row]), 6)
  row.state = 'cancelled'
  assert.equal(hasActiveShipment([row]), false)
  assert.equal(remainingShipmentQuantity({ id: 7, quantity: 10 }, [row]), 10)
})

test('whole-order sources deduct shipped quantities while same-SKU append stays independent', () => {
  const old = [{ state: 'shipped', quote: { items: [{ invoice_item_id: 10, quantity: 3 }] } }]
  assert.equal(remainingShipmentQuantity({ id: 20, quantity: 3, presale_source_item_ids: [10] }, old), 0)
  assert.equal(remainingShipmentQuantity({ id: 21, quantity: 5, presale_source_item_ids: [10] }, old), 2)
  assert.equal(remainingShipmentQuantity({ id: 22, quantity: 3, sku_id: 99 }, old), 3)
  assert.equal(remainingShipmentQuantity({ id: 23, quantity: 5, presale_source_item_ids: [10, 10] }, old), 2)
})

test('state command accepts only the same batch, a newer version and the requested outcome', () => {
  const row = { id: 3, invoice_id: 1033, version: 6 }
  const receipt = { ...row, version: 7, state: 'cancelled' }
  assert.equal(isShipmentStateReceipt(row, 'cancel', receipt), true)
  for (const patch of [{ id: 4 }, { invoice_id: 99 }, { version: 6 }, { state: 'paused' }, { version: '7' }]) {
    assert.equal(isShipmentStateReceipt(row, 'cancel', { ...receipt, ...patch }), false)
  }
  assert.equal(isShipmentStateReceipt(row, 'resume', { ...receipt, state: 'awaiting_payment' }), true)
  assert.equal(isShipmentStateReceipt(row, 'resume', { ...receipt, state: 'awaiting_verification' }), true)
})

test('goods cancellation releases quantities while retained freight is claimed only once', () => {
  const retired = { id: 7, state: 'cancelled_keep_freight',
    quote: { freight_amount: '121.16', items: [{ invoice_item_id: 8, quantity: 4 }] } }
  assert.equal(hasActiveShipment([retired]), false)
  assert.equal(remainingShipmentQuantity({ id: 8, quantity: 10 }, [retired]), 10)
  assert.equal(retainedFreightForReplacement([retired]), retired)
  const replacement = { id: 8, state: 'outbound_pending', quote: { retained_freight_settlement_id: 7 } }
  assert.equal(retainedFreightForReplacement([retired, replacement]), undefined)
  replacement.state = 'cancelled'
  assert.equal(retainedFreightForReplacement([retired, replacement]), retired)
  assert.equal(isShipmentStateReceipt({ id: 7, invoice_id: 1, version: 1 }, 'cancel_deleted',
    { ...retired, invoice_id: 1, version: 2 }), true)
})
