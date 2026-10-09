import test from 'node:test'
import assert from 'node:assert/strict'
import { createSubmission } from '../src/state/submission.mjs'
import { PortalError } from '../src/api/client.mjs'

const KEY = '11111111-1111-4111-8111-111111111111'
const body = () => ({ quote_id: KEY, quote_content_hash: 'a'.repeat(64), customer_po: 'PO 1', remark: 'Customer note' })
const receipt = { request_id: KEY, request_no: 'REQ-1', status: 'submitted' }
const uncertain = () => new PortalError('NETWORK_ERROR', 'Unknown', { uncertain: true })
const missing = () => new PortalError('RESOURCE_NOT_FOUND', 'Missing', { status: 404 })
function deferred() { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function fixture() {
  const entries = new Map(), listeners = new Set(), calls = []
  const storage = { setItem: (k, v) => entries.set(k, v), getItem: k => entries.get(k), removeItem: k => entries.delete(k) }
  const api = {
    session: { me: { account_public_id: 'buyer-a' } },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    async submit(key, value) { calls.push({ key, body: value }); return receipt },
    async orderByKey(key) { calls.push({ read: key }); return receipt },
  }
  const submission = createSubmission({ api, storage, newKey: () => KEY })
  return { api, submission, storage, entries, listeners, calls }
}

test('successful checkout uses a fresh frozen body and removes the recovery marker', async () => {
  const { submission, calls, entries } = fixture()
  const input = body()
  const result = await submission.begin(input)
  input.remark = 'changed'
  assert.equal(result.status, 'confirmed')
  assert.equal(calls[0].body.remark, 'Customer note')
  assert.equal(Object.isFrozen(calls[0].body), true)
  assert.equal(entries.size, 0)
})

test('double click cannot start a second submission', async () => {
  const { api, submission } = fixture(), gate = deferred()
  api.submit = () => gate.promise
  const first = submission.begin(body())
  assert.throws(() => submission.begin(body()), { code: 'SUBMISSION_PENDING' })
  gate.resolve(receipt)
  await first
})

test('lost response recovers the committed result with GET, without retrying POST', async () => {
  const { api, submission, calls } = fixture()
  let posts = 0
  api.submit = async () => { posts++; throw uncertain() }
  assert.equal((await submission.begin(body())).status, 'confirmed')
  assert.equal(posts, 1)
  assert.deepEqual(calls, [{ read: KEY }])
})

test('missing recovery result stays uncertain and explicit retry reuses exact key and body', async () => {
  const { api, submission, entries } = fixture()
  const posts = []
  api.submit = async (key, payload) => { posts.push({ key, payload }); if (posts.length === 1) throw uncertain(); return receipt }
  api.orderByKey = async () => { throw missing() }
  const input = body()
  assert.equal((await submission.begin(input)).status, 'uncertain')
  assert.throws(() => submission.begin(body()), { code: 'SUBMISSION_PENDING' })
  assert.deepEqual([...entries.values()].map(JSON.parse), [{ key: KEY }])
  input.customer_po = 'different'
  await submission.retry()
  assert.equal(posts[0].key, posts[1].key)
  assert.strictEqual(posts[0].payload, posts[1].payload)
  assert.equal(posts[1].payload.customer_po, 'PO 1')
})

test('refresh stores only a scoped key and permits recovery, never reconstruction of POST', async () => {
  const { api, storage, submission } = fixture()
  storage.setItem('leshine.portal.pending:buyer-a', JSON.stringify({ key: KEY }))
  assert.throws(() => submission.begin(body()), { code: 'SUBMISSION_PENDING' })
  assert.equal(submission.restorePending(), true)
  assert.equal(submission.state.canRetry, false)
  assert.throws(() => submission.retry(), { code: 'INVALID_ACTION' })
  assert.equal((await submission.recover()).status, 'confirmed')
  api.session = { me: { account_public_id: 'buyer-b' } }
  const other = createSubmission({ api, storage })
  assert.equal(other.restorePending(), false)
})

test('scope change clears state and refuses late success without removing saved key', async () => {
  const { api, submission, listeners, entries } = fixture(), gate = deferred()
  api.submit = () => gate.promise
  const pending = submission.begin(body())
  for (const listener of listeners) listener({ reason: 'another-tab' })
  gate.resolve(receipt)
  await assert.rejects(pending, { code: 'STALE_SCOPE', uncertain: true })
  assert.equal(submission.state.status, 'idle')
  assert.equal(entries.size, 1)
})

test('definite first rejection clears marker, while a retry rejection cannot erase unknown outcome', async () => {
  const { api, submission, entries } = fixture()
  api.submit = async () => { throw new PortalError('QUOTE_EXPIRED', 'Expired', { status: 409 }) }
  assert.equal((await submission.begin(body())).status, 'failed')
  assert.equal(entries.size, 0)
  api.submit = async () => { throw uncertain() }
  api.orderByKey = async () => { throw missing() }
  await submission.begin(body())
  api.submit = async () => { throw new PortalError('QUOTE_EXPIRED', 'Expired', { status: 409 }) }
  assert.equal((await submission.retry()).status, 'uncertain')
  assert.equal(entries.size, 1)
})

test('malformed success is recovered rather than treated as a confirmed order', async () => {
  const { api, submission } = fixture()
  api.submit = async () => ({})
  assert.equal((await submission.begin(body())).status, 'confirmed')
})

test('storage unavailable is explicit and does not invent refresh recovery', async () => {
  const { api } = fixture(), gate = deferred()
  api.submit = () => gate.promise
  const submission = createSubmission({ api, storage: { getItem() { return null }, setItem() { throw new Error('disabled') } }, newKey: () => KEY })
  const pending = submission.begin(body())
  assert.equal(submission.state.refreshRecovery, false)
  gate.resolve(receipt)
  await pending
})
