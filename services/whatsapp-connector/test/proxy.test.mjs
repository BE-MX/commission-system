import assert from 'node:assert/strict'
import test from 'node:test'
import { createServer } from 'node:http'
import { connect } from 'node:net'
import { once } from 'node:events'
import { WebSocketServer } from 'ws'
import { WebSocketClient } from 'baileys/lib/Socket/Client/websocket.js'
import { getHttpStream } from 'baileys/lib/Utils/messages-media.js'
import { whatsappProxyAgent, whatsappProxyDispatcher } from '../src/proxy.js'
import { fakeManager, authorization } from './fixtures.mjs'

test('dedicated proxy is optional and rejects invalid config without exposing credentials', () => {
  assert.equal(whatsappProxyAgent({ HTTPS_PROXY: 'http://unrelated:8080' }), undefined)
  for (const value of ['invalid-secret', 'socks5://localhost:1080', 'http://localhost/path', 'http://localhost/?secret=value']) {
    assert.throws(() => whatsappProxyAgent({ WHATSAPP_PROXY_URL: value }), /^Error: invalid_whatsapp_proxy_url$/)
  }
  const agent = whatsappProxyAgent({ WHATSAPP_PROXY_URL: 'http://localhost:1080' })
  assert.equal(agent.proxy.port, '1080')
  agent.destroy()
})

test('proxy reaches WhatsApp socket and media, while Ark authorization stays independent', async t => {
  const agent = whatsappProxyAgent({ WHATSAPP_PROXY_URL: 'http://localhost:1080' })
  t.after(() => agent.destroy())
  const dispatcher = whatsappProxyDispatcher({ WHATSAPP_PROXY_URL: 'http://localhost:1080' })
  t.after(() => dispatcher.destroy())
  const { manager, sockets } = fakeManager(t, { agent, dispatcher })
  await manager.bind({ account_uid: 'account_a', ark_user_id: authorization.ark_user_id,
    provider: 'baileys', consent_version: '1', bind_session_uid: 'bind_proxy' })
  assert.equal(sockets[0].config.agent, agent)
  assert.equal(sockets[0].config.fetchAgent, agent)
  assert.equal(sockets[0].config.options.dispatcher, dispatcher)
})

test('stopped connection reports terminal binding status even before it produced QR', async t => {
  const { manager, store } = fakeManager(t)
  await manager.bind({ account_uid: 'account_a', ark_user_id: authorization.ark_user_id,
    provider: 'baileys', consent_version: '1', bind_session_uid: 'bind_stopped' })
  manager.protect(manager.entries.get('account_a'), 'reconnect_exhausted', 'reconnect_required')
  assert.equal(store.account('account_a').status, 'reconnect_required')
  assert.equal(manager.session('bind_stopped').status, 'reconnect_required')
  assert.equal(manager.session('bind_stopped').qr_code_url, null)
})

test('installed Baileys WebSocket transport reaches target through HTTP CONNECT proxy', async t => {
  const target = createServer((request, response) => response.end('synthetic-history-download'))
  const ws = new WebSocketServer({ server: target })
  target.listen(0, '127.0.0.1'); await once(target, 'listening')
  const destination = `127.0.0.1:${target.address().port}`
  const tunnels = new Set(), requests = []
  const proxy = createServer()
  proxy.on('connect', (request, client, head) => {
    requests.push(request.url)
    const upstream = connect(target.address().port, '127.0.0.1', () => {
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n')
      if (head.length) upstream.write(head)
      upstream.pipe(client); client.pipe(upstream)
    })
    tunnels.add(client); tunnels.add(upstream)
  })
  proxy.listen(0, '127.0.0.1'); await once(proxy, 'listening')
  const agent = whatsappProxyAgent({ WHATSAPP_PROXY_URL: `http://127.0.0.1:${proxy.address().port}` })
  const dispatcher = whatsappProxyDispatcher({ WHATSAPP_PROXY_URL: `http://127.0.0.1:${proxy.address().port}` })
  const client = new WebSocketClient(new URL(`ws://${destination}`), { agent, connectTimeoutMs: 2000 })
  t.after(async () => {
    client.socket?.terminate(); agent.destroy()
    await dispatcher.destroy()
    for (const socket of tunnels) socket.destroy()
    for (const socket of ws.clients) socket.terminate()
    ws.close(); target.close(); proxy.close()
  })
  const opened = once(client, 'open', { signal: AbortSignal.timeout(3000) })
  client.connect(); await opened
  assert.deepEqual(requests, [destination])
  assert.equal(client.isOpen, true)
  const stream = await getHttpStream(`http://${destination}/history`, { dispatcher })
  const chunks = []
  for await (const chunk of stream) chunks.push(chunk)
  assert.equal(Buffer.concat(chunks).toString(), 'synthetic-history-download')
  assert.deepEqual(requests, [destination, destination])
})
