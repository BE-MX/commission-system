import 'dotenv/config'

import fs from 'node:fs'
import path from 'node:path'
import cors from 'cors'
import express from 'express'
import qrcode from 'qrcode'
import { v4 as uuidv4 } from 'uuid'
import whatsapp from 'whatsapp-web.js'

const { Client, LocalAuth } = whatsapp

const PORT = Number(process.env.PORT || 8787)
const API_KEY = process.env.WHATSAPP_CONNECTOR_API_KEY || ''
const DATA_DIR = process.env.WHATSAPP_DATA_DIR || './data'
const HEADLESS = (process.env.WHATSAPP_HEADLESS || 'true') !== 'false'
const RESTORE_ON_START = (process.env.WHATSAPP_RESTORE_ON_START || 'true') !== 'false'
const PUPPETEER_EXECUTABLE_PATH = process.env.WHATSAPP_PUPPETEER_EXECUTABLE_PATH || ''
const STATE_FILE = path.join(DATA_DIR, 'state.json')

fs.mkdirSync(DATA_DIR, { recursive: true })

const clients = new Map()
const state = loadState()

const app = express()
app.use(cors())
app.use(express.json({ limit: '1mb' }))
app.use(authenticate)

app.get('/health', (req, res) => {
  res.json({ status: 'ok' })
})

app.post('/internal/v1/bind-sessions', asyncHandler(async (req, res) => {
  const arkUserId = Number(req.body?.ark_user_id)
  if (!arkUserId) {
    return res.status(400).json({ code: 400, message: 'ark_user_id is required' })
  }

  const reusableSession = findReusableBindSession(arkUserId)
  if (reusableSession) {
    return res.json({ code: 200, data: reusableSession })
  }

  await closePendingClientsForUser(arkUserId)

  const bindSessionUid = `bind_${uuidv4()}`
  const accountUid = `wa_acc_${uuidv4()}`
  const now = new Date().toISOString()

  state.bindSessions[bindSessionUid] = {
    bind_session_uid: bindSessionUid,
    account_uid: accountUid,
    ark_user_id: arkUserId,
    status: 'pending',
    qr_code_url: null,
    expires_at: null,
    created_at: now,
    updated_at: now,
  }
  state.accounts[accountUid] = {
    account_uid: accountUid,
    ark_user_id: arkUserId,
    phone_number: null,
    display_name: null,
    status: 'binding',
    connector_status: 'initializing',
    last_sync_at: null,
    last_message_at: null,
    last_error: null,
  }
  saveState()

  startClient({ bindSessionUid, accountUid, arkUserId })
  res.json({ code: 200, data: state.bindSessions[bindSessionUid] })
}))

app.get('/internal/v1/bind-sessions/:bindSessionUid', (req, res) => {
  const session = state.bindSessions[req.params.bindSessionUid]
  if (!session) {
    return res.status(404).json({ code: 404, message: 'bind session not found' })
  }
  res.json({ code: 200, data: { ...session, account: state.accounts[session.account_uid] || null } })
})

app.post('/internal/v1/accounts/:accountUid/revoke', asyncHandler(async (req, res) => {
  const account = state.accounts[req.params.accountUid]
  if (!account) {
    return res.status(404).json({ code: 404, message: 'account not found' })
  }

  const client = clients.get(account.account_uid)
  if (client) {
    await client.destroy()
    clients.delete(account.account_uid)
  }

  account.status = 'revoked'
  account.connector_status = 'revoked'
  account.updated_at = new Date().toISOString()
  saveState()
  res.json({ code: 200, data: account })
}))

app.get('/internal/v1/conversations', asyncHandler(async (req, res) => {
  const accountUid = String(req.query.account_uid || '')
  const limit = clampLimit(req.query.limit, 100)
  const account = requireAccount(accountUid)
  const client = requireClient(accountUid)
  const chats = await client.getChats()

  const items = []
  for (const chat of chats.slice(0, limit)) {
    items.push(await mapConversation(chat, accountUid))
  }

  account.last_sync_at = new Date().toISOString()
  saveState()
  res.json({ code: 200, data: { items, next_cursor: String(Date.now()) } })
}))

