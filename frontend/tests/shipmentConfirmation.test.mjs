import assert from 'node:assert/strict'
import test from 'node:test'
import { canReconcileOutbound } from '../src/views/invoice/composables/shipmentSettlementState.js'
const row = (status, confirmation) => ({ outbound: { status, confirmation } })
const clear = { state: 'none', blocks_confirmation: false, requires_review: false, in_progress: false }
test('inspection completion supports read-only review of drafts and completed batches', () => {
  assert.equal(canReconcileOutbound(row('pending_remote', clear)), true)
  assert.equal(canReconcileOutbound(row('shipped', clear)), true)
})
test('expired or unknown claim can be reviewed, active claim stays blocked', () => {
  assert.equal(canReconcileOutbound(row('confirming', { state: 'active', requires_review: true, in_progress: true })), false)
  assert.equal(canReconcileOutbound(row('confirming', { state: 'unresolved', requires_review: true, in_progress: false })), true)
  assert.equal(canReconcileOutbound(row('pending_remote', { state: 'invalid', requires_review: true, in_progress: false })), true)
  assert.equal(canReconcileOutbound(row('confirm_uncertain', clear)), true)
  assert.equal(canReconcileOutbound(row('shipped', clear)), true)
})

import { confirmationKey, readConfirmation, saveConfirmation, clearConfirmation, isConfirmationTarget,
  isConfirmationResolution, protectConfirmation } from '../src/views/invoice/composables/shipmentConfirmation.js'
const original = () => ({ invoice_id: 1, settlement_id: 8, outbound_id: 9, remote_id: '401', body: { version: 2, reason: 'Review original' } })
const storage = () => { const data = new Map(); return { getItem: key => data.get(key) ?? null,
  setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) } }
const settlement = () => ({ id: 8, invoice_id: 1, version: 3, state: 'outbound_pending',
  outbound: { id: 9, remote_id: '401', status: 'pending_remote', confirmation: { ...clear } } })
test('confirmation storage preserves original target/body and isolates actor slots', () => {
  const store = storage(), command = original()
  saveConfirmation(store, 4, command); command.body.version = 7
  assert.deepEqual(readConfirmation(store, 4), original()); assert.equal(readConfirmation(store, 5), null)
  assert.throws(() => saveConfirmation(store, 4, { ...original(), settlement_id: 10 }))
  assert.throws(() => clearConfirmation(store, 4, command))
  clearConfirmation(store, 4, original()); assert.equal(readConfirmation(store, 4), null)
})
test('quota, silent drops, malformed records and remove failures do not report reliable storage', () => {
  const store = storage()
  assert.throws(() => saveConfirmation({ ...store, setItem() { throw Error('quota') } }, 4, original()))
  assert.throws(() => saveConfirmation({ ...store, setItem() {} }, 4, original()))
  store.setItem(confirmationKey(4), '{'); assert.throws(() => readConfirmation(store, 4))
  store.setItem(confirmationKey(4), JSON.stringify({ actor: 5, command: original() })); assert.throws(() => readConfirmation(store, 4))
  store.removeItem(confirmationKey(4)); saveConfirmation(store, 4, original())
  assert.throws(() => clearConfirmation({ ...store, removeItem() {} }, 4, original()))
})
test('ordinary none or old resolved rows remain locally blocked, active claims cannot be reviewed', () => {
  for (const state of ['none', 'resolved']) {
    const value = settlement(); value.outbound.confirmation.state = state
    const protectedRow = protectConfirmation(value, original())
    assert.equal(canReconcileOutbound(protectedRow), true)
    assert.equal(value.outbound.confirmation.state, state)
  }
  const active = settlement(); active.outbound.confirmation.in_progress = true
  assert.equal(canReconcileOutbound(protectConfirmation(active, original())), false)
})
test('explicit resolution requires exact original identity and advancement past the invoked version', () => {
  assert.equal(Boolean(isConfirmationResolution(settlement(), original(), 2)), true)
  assert.equal(Boolean(isConfirmationResolution(settlement(), original(), 3)), false)
  for (const mutate of [v => v.id = 10, v => v.invoice_id = 2, v => v.version = 2,
    v => v.outbound.id = 10, v => v.outbound.remote_id = '402', v => v.outbound.confirmation.state = 'unresolved',
    v => v.outbound.confirmation.blocks_confirmation = true, v => v.outbound.confirmation.in_progress = true]) {
    const value = settlement(); mutate(value)
    assert.equal(Boolean(isConfirmationResolution(value, original(), 2)), false)
  }
  assert.equal(isConfirmationTarget(settlement(), original()), true)
})
