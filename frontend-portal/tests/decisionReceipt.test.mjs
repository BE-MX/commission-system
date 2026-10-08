import test from 'node:test'
import assert from 'node:assert/strict'
import { createOrderDecision } from '../src/state/orderDecision.mjs'
const id = '11111111-1111-4111-8111-111111111111', revision = '22222222-2222-4222-8222-222222222222'
const other = '33333333-3333-4333-8333-333333333333', hash = 'a'.repeat(64)
const version = '9007199254740993', after = '9007199254740994'
function setup(action = 'accept_proposal', alter = result => result, latest) {
  const pi = action.endsWith('_pi'), calls = [], listeners = new Set()
  const proposal = { revision_id: revision, content_hash: hash, expires_at: '2030-01-01T00:00:00', bound_invoice_document_version: 3 }
  const order = { request_id: id, request_no: 'SYNTHETIC-01', row_version: version, status: pi ? 'invoice_created' : 'awaiting_customer', available_actions: [action], proposal, pi_amendment: { status: 'pending_customer', proposal } }
  const original = action === 'cancel' ? { request_id: id, status: 'cancelled', row_version: after }
    : { request_id: id, revision_id: revision, content_hash: hash, row_version: after,
      ...(pi ? { invoice_document_version: 3 } : { status: action.startsWith('accept') ? 'ready_for_review' : 'submitted' }) }
  const result = { original_receipt: original, current_state: pi ? 'invoice_created' : action === 'cancel' ? 'cancelled' : 'invoice_created', row_version: '9007199254740995', ...(pi ? { amendment_state: 'current' } : {}) }
  const api = { session: { capabilities: { place_order: true } }, subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    async decide(...args) { calls.push(['POST', ...args]); return alter(structuredClone(result)) },
    async cancel(...args) { calls.push(['POST', ...args]); return alter(structuredClone(result)) },
    async order(request) { calls.push(['GET', request]); return latest ?? order } }
  const controller = createOrderDecision({ api, now: () => Date.parse('2026-09-30T00:00:00+08:00') })
  return { order, calls, controller, api, listeners, result }
}
const wrong = [
  ['wrong original revision', r => { r.original_receipt.revision_id = other }],
  ['missing original revision', r => { delete r.original_receipt.revision_id }],
  ['wrong original hash', r => { r.original_receipt.content_hash = 'b'.repeat(64) }],
  ['missing original hash', r => { delete r.original_receipt.content_hash }],
  ['boolean current version', r => { r.row_version = true }],
  ['unsafe numeric current version', r => { r.row_version = Number('9007199254740995') }],
  ['negative current version', r => { r.row_version = -1 }],
  ['nondecimal current version', r => { r.row_version = '1e3' }],
  ['missing original version', r => { delete r.original_receipt.row_version }],
  ['current version before original receipt', r => { r.row_version = version }],
  ['unknown current request state', r => { r.current_state = 'not-a-state' }],
  ['wrong original accept state', r => { r.original_receipt.status = 'submitted' }],
]
for (const [name, mutate] of wrong) test(name + ' remains uncertain and prevents a new action', async () => {
  const ctx = setup('accept_proposal', result => { mutate(result); return result })
  assert.equal((await ctx.controller.begin(ctx.order, 'accept_proposal')).status, 'uncertain')
  assert.equal(ctx.controller.state.receipt, undefined)
  assert.throws(() => ctx.controller.begin(ctx.order, 'cancel', 'Different'), { code: 'ACTION_PENDING' })
  assert.equal(ctx.calls.filter(call => call[0] === 'POST').length, 1)
  assert.deepEqual(ctx.calls.at(-1), ['GET', id])
})
for (const action of ['reject_proposal', 'accept_pi', 'reject_pi']) test(action + ' verifies the original revision/hash', async () => {
  const ctx = setup(action, result => { result.original_receipt.revision_id = other; return result })
  assert.equal((await ctx.controller.begin(ctx.order, action, 'Original reason')).status, 'uncertain')
})
test('cancel cannot accept a receipt for a different command outcome', async () => {
  const ctx = setup('cancel', result => { result.original_receipt.status = 'ready_for_review'; return result })
  assert.equal((await ctx.controller.begin(ctx.order, 'cancel', 'Original reason')).status, 'uncertain')
})
test('PI cannot accept a receipt from another bound document version', async () => {
  const ctx = setup('accept_pi', result => { result.original_receipt.invoice_document_version = 4; return result })
  assert.equal((await ctx.controller.begin(ctx.order, 'accept_pi')).status, 'uncertain')
})
test('PI cannot display unknown current amendment state as confirmation', async () => {
  const ctx = setup('reject_pi', result => { result.amendment_state = 'not-a-state'; return result })
  assert.equal((await ctx.controller.begin(ctx.order, 'reject_pi', 'Original reason')).status, 'uncertain')
})
test('wrong-request recovery observation is discarded and never confirms the action', async () => {
  const ctx = setup('accept_proposal', () => ({}), { request_id: other, row_version: 10, status: 'cancelled', request_no: 'OTHER_PRIVATE_REQUEST' })
  await ctx.controller.begin(ctx.order, 'accept_proposal')
  assert.equal(ctx.controller.state.status, 'uncertain')
  assert.equal(ctx.controller.state.latest, undefined)
  assert.equal(ctx.controller.state.error.code, 'INVALID_RESPONSE')
})
test('scope change after dispatch remains explicitly uncertain and hides all response content', async () => {
  const ctx = setup(); let finish, entered
  const dispatched = new Promise(resolve => { entered = resolve })
  ctx.api.decide = () => new Promise(resolve => { finish = resolve; entered() })
  const pending = ctx.controller.begin(ctx.order, 'accept_proposal')
  await dispatched; ctx.listeners.forEach(fn => fn({ reason: 'another-tab' })); finish(ctx.result)
  await assert.rejects(pending, { code: 'STALE_SCOPE', uncertain: true })
  assert.deepEqual(ctx.controller.state, { status: 'idle' })
})
for (const action of ['accept_proposal', 'reject_proposal', 'accept_pi', 'reject_pi', 'cancel']) test(action + ' accepts actual complete receipt and exact large integer versions', async () => {
  const ctx = setup(action)
  assert.equal((await ctx.controller.begin(ctx.order, action, 'Original reason')).status, 'confirmed')
  assert.equal(ctx.controller.state.receipt.row_version, '9007199254740995')
  assert.equal(ctx.controller.state.receipt.current_state, ctx.result.current_state)
})
test('legitimate replay can have original receipt version below the supplied current version', async () => {
  const ctx = setup(); ctx.order.row_version = '9007199254740999'
  const result = await ctx.controller.begin(ctx.order, 'accept_proposal')
  assert.equal(result.status, 'confirmed')
})