app.get('/internal/v1/messages', asyncHandler(async (req, res) => {
  const accountUid = String(req.query.account_uid || '')
  const cursor = Number(req.query.cursor || 0)
  const chatId = String(req.query.chat_id || '')
  const limit = clampLimit(req.query.limit, 100)
  const account = requireAccount(accountUid)
  const client = requireClient(accountUid)
  const chats = chatId ? [await resolveChatById(client, chatId)] : await client.getChats()
  const items = []
  let maxTimestamp = cursor

  for (const chat of chats) {
    if (items.length >= limit) break
    const messages = await chat.fetchMessages({ limit: Math.min(limit, 100) })
    for (const message of messages) {
      const messageTime = Number(message.timestamp || 0) * 1000
      if (cursor && messageTime <= cursor) continue
      if (items.length >= limit) break
      maxTimestamp = Math.max(maxTimestamp, messageTime)
      items.push(await mapMessage(client, account, accountUid, chat, message))
    }
  }

  account.last_sync_at = new Date().toISOString()
  if (maxTimestamp) account.last_message_at = new Date(maxTimestamp).toISOString()
  saveState()
  res.json({ code: 200, data: { items, next_cursor: maxTimestamp ? String(maxTimestamp) : null } })
}))

app.use((err, req, res, next) => {
  const status = err.statusCode || 500
  res.status(status).json({ code: status, message: err.message || 'internal error' })
})

app.listen(PORT, () => {
  console.log(`WhatsApp Connector listening on ${PORT}`)
  restoreActiveClients()
})

function authenticate(req, res, next) {
  if (!API_KEY) return next()
  const header = req.headers.authorization || ''
  if (header !== `Bearer ${API_KEY}`) {
    return res.status(401).json({ code: 401, message: 'unauthorized' })
  }
  next()
}

function asyncHandler(fn) {
  return (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next)
}

function startClient({ bindSessionUid = null, accountUid, arkUserId, restore = false }) {
  if (clients.has(accountUid)) return

  const client = new Client({
    authStrategy: new LocalAuth({ clientId: accountUid }),
    puppeteer: {
      headless: HEADLESS,
      executablePath: PUPPETEER_EXECUTABLE_PATH || undefined,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    },
  })
  clients.set(accountUid, client)
  const account = state.accounts[accountUid]
  if (restore && account) {
    account.connector_status = 'restoring'
    account.updated_at = new Date().toISOString()
    saveState()
  }

  let reconnectRequired = false

  client.on('qr', async qr => {
    if (restore) {
      reconnectRequired = true
      markReconnectRequired(accountUid, 'stored WhatsApp session expired; create a new bind session')
      await client.destroy().catch(() => {})
      clients.delete(accountUid)
      return
    }
    const session = state.bindSessions[bindSessionUid]
    if (!session) return
    session.qr_code_url = await qrcode.toDataURL(qr)
    session.status = 'pending'
    session.expires_at = new Date(Date.now() + 60_000).toISOString()
    session.updated_at = new Date().toISOString()
    const account = state.accounts[accountUid]
    if (account) {
      account.status = 'binding'
      account.connector_status = 'qr_ready'
    }
    saveState()
  })

  client.on('ready', () => {
    const session = bindSessionUid ? state.bindSessions[bindSessionUid] : findLatestBindSessionForAccount(accountUid)
    const account = state.accounts[accountUid]
    const info = client.info || {}
    const wid = info.wid?.user || null
    if (session) {
      session.status = 'active'
      session.updated_at = new Date().toISOString()
    }
    if (account) {
      account.ark_user_id = arkUserId
      account.phone_number = wid
      account.display_name = info.pushname || info.platform || wid
      account.status = 'active'
      account.connector_status = 'connected'
      account.last_error = null
      account.updated_at = new Date().toISOString()
    }
    saveState()
  })

  client.on('auth_failure', message => {
    if (restore) {
      reconnectRequired = true
      markReconnectRequired(accountUid, `auth_failure: ${message}`)
      clients.delete(accountUid)
      return
    }
    markClientError(bindSessionUid, accountUid, `auth_failure: ${message}`)
  })

  client.on('disconnected', reason => {
    if (reconnectRequired) return
    markClientError(bindSessionUid, accountUid, `disconnected: ${reason}`)
    clients.delete(accountUid)
  })

  client.initialize().catch(error => {
    if (restore) {
      markReconnectRequired(accountUid, error.message)
      clients.delete(accountUid)
      return
    }
    markClientError(bindSessionUid, accountUid, error.message)
    clients.delete(accountUid)
  })
}

