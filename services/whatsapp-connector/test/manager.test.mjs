import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { Manager, backendAuthorizer, classifyDisconnect } from '../src/manager.js'
import { error } from '../src/crypto.js'
import { encryptionKey, authorization, fakeManager, fixture, message, tick, sleep } from './fixtures.mjs'

test('authorization is validated before initial socket; denied/unknown fail closed', async t => {
  const { manager, sockets, setAuthorization, store } = fakeManager(t)
  setAuthorization({ ...authorization, allowed: false })
  await assert.rejects(manager.start('account_a'), /authorization_denied/)
  assert.equal(sockets.length, 0)
  setAuthorization({ ...authorization, ark_user_id: 8 })
  await assert.rejects(manager.start('account_a'), /authorization_changed/)
  assert.equal(sockets.length, 0)
  assert.equal(store.account('account_a').ark_user_id, 7)
})

test('periodic owner authorization closes socket and cancels events within configured interval', async t => {
  const { manager, store, sockets, setAuthorization } = fakeManager(t, { authInterval: 30, leaseTTL: 100 })
  const entry = await manager.start('account_a')
  setAuthorization(error('authorization_unavailable', 503))
  await sleep(70)
  assert.equal(entry.stopped, true)
  assert.equal(sockets[0].closed, true)
  assert.equal(sockets[0].ev.listenerCount('messages.upsert'), 0)
  assert.equal(store.account('account_a').status, 'paused')
  sockets[0].ev.emit('messages.upsert', { messages: [message('late')] })
  assert.equal(store.entities('account_a', 'message').length, 0)
  assert.equal(store.account('account_a').coverage.gap_reason, 'authorization_unavailable')
})

test('bounded memory queue and disk failure cause visible protected pause, no bodies logged', async t => {
  const { manager, store, sockets } = fakeManager(t, { maxQueueEvents: 1 })
  const entry = await manager.start('account_a')
  sockets[0].ev.emit('messages.upsert', { messages: [message('queued')] })
  sockets[0].ev.emit('messages.upsert', { messages: [message('excess')] })
  await entry.queue
  assert.equal(store.account('account_a').last_error_code, 'backpressure_gap')
  assert.equal(store.account('account_a').sync_state, 'paused')
  assert.equal(store.entities('account_a', 'message').length, 0)
  assert.equal(sockets[0].closed, true)
})

test('disk quota persists a safe gap marker while rolling back all projected event content', async t => {
  const { manager, store, sockets } = fakeManager(t)
  const entry = await manager.start('account_a')
  store.maxBytes = 1024
  sockets[0].ev.emit('messages.upsert', { messages: [message('quota')] })
  await entry.queue
  assert.equal(store.account('account_a').last_error_code, 'disk_capacity')
  assert.equal(store.entities('account_a', 'message').length, 0)
})

test('auth CAS/store failure protects the connection rather than issuing new identity', async t => {
  const { manager, store, sockets } = fakeManager(t)
  const entry = await manager.start('account_a')
  const revision = store.authGet(entry.lease, 'creds', ['current']).current.revision
  store.authSet(entry.lease, { creds: { current: { registered: true, immutable: 'existing-identity' } } }, { 'creds:current': revision })
  sockets[0].ev.emit('creds.update', { registered: true })
  assert.equal(entry.stopped, true)
  assert.equal(store.account('account_a').last_error_code, 'auth_cas_conflict')
  const lease = store.acquire('account_a')
  assert.equal(store.authGet(lease, 'creds', ['current']).current.value.immutable, 'existing-identity')
  store.release(lease)
})

test('disconnect classification, transient restart and timer cancellation are bounded', async t => {
  assert.equal(classifyDisconnect(401), 'reauth_required')
  assert.equal(classifyDisconnect(440), 'blocked')
  assert.equal(classifyDisconnect(515), 'restart')
  assert.equal(classifyDisconnect(408), 'transient')
  assert.equal(classifyDisconnect(500), 'protected_pause')
  const { manager, store, sockets } = fakeManager(t, { retryBase: 20, maxRetries: 1, random: () => 0 })
  const entry = await manager.start('account_a')
  sockets[0].ev.emit('connection.update', { connection: 'close', lastDisconnect: { error: { output: { statusCode: 408 } } } })
  await sleep(50)
  assert.equal(sockets.length, 2)
  assert.equal(sockets[0].ev.listenerCount('connection.update'), 0)
  sockets[1].ev.emit('connection.update', { connection: 'close', lastDisconnect: { error: { output: { statusCode: 408 } } } })
  await tick()
  assert.equal(entry.stopped, true)
  assert.equal(store.account('account_a').last_error_code, 'reconnect_exhausted')
  await sleep(50)
  assert.equal(sockets.length, 2)
})

