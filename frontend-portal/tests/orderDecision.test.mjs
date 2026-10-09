import test from 'node:test'
import assert from 'node:assert/strict'
import { createOrderDecision, currentProposal } from '../src/state/orderDecision.mjs'
import { PortalError } from '../src/api/client.mjs'
import { fieldValue, piLabel } from '../src/orderPresentation.mjs'
const id = '11111111-1111-4111-8111-111111111111', revision = '22222222-2222-4222-8222-222222222222'
const proposal = () => ({ revision_id: revision, content_hash: 'a'.repeat(64), expires_at: '2026-10-01T00:00:00', expired: false })
const order = () => ({ request_id: id, request_no: 'TEST-001', status: 'awaiting_customer', row_version: '9007199254740993', available_actions: ['accept_proposal', 'reject_proposal', 'cancel'], proposal: proposal() })
const receipt = (action = 'accept_proposal', rev = revision, digest = 'a'.repeat(64)) => ({ original_receipt: {
  request_id: id, row_version: '9007199254740994', ...(action === 'cancel' ? { status: 'cancelled' } : {
    revision_id: rev, content_hash: digest, ...(action.endsWith('_pi') ? { invoice_document_version: 3 } : { status: action.startsWith('accept') ? 'ready_for_review' : 'submitted' }) }) },
  current_state: 'invoice_created', row_version: '9007199254740995', replayed: true, ...(action.endsWith('_pi') ? { amendment_state: 'current' } : {}) })
