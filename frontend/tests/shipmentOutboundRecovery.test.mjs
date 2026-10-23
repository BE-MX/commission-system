import test from 'node:test'
import assert from 'node:assert/strict'
import { canRecoverOutbound, outboundRecoveryBody, isOutboundRecoveryReceipt } from '../src/views/invoice/composables/shipmentOutboundRecovery.js'

const row = () => ({ id: 7, invoice_id: 981, version: 3, state: 'outbound_uncertain',
  quote: { quote_hash: 'f'.repeat(64), goods_amount: '1415.54', freight_amount: '121.16' },
  outbound: { id: 6, number: 'ORIGINAL-02', status: 'uncertain', remote_id: null },
  actions: { recover_outbound: { allowed: true, version: 'a'.repeat(64) } } })

test('explicit employee declaration and nonblank reference are required', () => {
  for (const closed of [false, undefined, null, 'true', 1]) assert.equal(outboundRecoveryBody(row(), closed, 'ticket-1234'), null)
  for (const reference of ['', '    ', 'x', 'x'.repeat(201)]) assert.equal(outboundRecoveryBody(row(), true, reference), null)
  const body = outboundRecoveryBody(row(), true, '  OKKI-ticket-1234  ')
  assert.equal(body.resolution_reference, 'OKKI-ticket-1234')
  assert.equal(body.original_request_closed, true)
  assert.equal(body.version, 3)
  assert.equal(body.recovery_version, 'a'.repeat(64))
})

test('local guesses cannot override server eligibility or an existing remote effect', () => {
  const original = row()
  assert.equal(canRecoverOutbound(original), true)
  for (const patch of [{ actions: {} }, { state: 'shipped' }, { outbound: { ...original.outbound, remote_id: '401' } },
    { actions: { recover_outbound: { allowed: false, version: 'a'.repeat(64) } } },
    { actions: { recover_outbound: { allowed: true, version: 'not-a-current-challenge' } } }]) {
    assert.equal(outboundRecoveryBody({ ...original, ...patch }, true, 'ticket-1234'), null)
  }
})

test('recovery receipt must preserve the same task, serial, quote and money', () => {
  const original = row()
  const result = { ...original, version: 4, state: 'outbound_pending', outbound: { ...original.outbound, status: 'pending' } }
  assert.equal(isOutboundRecoveryReceipt(original, result), true)
  for (const patch of [{ id: 8 }, { invoice_id: 982 }, { version: 3 }, { version: '4' }, { state: 'shipped' },
    { outbound: { ...result.outbound, id: 9 } }, { outbound: { ...result.outbound, number: 'NEW-03' } },
    { outbound: { ...result.outbound, remote_id: '401' } }, { quote: { ...original.quote, freight_amount: '121.80' } }]) {
    assert.equal(isOutboundRecoveryReceipt(original, { ...result, ...patch }), false)
  }
})
