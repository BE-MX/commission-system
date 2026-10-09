import test from 'node:test'
import assert from 'node:assert/strict'
import { createPortalClient } from '../src/api/client.mjs'

const ID = '11111111-1111-4111-8111-111111111111'
const OTHER = '22222222-2222-4222-8222-222222222222'
const identity = (id = ID) => ({ me: { account_public_id: id, company_display_name: 'Example' }, capabilities: { view_catalog: true }, csrf_token: `csrf-${id}` })
const ok = (data, status = 200) => new Response(JSON.stringify({ code: status, message: 'OK', data }), { status, headers: { 'Content-Type': 'application/json' } })
const failure = (status, code) => new Response(JSON.stringify({ code: status, message: 'Denied', data: { error_code: code, trace_id: 'trace-1', issues: [{ field: 'quantity' }] } }), { status })
function deferred() { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function setup(...responses) {
  const calls = []
  const client = createPortalClient({ fetchImpl: async (...args) => {
    calls.push(args)
    const next = responses.shift()
    if (next instanceof Error) throw next
    if (typeof next === 'function') return next(...args)
    assert.ok(next, 'unexpected fetch')
    return next
  } })
  return { client, calls }
}

test('private requests require a verified session; session has no bearer or CSRF token', async () => {
  const { client, calls } = setup(ok(identity()))
  await assert.rejects(client.catalog(), { code: 'SESSION_REQUIRED' })
  assert.equal(calls.length, 0)
  const session = await client.restore()
  assert.equal(session.me.account_public_id, ID)
  assert.equal(session.csrf_token, undefined)
  assert.equal(Object.isFrozen(session.capabilities), true)
})

test('requests stay same-origin with no-store, CSRF and exact version/key contracts', async () => {
  const { client, calls } = setup(ok(identity()), ok({}), ok({}), ok({}))
  await client.restore()
  await client.submit(ID, { quote_id: OTHER, quote_content_hash: 'a'.repeat(64) })
  await client.cancel(ID, '9007199254740993', 'No longer needed')
  await client.catalog({ keyword: 'Black & gold', in_stock_only: false })
  const [, submit] = calls[1]
  assert.equal(submit.credentials, 'same-origin')
  assert.equal(submit.redirect, 'error')
  assert.equal(submit.cache, 'no-store')
  assert.equal(submit.headers['X-Portal-CSRF'], `csrf-${ID}`)
  assert.equal(submit.headers['Idempotency-Key'], ID)
  assert.equal(submit.headers.Authorization, undefined)
  assert.equal(calls[2][1].headers['If-Match'], '"9007199254740993"')
  assert.equal(calls[3][0], '/api/portal/v1/catalog?keyword=Black+%26+gold&in_stock_only=false')
  assert.throws(() => client.cancel(ID, 9007199254740992, 'No'), { code: 'INVALID_INPUT' })
  assert.throws(() => client.product('https://attacker.invalid'), { code: 'INVALID_INPUT' })
})

test('bootstrap, activation and verify use preauth CSRF; wrong OTP remains retryable', async () => {
  const { client, calls } = setup(ok({ csrf_token: 'preauth' }), ok({ challenge_id: ID }, 202), failure(401, 'AUTH_FAILED'), ok(identity()))
  await client.bootstrap()
  await client.challenge({ email: 'buyer@example.test', invitationToken: 'x'.repeat(32) })
  assert.equal(JSON.parse(calls[1][1].body).purpose, 'activate')
  await assert.rejects(client.verify(ID, '123456'), { code: 'AUTH_FAILED', traceId: 'trace-1' })
  await client.verify(ID, '654321')
  assert.equal(calls[3][1].headers['X-Portal-CSRF'], 'preauth')
  assert.equal(client.session.me.account_public_id, ID)
})

test('write connection failure is uncertain and never automatically retried', async () => {
  const { client, calls } = setup(ok(identity()), new TypeError('Connection reset'))
  await client.restore()
  await assert.rejects(client.submit(ID, {}), { code: 'NETWORK_ERROR', uncertain: true })
  assert.equal(calls.length, 2)
})

test('write 503 and malformed successful response require result recovery', async () => {
  const { client, calls } = setup(ok(identity()), failure(503, 'TEMPORARILY_UNAVAILABLE'), new Response('<html>'), ok({ request_id: ID }))
  await client.restore()
  await assert.rejects(client.submit(ID, {}), { status: 503, uncertain: true })
  await assert.rejects(client.submit(ID, {}), { code: 'INVALID_RESPONSE', uncertain: true })
  assert.equal((await client.orderByKey(ID)).request_id, ID)
  assert.equal(calls.length, 4)
})

test('late response from previous account cannot cross a restored scope, even when fetch ignores abort', async () => {
  const slow = deferred()
  const { client, calls } = setup(ok(identity()), () => slow.promise, ok(identity(OTHER)))
  await client.restore()
  const old = client.catalog()
  await client.restore()
  assert.equal(calls[1][1].signal.aborted, true)
  slow.resolve(ok({ secret: 'old customer price' }))
  await assert.rejects(old, { code: 'STALE_SCOPE' })
  assert.equal(client.session.me.account_public_id, OTHER)
})

test('scope change during JSON parsing also discards the previous response', async () => {
  const json = deferred()
  const { client } = setup(ok(identity()), { ok: true, json: () => json.promise }, ok(identity(OTHER)))
  await client.restore()
  const old = client.orders()
  await Promise.resolve()
  await client.restore()
  json.resolve({ code: 200, data: { secret: 'old orders' } })
  await assert.rejects(old, { code: 'STALE_SCOPE' })
})

test('logout immediately aborts private reads, preserves CSRF for server revocation, and serializes auth', async () => {
  const read = deferred(), logout = deferred()
  const { client, calls } = setup(ok(identity()), () => read.promise, () => logout.promise)
  await client.restore()
  const old = client.catalog()
  const signingOut = client.logout()
  assert.equal(client.session, null)
  assert.equal(calls[1][1].signal.aborted, true)
  assert.equal(calls[2][1].headers['X-Portal-CSRF'], `csrf-${ID}`)
  await assert.rejects(client.bootstrap(), { code: 'AUTH_BUSY' })
  logout.resolve(ok({ signed_out: true }))
  await signingOut
  read.resolve(ok({ secret: 'old' }))
  await assert.rejects(old, { code: 'STALE_SCOPE' })
})

test('expired session clears all private data and invalidates other tabs without transmitting data', async () => {
  const messages = [], listeners = new Set()
  const channel = { addEventListener: (_, fn) => listeners.add(fn), removeEventListener: (_, fn) => listeners.delete(fn), postMessage: msg => messages.push(msg), close() {} }
  const queue = [ok(identity()), failure(401, 'AUTH_REQUIRED'), ok(identity(OTHER))]
  const client = createPortalClient({ fetchImpl: async () => queue.shift(), channel })
  await client.restore()
  await assert.rejects(client.orders(), { code: 'SESSION_EXPIRED' })
  assert.equal(client.session, null)
  assert.deepEqual(messages, [{ type: 'portal-session-changed' }])
  await client.restore()
  for (const listener of listeners) listener({ data: { type: 'portal-session-changed' } })
  assert.equal(client.session, null)
  assert.equal(messages.length, 1, 'received invalidation must not loop broadcasts')
  client.dispose()
  assert.equal(listeners.size, 0)
})

test('403 is an action error rather than a false sign-out; details remain available', async () => {
  const { client } = setup(ok(identity()), failure(403, 'ACTION_FORBIDDEN'))
  await client.restore()
  await assert.rejects(client.quote({}), error => error.code === 'ACTION_FORBIDDEN' && error.issues[0].field === 'quantity')
  assert.ok(client.session)
})

test('PDF remains authenticated, rejects HTML and drops bytes after scope changes', async () => {
  const bytes = deferred()
  const { client } = setup(ok(identity()), new Response('<html>'),
    { ok: true, headers: new Headers({ 'Content-Type': 'application/pdf' }), blob: () => bytes.promise }, ok(identity(OTHER)))
  await client.restore()
  await assert.rejects(client.download(ID), { code: 'INVALID_RESPONSE' })
  const old = client.download(ID)
  await Promise.resolve()
  await client.restore()
  bytes.resolve(new Blob(['old PDF']))
  await assert.rejects(old, { code: 'STALE_SCOPE' })
})

test('caller abort and disposed client do not leak results', async () => {
  const { client, calls } = setup(ok(identity()))
  await client.restore()
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(client.catalog({}, controller.signal), { code: 'REQUEST_ABORTED' })
  assert.equal(calls.length, 1)
  client.dispose()
  await assert.rejects(client.catalog(), { code: 'CLIENT_CLOSED' })
})

test('malformed session is never accepted as logged in', async () => {
  const { client } = setup(ok({ me: { account_public_id: ID }, csrf_token: '' }))
  await assert.rejects(client.restore(), { code: 'INVALID_RESPONSE' })
  assert.equal(client.session, null)
})

test('scope change preserves uncertain classification of already dispatched writes', async () => {
  const write = deferred()
  const { client } = setup(ok(identity()), () => write.promise, ok(identity(OTHER)))
  await client.restore()
  const pending = client.submit(ID, {})
  await client.restore()
  write.resolve(ok({ request_id: ID }))
  await assert.rejects(pending, { code: 'STALE_SCOPE', uncertain: true })
})

test('non-JSON 401 clears local session before trying to read a body', async () => {
  const { client } = setup(ok(identity()), new Response('<html>Denied</html>', { status: 401 }))
  await client.restore()
  await assert.rejects(client.orders(), { code: 'SESSION_EXPIRED' })
  assert.equal(client.session, null)
})

test('failed logout can be manually retried without restoring private session', async () => {
  const { client, calls } = setup(ok(identity()), new TypeError('Connection reset'), ok({ signed_out: true }))
  await client.restore()
  await assert.rejects(client.logout(), { code: 'NETWORK_ERROR', uncertain: true })
  assert.equal(client.session, null)
  await client.logout()
  assert.equal(calls[1][1].headers['X-Portal-CSRF'], calls[2][1].headers['X-Portal-CSRF'])
  assert.equal(client.session, null)
})