function setup(overrides = {}) {
  const listeners = new Set(), calls = []
  const api = { session: { capabilities: { place_order: true } }, subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    async decide(...args) { calls.push(args); return receipt((args[3] === 'accept' ? 'accept' : 'reject') + (args[1] === id ? '_pi' : '_proposal'), args[1], args[3] === 'accept' ? args[4] : 'a'.repeat(64)) }, async cancel(...args) { calls.push(args); return receipt('cancel') }, async order() { return order() }, async actionReceipt(request, locator) { return { found: false, command: { request_id: request, ...locator } } }, ...overrides }
  const controller = createOrderDecision({ api, now: () => Date.parse('2026-09-30T00:00:00+08:00') })
  return { api, controller, calls, clear() { api.session = null; listeners.forEach(fn => fn({ reason: 'another-tab' })) } }
}
test('accept freezes exact version/hash/revision and uses current state rather than old receipt status', async () => {
  const { controller, calls } = setup(), detail = order()
  await controller.begin(detail, 'accept_proposal'); detail.proposal.content_hash = 'b'.repeat(64)
  assert.deepEqual(calls[0], [id, revision, '9007199254740993', 'accept', 'a'.repeat(64)])
  assert.equal(controller.state.receipt.current_state, 'invoice_created')
  assert.equal(controller.state.operation.value, 'a'.repeat(64))
})
test('expired/missing proposal, missing action permission and empty reason do not dispatch', () => {
  const { controller, calls, api } = setup()
  assert.throws(() => controller.begin({ ...order(), proposal: { ...proposal(), expired: true } }, 'accept_proposal'), { code: 'PROPOSAL_EXPIRED' })
  assert.throws(() => controller.begin({ ...order(), available_actions: [] }, 'cancel', 'test'), { code: 'ACTION_UNAVAILABLE' })
  assert.throws(() => controller.begin(order(), 'cancel', '  '), { code: 'REASON_REQUIRED' })
  api.session.capabilities.place_order = false
  assert.throws(() => controller.begin(order(), 'accept_proposal'), { code: 'ACTION_UNAVAILABLE' })
  assert.equal(calls.length, 0)
})
test('PI acceptance chooses the amendment and never the previously published proposal', async () => {
  const { controller, calls } = setup()
  const detail = { ...order(), status: 'invoice_created', available_actions: ['accept_pi'], pi_amendment: { status: 'pending_customer', proposal: { ...proposal(), revision_id: id, content_hash: 'b'.repeat(64), bound_invoice_document_version: 3 } } }
  assert.equal(currentProposal(detail).revision_id, id)
  await controller.begin(detail, 'accept_pi')
  assert.deepEqual(calls[0], [id, id, '9007199254740993', 'accept', 'b'.repeat(64)])
})
test('reject actions use the exact applicable revision and a trimmed reason rather than a hash', async () => {
  const { controller, calls } = setup()
  await controller.begin(order(), 'reject_proposal', '  Please change the length  ')
  assert.deepEqual(calls[0], [id, revision, '9007199254740993', 'reject', 'Please change the length'])
  await controller.begin({ ...order(), status: 'invoice_created', available_actions: ['reject_pi'], pi_amendment: { proposal: { ...proposal(), revision_id: id, bound_invoice_document_version: 3 } } }, 'reject_pi', 'Different delivery')
  assert.deepEqual(calls[1], [id, id, '9007199254740993', 'reject', 'Different delivery'])
})
test('unknown result reads current state without claiming command success; retry preserves reason and version', async () => {
  const calls = []; let failed = true
  const { controller } = setup({ cancel: async (...args) => { calls.push(args); if (failed) throw new PortalError('NETWORK', 'Unknown', { uncertain: true }); return receipt('cancel') }, order: async () => ({ ...order(), status: 'cancelled' }) })
  await controller.begin(order(), 'cancel', '  Original reason  ')
  assert.equal(controller.state.status, 'uncertain'); assert.equal(controller.state.latest.status, 'cancelled')
  assert.throws(() => controller.begin(order(), 'accept_proposal'), { code: 'ACTION_PENDING' })
  assert.throws(() => controller.dismiss(), { code: 'ACTION_PENDING' })
  await controller.recover(); assert.equal(calls.length, 1)
  failed = false; await controller.retry()
  assert.deepEqual(calls, [[id, '9007199254740993', 'Original reason'], [id, '9007199254740993', 'Original reason']])
  assert.equal(controller.state.status, 'confirmed')
})
test('uncertain retry rejection cannot erase unknown earlier outcome; failed recovery remains uncertain', async () => {
  let first = true
  const { controller } = setup({ decide: async () => { const uncertain = first; first = false; throw new PortalError('FAILED', 'Try again', { uncertain, status: 409 }) }, order: async () => { throw new PortalError('NOT_FOUND', 'Unavailable', { status: 404 }) } })
  await controller.begin(order(), 'accept_proposal'); await controller.retry()
  assert.equal(controller.state.status, 'uncertain'); assert.equal(controller.state.error.status, 404)
})
test('known first rejection is editable; malformed success requires recovery', async () => {
  const rejected = setup({ decide: async () => { throw new PortalError('PROPOSAL_CHANGED', 'Refresh', { status: 409 }) } })
  await rejected.controller.begin(order(), 'accept_proposal'); assert.equal(rejected.controller.state.status, 'failed')
  rejected.controller.dismiss(); assert.equal(rejected.controller.state.status, 'idle')
  const malformed = setup({ decide: async () => ({ current_state: 'ready_for_review' }) })
  await malformed.controller.begin(order(), 'accept_proposal'); assert.equal(malformed.controller.state.status, 'uncertain')
})
test('double submit is blocked and late command success is discarded on scope change', async () => {
  let finish, entered
  const dispatched = new Promise(resolve => { entered = resolve })
  const { controller, clear } = setup({ decide: () => new Promise(resolve => { finish = resolve; entered() }) })
  const request = controller.begin(order(), 'accept_proposal')
  assert.throws(() => controller.begin(order(), 'cancel', 'reason'), { code: 'ACTION_PENDING' })
  await dispatched; clear(); finish(receipt()); await assert.rejects(request, { code: 'STALE_SCOPE' })
  assert.deepEqual(controller.state, { status: 'idle' })
})
test('comparisons show all known delivery/payment/header values; internal identifiers are omitted', () => {
  assert.match(fieldValue('delivery', { address_line1: 'New address', country_code: 'GB', customer_id: 12 }), /Address: New address\nCountry: GB/)
  assert.ok(!fieldValue('commercial_header', { invoice_no: 'PI-TEST', invoice_id: 12 }).includes('12'))
  assert.equal(fieldValue('total_amount', null), 'To be confirmed')
  assert.match(piLabel('accepted'), /Awaiting publication/)
})