test('rejecting an expired but identified proposal preserves the original reason and receipt', async () => {
  const ctx = setup('reject_proposal'); ctx.order.proposal.expires_at = '2020-01-01T00:00:00'; ctx.order.proposal.expired = true
  assert.equal((await ctx.controller.begin(ctx.order, 'reject_proposal', '  Original reason  ')).status, 'confirmed')
  assert.equal(ctx.calls[0].at(-1), 'Original reason')
})
test('same-request recovery with an invalid version is discarded', async () => {
  const ctx = setup('accept_proposal', () => ({}), { request_id: id, status: 'invoice_created', row_version: true })
  await ctx.controller.begin(ctx.order, 'accept_proposal')
  assert.equal(ctx.controller.state.status, 'uncertain'); assert.equal(ctx.controller.state.latest, undefined)
  assert.equal(ctx.controller.state.error.code, 'INVALID_RESPONSE')
})
test('scope change during GET recovery retains the preceding dispatched action uncertainty', async () => {
  const ctx = setup('accept_proposal', () => ({})); let finish, entered
  const start = new Promise(resolve => { entered = resolve })
  ctx.api.order = () => new Promise(resolve => { finish = resolve; entered() })
  const pending = ctx.controller.begin(ctx.order, 'accept_proposal'); await start
  ctx.listeners.forEach(fn => fn({ reason: 'another-tab' })); finish(ctx.order)
  await assert.rejects(pending, { code: 'STALE_SCOPE', uncertain: true })
  assert.deepEqual(ctx.controller.state, { status: 'idle' })
})
test('PI action with missing original document binding is refused before dispatch', () => {
  const ctx = setup('reject_pi'); delete ctx.order.pi_amendment.proposal.bound_invoice_document_version
  assert.throws(() => ctx.controller.begin(ctx.order, 'reject_pi', 'Original reason'), { code: 'PROPOSAL_UNAVAILABLE' })
  assert.deepEqual(ctx.calls, [])
})
