import assert from 'node:assert/strict'
import test from 'node:test'
import { EventEmitter } from 'node:events'
import { createDiagnostics } from '../src/diagnostics.js'
import { backendAuthorizer } from '../src/manager.js'
import { authorization, fakeManager, tick } from './fixtures.mjs'

test('diagnostics allow only fixed fields and use Beijing time across midnight', () => {
  const lines = []
  const diagnostic = createDiagnostics(line => lines.push(line), () => Date.parse('2026-10-14T16:00:01Z'))
  diagnostic('connection_closed', 'PRIVATE_ACCOUNT', { status_code: 408, classification: 'transient', registered: false,
    qr: 'PRIVATE_QR', message: 'PRIVATE_BODY', jid: 'PRIVATE_PHONE', stack: 'PRIVATE_KEY' })
  diagnostic('PRIVATE_EVENT', 'PRIVATE_ACCOUNT', { message: 'PRIVATE_BODY' })
  assert.equal(lines.length, 1)
  const value = JSON.parse(lines[0])
  assert.equal(value.at, '2026-10-15T00:00:01+08:00')
  assert.equal(value.event, 'connection_closed')
  assert.equal(value.status_code, 408)
  assert.equal(value.classification, 'transient')
  assert.equal(value.registered, false)
  assert.match(value.account, /^[a-f0-9]{16}$/)
  assert.equal(lines.join('').includes('PRIVATE_'), false)
  diagnostic('connection_closed', 'PRIVATE_ACCOUNT', { status_code: 'PRIVATE_ERROR', classification: 'PRIVATE_ERROR' })
  const invalid = JSON.parse(lines[1])
  assert.equal(invalid.status_code, null)
  assert.equal(invalid.classification, 'other')
})

test('authorization failures distinguish timeout, transport, HTTP, malformed JSON and denial without logging errors', async () => {
  const cases = [
    [async () => { throw Object.assign(new Error('PRIVATE_BODY'), { name: 'TimeoutError' }) }, 'timeout', 'request', null],
    [async () => { throw Object.assign(new Error('PRIVATE_BODY'), { cause: { code: 'ECONNREFUSED', secret: 'PRIVATE_KEY' } }) }, 'transport', 'request', null],
    [async () => ({ ok: false, status: 502 }), 'http_error', 'response', 502],
    [async () => ({ ok: true, status: 200, json: async () => { throw new Error('PRIVATE_BODY') } }), 'invalid_response', 'response', 200],
    [async () => ({ ok: true, status: 200, json: async () => ({ code: 200, data: { ...authorization, allowed: false } }) }), 'denied', 'validation', 200],
  ]
  for (const [fetcher, failure, phase, status] of cases) {
    const lines = []
    const check = backendAuthorizer('http://localhost', 'PRIVATE_KEY', fetcher, createDiagnostics(line => lines.push(line)))
    await assert.rejects(check('PRIVATE_ACCOUNT'), failure === 'denied' ? /authorization_denied/ : /authorization_unavailable/)
    assert.equal(lines.length, 1)
    const value = JSON.parse(lines[0])
    assert.equal(value.failure, failure)
    assert.equal(value.phase, phase)
    assert.equal(value.http_status, status)
    assert.ok(value.elapsed_ms >= 0)
    assert.equal(lines.join('').includes('PRIVATE_'), false)
  }
})

test('pairing milestones and refresh notifications are observed without changing the protocol; listeners are removed', async t => {
  const lines = []
  const diagnostic = createDiagnostics(line => lines.push(line))
  const { manager, sockets, store } = fakeManager(t, { diagnostic, retryBase: 10000 })
  const original = manager.socketFactory
  manager.socketFactory = config => { const socket = original(config); socket.ws = new EventEmitter(); return socket }
  const entry = await manager.start('account_a')
  const socket = sockets[0]
  socket.ws.emit('CB:notification,type:companion_reg_refresh', { content: 'PRIVATE_NODE' })
  socket.ev.emit('connection.update', { qr: 'PRIVATE_QR' })
  await tick()
  const update = { me: { id: 'PRIVATE_JID' }, registered: true, advSecretKey: 'PRIVATE_KEY' }
  // rc14 updates the same credentials object in its own earlier listener.
  Object.assign(socket.config.auth.creds, update)
  socket.ev.emit('creds.update', update)
  socket.ev.emit('connection.update', { connection: 'open' })
  await tick()
  assert.equal(store.account('account_a').status, 'active')
  socket.ev.emit('connection.update', { connection: 'close', lastDisconnect: { error: { output: { statusCode: 408 }, message: 'PRIVATE_ERROR' } } })
  await tick()
  assert.equal(entry.stopped, false)
  assert.equal(socket.ws.listenerCount('CB:notification,type:companion_reg_refresh'), 0)
  const events = lines.map(line => JSON.parse(line))
  for (const event of ['socket_start', 'companion_reg_refresh', 'qr_ready', 'pairing_credentials', 'connection_open', 'connection_closed']) {
    assert.ok(events.some(value => value.event === event), event)
  }
  const credentials = events.find(value => value.event === 'pairing_credentials')
  assert.equal(credentials.registered, true)
  assert.equal(credentials.has_identity, true)
  assert.equal(lines.join('').includes('PRIVATE_'), false)
  manager.shutdown()
})

test('diagnostic output failure never prevents authorization or protected pause', async t => {
  const diagnostic = createDiagnostics(() => { throw new Error('PRIVATE_SINK') })
  const check = backendAuthorizer('http://localhost', 'PRIVATE_KEY', async () => ({ ok: false, status: 503 }), diagnostic)
  await assert.rejects(check('account_a'), /authorization_unavailable/)
  const { manager, store } = fakeManager(t, { diagnostic })
  const entry = await manager.start('account_a')
  manager.protect(entry, 'authorization_unavailable')
  assert.equal(entry.stopped, true)
  assert.equal(store.account('account_a').status, 'paused')
})