test('loggedOut clears unusable auth and requires rebind; replaced remains protected', async t => {
  const { manager, store, sockets } = fakeManager(t)
  const entry = await manager.start('account_a')
  sockets[0].ev.emit('connection.update', { connection: 'close', lastDisconnect: { error: { output: { statusCode: 401 } } } })
  await tick()
  assert.equal(store.account('account_a').connection_state, 'reauth_required')
  assert.equal(store.account('account_a').needs_user_action, true)
  assert.equal(store.db.prepare('SELECT COUNT(*) AS count FROM auth').get().count, 0)
  assert.equal(entry.stopped, true)
})

test('bind is stable, QR is memory-only and restored credentials do not force QR', async t => {
  const { manager, store, sockets, filename, onCleanup } = fakeManager(t)
  const request = { account_uid: 'account_a', bind_session_uid: 'bind_operation', ark_user_id: 7, provider: 'baileys', consent_version: '1' }
  const session = await manager.bind(request)
  assert.equal(session.account_uid, 'account_a')
  sockets[0].ev.emit('connection.update', { qr: 'SYNTHETIC_QR_PRIVATE' })
  await tick()
  assert.ok(manager.session('bind_operation').qr_code_url)
  const serialized = JSON.stringify(store.entities('account_a', 'bind'))
  assert.equal(serialized.includes('qr_code_url'), false)
  assert.equal(serialized.includes('SYNTHETIC_QR_PRIVATE'), false)
  for (const suffix of ['', '-wal']) assert.equal(readFileSync(filename + suffix).includes(Buffer.from('SYNTHETIC_QR_PRIVATE')), false)
  const again = await manager.bind(request)
  assert.equal(again.bind_session_uid, session.bind_session_uid)
  assert.equal(sockets.length, 1)
  sockets[0].ev.emit('creds.update', { registered: true })
  sockets[0].ev.emit('connection.update', { connection: 'open' })
  await tick()
  assert.equal(manager.session('bind_operation').qr_code_url, null)
  const oldPrivate = sockets[0].config.auth.creds.noiseKey.private
  manager.shutdown()
  const restoredSockets = []
  const restored = new Manager(store, { authorize: async () => ({ ...authorization }), socketFactory: config => {
    const socket = { ev: sockets[0].ev, config, user: sockets[0].user, end() {} }
    restoredSockets.push(socket); return socket
  } })
  onCleanup(() => restored.shutdown())
  await restored.restore()
  assert.equal(restoredSockets.length, 1)
  assert.deepEqual(restoredSockets[0].config.auth.creds.noiseKey.private, oldPrivate)
  assert.equal(restoredSockets[0].config.auth.creds.registered, true)
  assert.equal(restored.session('bind_operation').qr_code_url, null)
  assert.equal(store.account('account_a').coverage.gap_reason, 'connector_restart_gap')
})

test('revoke pauses collection before logout and clears local credentials without claiming unproven peer acknowledgment', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].logout = async () => {
    assert.equal(store.account('account_a').status, 'revoking')
    assert.equal(sockets[0].closed, false)
    assert.equal(sockets[0].ev.listenerCount('messages.upsert'), 0)
    assert.ok(store.db.prepare('SELECT COUNT(*) AS count FROM auth').get().count > 0)
    sockets[0].ev.emit('messages.upsert', { messages: [message('logout-late')] })
  }
  const result = await manager.revoke('account_a')
  assert.equal(result.status, 'paused')
  assert.equal(result.revoke_state, 'remote_unconfirmed')
  assert.equal(result.local_credentials_cleared, true)
  assert.equal(result.logout_state, 'not_sent_no_identity')
  assert.equal(sockets[0].closed, true)
  assert.equal(store.entities('account_a', 'message').length, 0)
  assert.equal(store.db.prepare('SELECT COUNT(*) AS count FROM auth').get().count, 0)
  assert.throws(() => store.feed('account_a'), /account_paused/)
})

test('offline or failed logout retains remote_unconfirmed and requires phone-side action', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].logout = async () => { throw new Error('synthetic-network-unavailable') }
  const result = await manager.revoke('account_a')
  assert.equal(result.status, 'paused')
  assert.equal(result.revoke_state, 'remote_unconfirmed')
  assert.equal(result.needs_user_action, true)
  assert.equal(store.db.prepare('SELECT COUNT(*) AS count FROM auth').get().count, 0)
})

test('reauthorization changes consent while preserving registered auth and republishes only current consent', async t => {
  const { manager, store, sockets, setAuthorization } = fakeManager(t)
  const entry = await manager.start('account_a')
  sockets[0].ev.emit('creds.update', { registered: true })
  sockets[0].ev.emit('messages.upsert', { messages: [message('consented')] })
  await entry.queue
  const privateKey = sockets[0].config.auth.creds.noiseKey.private
  await manager.pause('account_a')
  assert.throws(() => store.feed('account_a'), /account_paused/)
  setAuthorization({ ...authorization, consent_version: '2', crm_shared: true })
  const account = await manager.reauthorize('account_a')
  assert.equal(account.consent_version, '2')
  assert.equal(account.crm_shared, true)
  assert.deepEqual(sockets[1].config.auth.creds.noiseKey.private, privateKey)
  const changes = store.feed('account_a').items
  assert.equal(changes.every(item => item.consent_version === '2' && item.payload.consent_version === '2'), true)
  assert.equal(changes.some(item => item.kind === 'message' && item.payload.external_message_id === 'consented'), true)
})