function restoreActiveClients() {
  if (!RESTORE_ON_START) {
    console.log('WhatsApp Connector restore disabled')
    return
  }
  const accounts = Object.values(state.accounts).filter(account => account.status === 'active')
  for (const account of accounts) {
    startClient({
      bindSessionUid: findLatestBindSessionForAccount(account.account_uid)?.bind_session_uid || null,
      accountUid: account.account_uid,
      arkUserId: Number(account.ark_user_id),
      restore: true,
    })
  }
  console.log(`WhatsApp Connector restore queued ${accounts.length} active account(s)`)
}

function findReusableBindSession(arkUserId) {
  const now = Date.now()
  return Object.values(state.bindSessions)
    .filter(session => {
      if (Number(session.ark_user_id) !== arkUserId) return false
      if (!['pending', 'binding'].includes(session.status)) return false
      if (!clients.has(session.account_uid)) return false
      if (!session.qr_code_url) return false
      if (!session.expires_at) return true
      return new Date(session.expires_at).getTime() > now
    })
    .sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0))[0] || null
}

function findLatestBindSessionForAccount(accountUid) {
  return Object.values(state.bindSessions)
    .filter(session => session.account_uid === accountUid)
    .sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0))[0] || null
}

async function closePendingClientsForUser(arkUserId) {
  const pending = Object.values(state.bindSessions).filter(session => {
    if (Number(session.ark_user_id) !== arkUserId) return false
    return ['pending', 'binding'].includes(session.status)
  })
  for (const session of pending) {
    session.status = 'expired'
    session.updated_at = new Date().toISOString()
    const account = state.accounts[session.account_uid]
    if (account && account.status !== 'active') {
      account.status = 'expired'
      account.connector_status = 'expired'
      account.updated_at = new Date().toISOString()
    }
    const client = clients.get(session.account_uid)
    if (client) {
      await client.destroy().catch(() => {})
      clients.delete(session.account_uid)
    }
  }
  if (pending.length) saveState()
}

function markClientError(bindSessionUid, accountUid, message) {
  const session = state.bindSessions[bindSessionUid]
  const account = state.accounts[accountUid]
  if (session) {
    session.status = 'error'
    session.updated_at = new Date().toISOString()
  }
  if (account) {
    account.status = 'error'
    account.connector_status = 'error'
    account.last_error = message
    account.updated_at = new Date().toISOString()
  }
  saveState()
}

function markReconnectRequired(accountUid, message) {
  const account = state.accounts[accountUid]
  const session = findLatestBindSessionForAccount(accountUid)
  if (session && session.status === 'active') {
    session.status = 'reconnect_required'
    session.updated_at = new Date().toISOString()
  }
  if (account) {
    account.status = 'reconnect_required'
    account.connector_status = 'qr_required'
    account.last_error = message
    account.updated_at = new Date().toISOString()
  }
  saveState()
}

function requireAccount(accountUid) {
  const account = state.accounts[accountUid]
  if (!account) {
    const error = new Error('account not found')
    error.statusCode = 404
    throw error
  }
  if (account.status !== 'active') {
    const error = new Error('account is not active')
    error.statusCode = 409
    throw error
  }
  return account
}

function requireClient(accountUid) {
  const client = clients.get(accountUid)
  if (!client) {
    const error = new Error('client is not loaded; create a new bind session')
    error.statusCode = 409
    throw error
  }
  return client
}

