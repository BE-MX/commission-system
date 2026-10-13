import assert from 'node:assert/strict'
import test from 'node:test'
import { once } from 'node:events'
import { createApp } from '../src/server.js'
import { fakeManager, message, tick, authorization } from './fixtures.mjs'
import { Projector } from '../src/projection.js'

async function httpFixture(t, options) {
  const result = fakeManager(t, options)
  const server = createApp(result.manager, 'synthetic-key').listen(0, '127.0.0.1')
  await once(server, 'listening')
  result.onCleanup(() => { server.closeAllConnections(); server.close() })
  const url = `http://127.0.0.1:${server.address().port}`
  return { ...result, async request(route, { body, authorized = true, method = body ? 'POST' : 'GET' } = {}) {
    const response = await fetch(`${url}${route}`, { method, headers: { ...(authorized ? { Authorization: 'Bearer synthetic-key' } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined })
    return { status: response.status, headers: response.headers, value: await response.json() }
  } }
}

test('HTTP protected health and all v1/v2 routes reject missing Bearer, no permissive CORS', async t => {
  const { request } = await httpFixture(t)
  for (const route of ['/health', '/internal/v1/conversations?account_uid=account_a', '/internal/v2/accounts/account_a']) {
    assert.equal((await request(route, { authorized: false })).status, 401)
  }
  const health = await request('/health')
  assert.equal(health.value.provider, 'baileys')
  assert.equal(health.headers.get('access-control-allow-origin'), null)
  assert.equal(health.headers.get('cache-control'), 'no-store')
})

test('v2 durable feed and v1 persistent pagination work offline, preserve end cursor and chat isolation', async t => {
  const { store, request } = await httpFixture(t)
  const lease = store.acquire('account_a')
  store.patchAccount(lease, { status: 'active', connection_state: 'reconnecting' })
  const projector = new Projector(store)
  projector.ingest(lease, 'messages.upsert', { messages: [message('a'), message('b', 'same timestamp'),
    message('other', 'another chat', 10, { remoteJid: '15550003333@s.whatsapp.net' })] })
  store.release(lease)
  let cursor = '0'; const all = []
  for (let i = 0; i < 20; i++) {
    const page = await request(`/internal/v2/changes?account_uid=account_a&limit=2&cursor=${cursor}`)
    assert.equal(page.status, 200)
    all.push(...page.value.data.items)
    assert.equal(page.value.data.account.session_generation, 1)
    cursor = page.value.data.next_cursor
    if (!page.value.data.has_more) break
  }
  assert.equal(all.filter(item => item.kind === 'message').length, 3)
  assert.equal(all.every(item => item.session_generation === 1 && item.consent_version === '1'), true)
  const end = await request(`/internal/v2/changes?account_uid=account_a&cursor=${cursor}`)
  assert.equal(end.value.data.next_cursor, cursor)
  assert.equal(end.value.data.items.length, 0)
  const own = await request('/internal/v1/messages?account_uid=account_a&chat_id=15550002222%40s.whatsapp.net&limit=1')
  assert.equal(own.value.data.items.length, 1)
  assert.equal(own.value.data.has_more, true)
  const next = await request(`/internal/v1/messages?account_uid=account_a&chat_id=15550002222%40s.whatsapp.net&limit=1&cursor=${own.value.data.next_cursor}`)
  assert.equal(next.value.data.items[0].external_message_id, 'b')
  const empty = await request(`/internal/v1/messages?account_uid=account_a&chat_id=15550002222%40s.whatsapp.net&cursor=${next.value.data.next_cursor}`)
  assert.equal(empty.value.data.next_cursor, next.value.data.next_cursor)
  const chats = await request('/internal/v1/conversations?account_uid=account_a')
  assert.ok(chats.value.data.items.length > 0)
})

test('HTTP bad cursor/limits stay explicit, paused bodies are denied and metadata stays inspectable', async t => {
  const { request } = await httpFixture(t)
  for (const query of ['cursor=-1', 'cursor=NaN', 'cursor=9007199254740992', 'limit=0', 'limit=501', 'limit=x']) {
    assert.equal((await request(`/internal/v2/changes?account_uid=account_a&${query}`)).status, 400)
  }
  const pause = await request('/internal/v2/accounts/account_a/pause', { method: 'POST' })
  assert.equal(pause.value.data.status, 'paused')
  assert.equal((await request('/internal/v2/changes?account_uid=account_a')).status, 403)
  assert.equal((await request('/internal/v1/messages?account_uid=account_a')).status, 403)
  const meta = await request('/internal/v2/accounts/account_a')
  assert.equal(meta.value.data.provider, 'baileys')
  assert.equal(meta.value.data.sync_state, 'paused')
})

test('HTTP bind operation UID readback is idempotent and QR response stays transient', async t => {
  const { request, sockets, setAuthorization } = await httpFixture(t)
  const body = { account_uid: 'account_a', ark_user_id: 7, consent_version: '1', provider: 'baileys', bind_session_uid: 'bind_readback' }
  const first = await request('/internal/v1/bind-sessions', { body })
  assert.equal(first.value.data.account_uid, 'account_a')
  assert.equal(first.value.data.qr_code_url, null)
  sockets[0].ev.emit('connection.update', { qr: 'SYNTHETIC_TRANSIENT_QR' })
  await tick()
  const readback = await request('/internal/v1/bind-sessions/bind_readback')
  assert.ok(readback.value.data.qr_code_url.startsWith('data:image/png;base64,'))
  assert.equal(readback.headers.get('cache-control'), 'no-store')
  const repeated = await request('/internal/v1/bind-sessions', { body })
  assert.equal(repeated.value.data.bind_session_uid, 'bind_readback')
  assert.equal(sockets.length, 1)
  setAuthorization({ ...authorization, ark_user_id: 8 })
  assert.equal((await request('/internal/v1/bind-sessions/bind_readback')).status, 403)
})
