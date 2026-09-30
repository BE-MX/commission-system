import test from 'node:test'
import assert from 'node:assert/strict'
import { canChangeShipment } from '../src/views/invoice/composables/shipmentSettlementState.js'

test('settlement actions disappear after outbound creation or uncertain remote state', () => {
  assert.equal(canChangeShipment({ state: 'outbound_pending', outbound: { status: 'pending' } }, 'pause'), false)
  assert.equal(canChangeShipment({ state: 'outbound_uncertain' }, 'cancel'), false)
  assert.equal(canChangeShipment({ state: 'review_required' }, 'pause'), false)
})

test('cancel requires no registered payment or bound freight, while pause may remain', () => {
  const empty = { state: 'awaiting_payment', balance: { registered_amount: '0.00' } }
  assert.equal(canChangeShipment(empty, 'cancel'), true)
  assert.equal(canChangeShipment({ ...empty, balance: { registered_amount: '1.00' } }, 'cancel'), false)
  assert.equal(canChangeShipment({ ...empty, freight_target: { status: 'bound', remote_order_id: '123' } }, 'cancel'), false)
  assert.equal(canChangeShipment({ ...empty, freight_target: { status: 'bound', remote_order_id: '123' } }, 'pause'), true)
  assert.equal(canChangeShipment({ ...empty, freight_target: { status: 'uncertain' } }, 'pause'), false)
  assert.equal(canChangeShipment({ ...empty, state: 'paused' }, 'resume'), true)
})
