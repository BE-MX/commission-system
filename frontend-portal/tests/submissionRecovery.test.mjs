import test from 'node:test'
import assert from 'node:assert/strict'
import { createSubmission } from '../src/state/submission.mjs'
import { PortalError } from '../src/api/client.mjs'

const key = '11111111-1111-4111-8111-111111111111'
const otherKey = '22222222-2222-4222-8222-222222222222'
const slot = 'leshine.portal.pending:buyer-a'
const body = { quote_id: key, quote_content_hash: 'a'.repeat(64) }
const receipt = { request_id: key, request_no: 'REQ-1' }
function setup(raw, options = {}) {
  const values = new Map(raw === undefined ? [] : [[slot, raw]])
  const calls = []; let generated = 0
  const storage = {
    getItem(k) { if (options.readFails) throw new Error('PRIVATE_STORAGE_ERROR'); return values.get(k) ?? null },
    setItem(k, v) { values.set(k, v) }, removeItem(k) { values.delete(k) },
  }
  const api = { session: { me: { account_public_id: 'buyer-a' } }, subscribe: () => () => {},
    async submit(k, payload) { calls.push(['POST', k, payload]); return receipt },
    async orderByKey(k) { calls.push(['GET', k]); return receipt } }
  const submission = createSubmission({ api, storage, newKey: () => { generated++; return key } })
  return { values, storage, calls, api, submission, generated: () => generated }
}

for (const raw of ['{broken', '', 'null', 'false', '[]', '{}', '{"key":7}', '{"key":"bad"}', JSON.stringify({ key, customer_po: 'PRIVATE_PO' })]) {
  test(`corrupt persisted marker blocks new key and restore: ${raw}`, () => {
    const ctx = setup(raw)
    assert.throws(() => ctx.submission.begin(body), { code: 'RECOVERY_RECORD_INVALID' })
    assert.throws(() => ctx.submission.restorePending(), { code: 'RECOVERY_RECORD_INVALID' })
    assert.equal(ctx.generated(), 0); assert.deepEqual(ctx.calls, [])
    assert.equal(ctx.values.get(slot), raw)
    assert.equal(ctx.submission.state.status, 'idle')
  })
}
test('unreadable storage is not proof that no prior order exists', () => {
  const ctx = setup(JSON.stringify({ key: otherKey }), { readFails: true })
  assert.throws(() => ctx.submission.begin(body), { code: 'RECOVERY_STORAGE_UNAVAILABLE' })
  assert.throws(() => ctx.submission.restorePending(), { code: 'RECOVERY_STORAGE_UNAVAILABLE' })
  assert.equal(ctx.generated(), 0); assert.deepEqual(ctx.calls, [])
  assert.equal(ctx.values.get(slot), JSON.stringify({ key: otherKey }))
})
test('confirmed response cannot erase a different same-account pending reference', async () => {
  const ctx = setup(); let finish
  ctx.api.submit = () => new Promise(resolve => { finish = resolve })
  const pending = ctx.submission.begin(body)
  ctx.storage.setItem(slot, JSON.stringify({ key: otherKey }))
  finish(receipt); assert.equal((await pending).status, 'confirmed')
  assert.equal(ctx.values.get(slot), JSON.stringify({ key: otherKey }))
  assert.throws(() => ctx.submission.begin(body), { code: 'SUBMISSION_PENDING' })
  assert.equal(ctx.generated(), 1)
})
test('definite rejection cannot erase a replacement pending reference', async () => {
  const ctx = setup(); let fail
  ctx.api.submit = () => new Promise((resolve, reject) => { fail = reject })
  const pending = ctx.submission.begin(body)
  ctx.storage.setItem(slot, JSON.stringify({ key: otherKey }))
  fail(new PortalError('QUOTE_EXPIRED', 'Expired', { status: 409 }))
  assert.equal((await pending).status, 'failed')
  assert.equal(ctx.values.get(slot), JSON.stringify({ key: otherKey }))
})
test('a valid restored reference is GET-only and clears only its own marker', async () => {
  const ctx = setup(JSON.stringify({ key }))
  assert.equal(ctx.submission.restorePending(), true)
  assert.throws(() => ctx.submission.retry(), { code: 'INVALID_ACTION' })
  assert.equal((await ctx.submission.recover()).status, 'confirmed')
  assert.deepEqual(ctx.calls, [['GET', key]]); assert.equal(ctx.values.has(slot), false)
  assert.equal(ctx.generated(), 0)
})
test('another account marker is neither read nor displayed nor deleted', async () => {
  const ctx = setup('{broken')
  ctx.api.session = { me: { account_public_id: 'buyer-b' } }
  assert.equal(ctx.submission.restorePending(), false)
  assert.equal((await ctx.submission.begin(body)).status, 'confirmed')
  assert.equal(ctx.values.get(slot), '{broken')
})
test('absent storage deliberately supports only in-memory recovery', async () => {
  const api = { session: { me: { account_public_id: 'buyer-a' } }, subscribe: () => () => {},
    async submit() { return receipt } }
  const submission = createSubmission({ api, newKey: () => key })
  assert.equal(submission.restorePending(), false)
  assert.equal((await submission.begin(body)).status, 'confirmed')
})

test('same key but changed raw marker is retained after a late confirmed response', async () => {
  const ctx = setup(); let finish
  ctx.api.submit = () => new Promise(resolve => { finish = resolve })
  const pending = ctx.submission.begin(body)
  const replacement = '{ "key" : "' + key + '" }'
  ctx.storage.setItem(slot, replacement)
  finish(receipt); assert.equal((await pending).status, 'confirmed')
  assert.equal(ctx.values.get(slot), replacement)
})
test('cleanup read failure preserves marker without hiding a known confirmed result', async () => {
  const ctx = setup(); let finish
  ctx.api.submit = () => new Promise(resolve => { finish = resolve })
  const pending = ctx.submission.begin(body)
  ctx.storage.getItem = () => { throw new Error('PRIVATE_CLEANUP_ERROR') }
  finish(receipt); assert.equal((await pending).status, 'confirmed')
  assert.equal(ctx.values.get(slot), JSON.stringify({ key }))
  assert.throws(() => ctx.submission.begin(body), { code: 'RECOVERY_STORAGE_UNAVAILABLE' })
})
test('silent failed storage write is explicitly in-memory, not reliable refresh recovery', async () => {
  const ctx = setup(); let finish
  ctx.storage.setItem = () => {}
  ctx.api.submit = () => new Promise(resolve => { finish = resolve })
  const pending = ctx.submission.begin(body)
  assert.equal(ctx.submission.state.refreshRecovery, false)
  finish(receipt); assert.equal((await pending).status, 'confirmed')
})