async function mapConversation(chat, accountUid) {
  const contactProfile = await resolveChatContactProfile(chat)
  return {
    conversation_uid: `${accountUid}:${chat.id._serialized}`,
    chat_id: chat.id._serialized,
    contact_phone: contactProfile.phone || normalizeContactPhone(chat.id._serialized),
    contact_name: contactProfile.name || chat.name || chat.formattedTitle || null,
    is_group: Boolean(chat.isGroup),
    last_message_at: chat.timestamp ? new Date(chat.timestamp * 1000).toISOString() : null,
    last_message_preview: chat.lastMessage?.body || '',
  }
}

async function mapMessage(client, account, accountUid, chat, message) {
  const messageId = message.id?._serialized || message.id?.id || `${chat.id._serialized}_${message.timestamp}`
  const sentAt = message.timestamp ? new Date(message.timestamp * 1000).toISOString() : null
  const body = message.body || ''
  const senderWaId = resolveSenderWaId(client, message)
  const senderProfile = message.fromMe
    ? {
        wa_id: senderWaId,
        phone: account.phone_number,
        name: account.display_name || account.phone_number,
      }
    : await resolveContactProfile(client, senderWaId)

  return {
    message_uid: `${accountUid}:${messageId}`,
    conversation_uid: `${accountUid}:${chat.id._serialized}`,
    external_message_id: messageId,
    direction: message.fromMe ? 'outbound' : 'inbound',
    sender_wa_id: senderProfile.wa_id || senderWaId,
    sender_phone: senderProfile.phone || normalizeContactPhone(senderWaId),
    sender_name: senderProfile.name,
    content_type: message.type || 'text',
    content_text: body,
    content_preview: body.slice(0, 500),
    sent_at: sentAt,
    attachments: message.hasMedia ? [{ mime_type: message.type || null }] : [],
  }
}

function resolveSenderWaId(client, message) {
  if (message.fromMe) {
    return client.info?.wid?._serialized || client.info?.wid?.user || message.author || message.from || ''
  }
  return message.author || message.from || ''
}

async function resolveChatContactProfile(chat) {
  try {
    if (typeof chat.getContact !== 'function') return {}
    const contact = await chat.getContact()
    return contactToProfile(contact)
  } catch {
    return {}
  }
}

async function resolveContactProfile(client, contactId) {
  if (!contactId) return {}
  try {
    const contact = await client.getContactById(contactId)
    return contactToProfile(contact)
  } catch {
    return {
      wa_id: contactId,
      phone: normalizeContactPhone(contactId),
      name: null,
    }
  }
}

async function resolveChatById(client, chatId) {
  if (typeof client.getChatById === 'function') {
    try {
      const chat = await client.getChatById(chatId)
      if (chat) return chat
    } catch {
      // Fall back to getChats because whatsapp-web.js versions differ here.
    }
  }

  const chats = await client.getChats()
  const chat = chats.find(item => item.id?._serialized === chatId)
  if (!chat) {
    const error = new Error('chat not found')
    error.statusCode = 404
    throw error
  }
  return chat
}

function contactToProfile(contact) {
  if (!contact) return {}
  const waId = contact.id?._serialized || contact.id?.user || null
  return {
    wa_id: waId,
    phone: normalizeContactPhone(waId || contact.number || ''),
    name: contact.pushname || contact.name || contact.shortName || contact.verifiedName || null,
  }
}

function normalizeContactPhone(value) {
  return String(value || '').replace(/@c\.us$|@g\.us$/, '') || null
}

function clampLimit(value, fallback) {
  const num = Number(value || fallback)
  if (!Number.isFinite(num)) return fallback
  return Math.max(1, Math.min(num, 500))
}

function loadState() {
  if (!fs.existsSync(STATE_FILE)) {
    return { bindSessions: {}, accounts: {} }
  }
  try {
    const raw = fs.readFileSync(STATE_FILE, 'utf8')
    return JSON.parse(raw)
  } catch {
    return { bindSessions: {}, accounts: {} }
  }
}

function saveState() {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), 'utf8')
}