test('reauthorizing unregistered account requires explicit rebind without silently creating a socket', async t => {
  const { manager, sockets } = fakeManager(t)
  const result = await manager.reauthorize('account_a')
  assert.equal(result.last_error_code, 'rebind_required')
  assert.equal(result.needs_user_action, true)
  assert.equal(sockets.length, 0)
})

test('backend callback validation uses real envelope and denies unknown provider and failed requests', async () => {
  let requestedUrl
  const check = backendAuthorizer('http://127.0.0.1:8001/', 'synthetic-key', async (url, options) => {
    requestedUrl = url
    assert.equal(options.headers.Authorization, 'Bearer synthetic-key')
    assert.equal(options.redirect, 'error')
    return { ok: true, async json() { return { code: 200, data: { ...authorization } } } }
  })
  assert.equal((await check('account_a')).ark_user_id, 7)
  assert.equal(requestedUrl, 'http://127.0.0.1:8001/api/whatsapp/internal/accounts/account_a/authorization')
  for (const data of [{ ...authorization, allowed: false }, { ...authorization, provider: 'wwebjs' }, {}]) {
    const denied = backendAuthorizer('http://localhost', 'synthetic-key', async () => ({ ok: true, json: async () => ({ code: 200, data }) }))
    await assert.rejects(denied('account_a'), /authorization_denied/)
  }
  const unavailable = backendAuthorizer('http://localhost', 'synthetic-key', async () => { throw new Error('network') })
  await assert.rejects(unavailable('account_a'), /authorization_unavailable/)
})

test('an async QR callback from an old socket cannot mutate the reconnecting socket', async t => {
  let resolveQR
  const { manager, sockets, store } = fakeManager(t, { encodeQR: () => new Promise(resolve => { resolveQR = resolve }), retryBase: 20 })
  await manager.start('account_a')
  sockets[0].ev.emit('connection.update', { qr: 'OLD_SYNTHETIC_QR' })
  sockets[0].ev.emit('connection.update', { connection: 'close', lastDisconnect: { error: { output: { statusCode: 408 } } } })
  await sleep(50)
  assert.equal(sockets.length, 2)
  resolveQR('data:image/png;base64,OLD')
  await tick()
  assert.equal(manager.entries.get('account_a').qr, null)
  assert.equal(store.account('account_a').connection_state, 'reconnecting')
})

test('failed republishing leaves consent-changing account protected and cache inaccessible', async t => {
  const { manager, store, sockets, setAuthorization } = fakeManager(t)
  const entry = await manager.start('account_a')
  sockets[0].ev.emit('creds.update', { registered: true })
  sockets[0].ev.emit('messages.upsert', { messages: [message('cache')] })
  await entry.queue
  await manager.pause('account_a')
  setAuthorization({ ...authorization, consent_version: '2' })
  store.maxRows = 1
  await assert.rejects(manager.reauthorize('account_a'), /retention_capacity/)
  assert.equal(store.account('account_a').status, 'paused')
  assert.equal(store.account('account_a').last_error_code, 'retention_capacity')
  assert.throws(() => store.feed('account_a'), /account_paused/)
  assert.equal(sockets.length, 1)
})

test('pre-socket restore authorization failure replaces stale connected metadata with a safe paused gap', async t => {
  const { manager, store, sockets, setAuthorization } = fakeManager(t)
  const lease = store.acquire('account_a')
  store.patchAccount(lease, { status: 'active', connection_state: 'connected', sync_state: 'collecting' })
  store.release(lease)
  setAuthorization(error('authorization_unavailable', 503))
  await manager.restore()
  assert.equal(sockets.length, 0)
  assert.equal(store.account('account_a').status, 'paused')
  assert.equal(store.account('account_a').connection_state, 'protected_pause')
  assert.equal(store.account('account_a').coverage.gap_reason, 'authorization_unavailable')
})

test('a known device identity only proves logout request_sent, never remote device removal', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].ev.emit('creds.update', { registered: true, me: { id: '15550001111@s.whatsapp.net' } })
  const result = await manager.revoke('account_a')
  assert.equal(result.logout_state, 'request_sent')
  assert.equal(result.revoke_state, 'remote_unconfirmed')
  assert.equal(result.local_credentials_cleared, true)
  assert.equal(store.account('account_a').status, 'paused')
})
