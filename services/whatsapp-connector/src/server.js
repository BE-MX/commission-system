import dotenv from 'dotenv'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import express from 'express'
import { authenticateWith, connectorConfig } from './auth.js'
import { error } from './crypto.js'
import { Store } from './store.js'
import { Manager, backendAuthorizer } from './manager.js'
import { hash } from './projection.js'
import { whatsappProxyAgent, whatsappProxyDispatcher } from './proxy.js'

const asyncHandler = fn => (req, res, next) => Promise.resolve(fn(req, res)).catch(next)
function pagination(query) {
  const cursor = String(query.cursor || '0')
  if (!/^\d{1,16}$/.test(cursor) || !Number.isSafeInteger(Number(cursor))) throw error('invalid_cursor', 400)
  const limit = Number(query.limit || 100)
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw error('invalid_limit', 400)
  return { cursor: Number(cursor), limit }
}
export function createApp(manager, apiKey) {
  const app = express()
  app.disable('x-powered-by')
  app.use((req, res, next) => { res.set('Cache-Control', 'no-store'); next() })
  app.use(authenticateWith(apiKey))
  app.use(express.json({ limit: '32kb' }))
  app.get('/health', (req, res) => res.json({ status: 'ok', provider: 'baileys', storage: 'sqlite-single-host' }))
  app.post('/internal/v1/bind-sessions', asyncHandler(async (req, res) => {
    res.json({ code: 200, data: await manager.bind(req.body) })
  }))
  app.get('/internal/v1/bind-sessions/:bindSessionUid', asyncHandler(async (req, res) => {
    const session = manager.session(req.params.bindSessionUid)
    await manager.readable(session.account_uid)
    res.set('Cache-Control', 'no-store').json({ code: 200, data: session })
  }))
  app.get('/internal/v2/accounts/:uid', (req, res) => res.json({ code: 200, data: manager.metadata(manager.store.account(req.params.uid)) }))
  for (const [action, version] of [['pause', 'v2'], ['reauthorize', 'v2'], ['revoke', 'v1']]) {
    app.post(`/internal/${version}/accounts/:uid/${action}`, asyncHandler(async (req, res) => {
      res.json({ code: 200, data: await manager[action](req.params.uid) })
    }))
  }
  app.get('/internal/v2/changes', asyncHandler(async (req, res) => {
    const uid = String(req.query.account_uid || '')
    await manager.readable(uid)
    const { cursor, limit } = pagination(req.query)
    const data = manager.store.feed(uid, cursor, limit)
    data.account = manager.metadata(data.account)
    for (const item of data.items) if (item.kind === 'account') item.payload = manager.metadata(item.payload)
    res.json({ code: 200, data })
  }))
  for (const [route, kind] of [['conversations', 'conversation'], ['messages', 'message']]) {
    app.get(`/internal/v1/${route}`, asyncHandler(async (req, res) => {
      const uid = String(req.query.account_uid || '')
      await manager.readable(uid)
      const { cursor, limit } = pagination(req.query)
      const chat = kind === 'message' && req.query.chat_id ? hash(String(req.query.chat_id)) : null
      const data = manager.store.feed(uid, cursor, limit, kind, chat)
      res.json({ code: 200, data: { items: data.items.map(item => item.payload), next_cursor: data.next_cursor,
        has_more: data.has_more, account: manager.metadata(data.account) } })
    }))
  }
  app.use((err, req, res, next) => {
    const status = err.statusCode || (err.type === 'entity.too.large' ? 413 : 500)
    res.status(status).json({ code: status, message: err.code || (status === 413 ? 'request_size_limit' : 'connector_internal_error') })
  })
  return app
}
export async function main(env = process.env) {
  const { apiKey, host } = connectorConfig(env)
  if ((env.WHATSAPP_PROVIDER || 'baileys') !== 'baileys') throw error('unsupported_provider', 500)
  if (!env.ARK_API_BASE_URL) throw error('ARK_API_BASE_URL_required', 500)
  const agent = whatsappProxyAgent(env)
  const dispatcher = whatsappProxyDispatcher(env)
  const store = new Store(path.resolve(env.WHATSAPP_DATA_DIR || './data', 'connector.sqlite'), {
    encryptionKey: env.WHATSAPP_ENCRYPTION_KEY, keyVersion: env.WHATSAPP_KEY_VERSION || '1',
    maxBytes: Number(env.WHATSAPP_MAX_DISK_BYTES || 1024 ** 3), maxRows: Number(env.WHATSAPP_MAX_CHANGE_ROWS || 1000000),
  })
  const manager = new Manager(store, { authorize: backendAuthorizer(env.ARK_API_BASE_URL, apiKey), agent, dispatcher })
  const server = createApp(manager, apiKey).listen(Number(env.PORT || 8787), host, () => {
    console.log(`WhatsApp connector listening on ${host}:${env.PORT || 8787} (baileys, single host)`)
    if (env.WHATSAPP_RESTORE_ON_START !== 'false') void manager.restore()
  })
  const shutdown = () => {
    manager.shutdown(); agent?.destroy()
    if (dispatcher) void dispatcher.destroy().catch(() => console.warn('connector_proxy_shutdown_failed'))
    server.close(() => store.close())
  }
  process.once('SIGTERM', shutdown); process.once('SIGINT', shutdown)
  return { server, store, manager }
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  dotenv.config({ quiet: true })
  main().catch(err => { console.error(`connector_start_failed:${err.code || 'configuration_error'}`); process.exitCode = 1 })
}
