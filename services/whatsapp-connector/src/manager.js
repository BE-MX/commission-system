import { randomUUID } from 'node:crypto'
import makeWASocket, { BufferJSON, DisconnectReason } from 'baileys'
import pino from 'pino'
import qrcode from 'qrcode'
import { authState } from './auth-state.js'
import { error } from './crypto.js'
import { Projector, phone } from './projection.js'

const INGEST_EVENTS = ['messages.upsert', 'messages.update', 'messages.delete', 'messaging-history.set',
  'messaging-history.status', 'chats.upsert', 'chats.update', 'chats.delete', 'contacts.upsert', 'contacts.update']
const logger = pino({ level: 'silent' }) // Upstream debug records can contain keys/bodies/QR; never enable them here.

export function classifyDisconnect(code) {
  if (code === DisconnectReason.loggedOut) return 'reauth_required'
  if (code === DisconnectReason.connectionReplaced) return 'blocked'
  if (code === DisconnectReason.restartRequired) return 'restart'
  if ([DisconnectReason.connectionClosed, DisconnectReason.connectionLost, DisconnectReason.timedOut,
    DisconnectReason.unavailableService].includes(code)) return 'transient'
  return 'protected_pause'
}

export function backendAuthorizer(baseUrl, apiKey, fetcher = fetch) {
  const url = new URL(baseUrl)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw error('invalid_ark_api_base_url', 500)
  return async uid => {
    try {
      const response = await fetcher(`${url.href.replace(/\/$/, '')}/api/whatsapp/internal/accounts/${encodeURIComponent(uid)}/authorization`,
        { headers: { Authorization: `Bearer ${apiKey}` }, signal: AbortSignal.timeout(5000), redirect: 'error' })
      if (!response.ok) throw error('authorization_unavailable', 503)
      const result = await response.json()
      const auth = result.code === 200 ? result.data : null
      if (!auth?.allowed || auth.provider !== 'baileys' || !Number.isSafeInteger(auth.ark_user_id) || auth.ark_user_id < 1
        || !Number.isSafeInteger(auth.session_generation) || auth.session_generation < 1
        || !String(auth.consent_version || '')) throw error('authorization_denied', 403)
      return { ...auth, consent_version: String(auth.consent_version) }
    } catch (err) { throw error(err.code === 'authorization_denied' ? err.code : 'authorization_unavailable', err.code === 'authorization_denied' ? 403 : 503) }
  }
}

export class Manager {
  constructor(store, { authorize, socketFactory = makeWASocket, encodeQR = qrcode.toDataURL,
    authInterval = 10000, leaseTTL = 30000, maxQueueEvents = 64, maxQueueBytes = 16 * 1024 ** 2,
    maxEventBytes = 8 * 1024 ** 2, maxRetries = 5, retryBase = 1000, random = Math.random } = {}) {
    if (!authorize) throw error('authorizer_required', 500)
    if (authInterval > 15000 || authInterval < 20 || leaseTTL <= authInterval * 2) throw error('invalid_lease_interval', 500)
    Object.assign(this, { store, authorize, socketFactory, encodeQR, authInterval, leaseTTL,
      maxQueueEvents, maxQueueBytes, maxEventBytes, maxRetries, retryBase, random })
    this.projector = new Projector(store)
    this.entries = new Map()
    this.sessions = new Map()
    this.pending = new Map()
    this.holder = randomUUID()
    this.closed = false
    for (const account of store.accounts()) for (const session of store.entities(account.account_uid, 'bind')) {
      delete session.source_revision
      this.sessions.set(session.bind_session_uid, session)
    }
  }
  async authorized(uid, expected) {
    const auth = await this.authorize(uid)
    if (!auth?.allowed || auth.provider !== 'baileys' || !Number.isSafeInteger(auth.ark_user_id) || auth.ark_user_id < 1
      || !Number.isSafeInteger(auth.session_generation) || auth.session_generation < 1 || !String(auth.consent_version || '')) throw error('authorization_denied', 403)
    auth.consent_version = String(auth.consent_version)
    if (expected && (auth.ark_user_id !== expected.ark_user_id || auth.session_generation !== expected.session_generation
      || auth.consent_version !== String(expected.consent_version))) throw error('authorization_changed', 403)
    return auth
  }
  exclusive(uid, fn) {
    if (this.pending.has(uid)) throw error('account_operation_busy')
    const work = Promise.resolve().then(fn)
    this.pending.set(uid, work)
    return work.finally(() => this.pending.delete(uid))
  }
  async bind(request) {
    const uid = request.account_uid
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(uid || '') || !Number.isSafeInteger(request.ark_user_id) || request.ark_user_id < 1
      || request.provider !== 'baileys' || !String(request.consent_version || '')) throw error('invalid_bind_request', 400)
    const bindUid = request.bind_session_uid || `bind_${randomUUID()}`
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(bindUid)) throw error('invalid_bind_session_uid', 400)
    return this.exclusive(uid, async () => {
      const auth = await this.authorized(uid)
      if (auth.ark_user_id !== request.ark_user_id || auth.consent_version !== String(request.consent_version)) throw error('owner_or_consent_mismatch', 403)
      const existingSession = this.sessions.get(bindUid)
      if (existingSession) {
        if (existingSession.account_uid !== uid || existingSession.ark_user_id !== request.ark_user_id) throw error('bind_session_conflict')
        if (existingSession.session_generation !== auth.session_generation || existingSession.consent_version !== auth.consent_version) throw error('bind_session_expired')
        return this.session(bindUid)
      }
      this.stop(uid)
      this.store.configure(uid, auth)
      const session = { bind_session_uid: bindUid, account_uid: uid, ark_user_id: request.ark_user_id,
        session_generation: auth.session_generation, consent_version: auth.consent_version,
        status: 'pending', created_at: new Date().toISOString() }
      this.sessions.set(bindUid, session)
      try { await this.start(uid, { session, freshBind: true, auth }) }
      catch (err) { session.status = 'error'; throw err }
      return this.session(bindUid)
    })
  }
  session(bindUid) {
    const session = this.sessions.get(bindUid)
    if (!session) throw error('bind_session_not_found', 404)
    const entry = this.entries.get(session.account_uid)
    const account = this.store.account(session.account_uid)
    const current = session.session_generation === account?.session_generation && session.consent_version === account?.consent_version
    const qr = current && entry?.session?.bind_session_uid === bindUid && entry.qr && entry.qr.expires > Date.now() ? entry.qr : null
    return { ...session, status: !current ? 'expired' : account?.status === 'active' ? 'active' : session.status,
      qr_code_url: qr?.url || null, expires_at: qr ? new Date(qr.expires).toISOString() : null, account: this.metadata(account) }
  }
  metadata(account) {
    if (!account) throw error('account_not_found', 404)
    const safe = { ...account, connector_status: account.connection_state, last_error: account.last_error_code || null }
    delete safe.self_jid
    return safe
  }
  async readable(uid) {
    const account = this.store.account(uid)
    if (!account) throw error('account_not_found', 404)
    try { await this.authorized(uid, account) }
    catch (err) { this.protect(this.entries.get(uid), err.code); throw err }
    if (['paused', 'revoking', 'revoked'].includes(account.status)) throw error(account.status === 'revoked' ? 'revoked' : 'account_paused', 403)
    return account
  }
  async start(uid, { session = null, freshBind = false, auth = null } = {}) {
    if (this.closed) throw error('connector_stopping', 503)
    if (this.entries.has(uid)) return this.entries.get(uid)
    const account = this.store.account(uid)
    if (!account) throw error('account_not_found', 404)
    const allowed = auth || await this.authorized(uid, account)
    if (this.closed) throw error('connector_stopping', 503)
    if (allowed.session_generation !== account.session_generation || allowed.ark_user_id !== account.ark_user_id
      || String(allowed.consent_version) !== account.consent_version) throw error('authorization_changed', 403)
    const lease = this.store.acquire(uid, this.holder, this.leaseTTL)
    session ||= [...this.sessions.values()].filter(value => value.account_uid === uid && value.session_generation === account.session_generation
      && value.consent_version === account.consent_version).sort((a, b) => a.created_at.localeCompare(b.created_at)).at(-1) || null
    const entry = { uid, lease, session, stopped: false, collecting: true, queue: Promise.resolve(),
      queueCount: 0, queueBytes: 0, retries: 0, listeners: [], socket: null, qr: null, validating: false, epoch: 0 }
    this.entries.set(uid, entry)
    try {
      this.store.patchAccount(lease, { status: freshBind ? 'binding' : account.status,
        connection_state: 'connecting', sync_state: 'collecting', needs_user_action: false, last_error_code: null })
      if (session) this.store.transaction(() => {
        this.store.fence(lease)
        this.store.putEntity(lease, 'bind', session.bind_session_uid, session, {}, true)
      })
      entry.heartbeat = setInterval(() => { void this.checkAuthorization(entry) }, this.authInterval)
      await this.openSocket(entry)
      return entry
    } catch (err) { this.protect(entry, err.code || 'socket_start_failed'); throw err }
  }
  async openSocket(entry) {
    if (entry.opening || entry.stopped) return
    entry.opening = true
    try {
    await this.authorized(entry.uid, this.store.account(entry.uid)) // Recheck immediately before every socket construction.
    if (entry.stopped) return
    this.store.renew(entry.lease)
    const auth = authState(this.store, entry.lease, err => this.protect(entry, err.code || 'auth_store_failed'))
    entry.auth = auth.state
    const socket = this.socketFactory({ auth: auth.state, logger, markOnlineOnConnect: false, syncFullHistory: true,
      shouldSyncHistoryMessage: () => true, emitOwnEvents: true, fireInitQueries: true,
      getMessage: async () => undefined, connectTimeoutMs: 20000, defaultQueryTimeoutMs: 20000 })
    entry.socket = socket
    const epoch = ++entry.epoch
    const on = (name, handler) => { socket.ev.on(name, handler); entry.listeners.push([name, handler]) }
    on('creds.update', update => {
      if (entry.stopped) return
      try { auth.saveCreds(update) } catch (err) { this.protect(entry, err.code || 'auth_store_failed') }
    })
    on('connection.update', update => { void this.connection(entry, update, epoch).catch(err => this.protect(entry, err.code || 'connection_update_failed')) })
    for (const name of INGEST_EVENTS) on(name, value => this.enqueue(entry, name, value))
    } finally { entry.opening = false }
  }
  enqueue(entry, kind, value) {
    if (entry.stopped || !entry.collecting) return
    let bytes
    try { bytes = Buffer.byteLength(JSON.stringify(value, BufferJSON.replacer)) }
    catch { this.protect(entry, 'invalid_event'); return }
    if (bytes > this.maxEventBytes || entry.queueCount >= this.maxQueueEvents || entry.queueBytes + bytes > this.maxQueueBytes) {
      this.protect(entry, 'backpressure_gap'); return
    }
    entry.queueCount++; entry.queueBytes += bytes
    entry.queue = entry.queue.then(() => {
      if (!entry.stopped && entry.collecting) this.projector.ingest(entry.lease, kind, value, randomUUID(), bytes)
    }).catch(err => this.protect(entry, err.code || 'event_store_failed')).finally(() => { entry.queueCount--; entry.queueBytes -= bytes })
  }
  async checkAuthorization(entry) {
    if (entry.stopped || entry.validating) return
    entry.validating = true
    try {
      await this.authorized(entry.uid, this.store.account(entry.uid))
      if (!entry.stopped) this.store.renew(entry.lease)
    } catch (err) { this.protect(entry, err.code || 'authorization_unavailable') }
    finally { entry.validating = false }
  }
  async connection(entry, update, epoch = entry.epoch) {
    if (entry.stopped || epoch !== entry.epoch) return
    this.store.fence(entry.lease)
    if (update.qr) {
      const qrUrl = await this.encodeQR(update.qr)
      if (entry.stopped || epoch !== entry.epoch) return
      entry.qr = { url: qrUrl, expires: Date.now() + 60000 }
      clearTimeout(entry.qrTimer)
      entry.qrTimer = setTimeout(() => { entry.qr = null }, 60000)
      this.store.patchAccount(entry.lease, { status: 'binding', connection_state: 'qr_ready', needs_user_action: true })
    }
    if (update.connection === 'open') {
      this.clearQR(entry)
      const me = entry.socket.user || {}
      this.store.patchAccount(entry.lease, { status: 'active', connection_state: 'connected', sync_state: 'collecting',
        needs_user_action: false, last_error_code: null, self_jid: me.id || null,
        phone_number: phone(me.id), display_name: me.name || null })
      if (entry.session) entry.session.status = 'active'
    }
    if (update.connection !== 'close') return
    const code = update.lastDisconnect?.error?.output?.statusCode || update.lastDisconnect?.error?.statusCode
    const classification = classifyDisconnect(code)
    this.detachSocket(entry)
    this.clearQR(entry)
    if (['reauth_required', 'blocked', 'protected_pause'].includes(classification)) {
      if (classification === 'reauth_required') this.store.clearAuth(entry.lease)
      this.protect(entry, classification, classification === 'reauth_required' ? 'reconnect_required' : 'paused')
      return
    }
    if (++entry.retries > this.maxRetries) { this.protect(entry, 'reconnect_exhausted', 'reconnect_required'); return }
    this.store.patchAccount(entry.lease, { connection_state: 'reconnecting', sync_state: 'idle', last_error_code: classification })
    const delay = classification === 'restart' ? 100 : Math.min(30000, this.retryBase * 2 ** (entry.retries - 1)) * (0.75 + this.random() * 0.5)
    entry.retryTimer = setTimeout(() => {
      if (!entry.stopped) void this.openSocket(entry).catch(err => this.protect(entry, err.code || 'socket_start_failed'))
    }, delay)
  }
  clearQR(entry) { entry.qr = null; clearTimeout(entry.qrTimer) }
  detachSocket(entry, close = true) {
    const socket = entry.socket
    if (!socket) return
    entry.epoch++
    for (const [name, handler] of entry.listeners) socket.ev.off(name, handler)
    entry.listeners = []
    if (close) { try { socket.end(new Error('connector_controlled_close')) } catch { console.warn('connector_socket_close_failed') } }
    entry.socket = null
  }
  stop(uid, { preserveSocket = false } = {}) {
    const entry = this.entries.get(uid)
    if (!entry) return null
    entry.collecting = false; entry.stopped = true
    clearInterval(entry.heartbeat); clearTimeout(entry.retryTimer); this.clearQR(entry)
    this.detachSocket(entry, !preserveSocket)
    this.entries.delete(uid)
    if (!preserveSocket) this.store.release(entry.lease)
    return entry
  }
  protect(entry, code, status = 'paused') {
    if (!entry || entry.stopped) return
    try {
      const account = this.store.fence(entry.lease)
      this.store.patchAccount(entry.lease, { status, connection_state: code === 'reauth_required' ? 'reauth_required' : 'protected_pause',
        sync_state: 'paused', last_error_code: code, needs_user_action: true,
        coverage: { ...account.coverage, gap_reason: code } })
    } catch (err) { console.warn(`connector_protection_failed:${err.code || 'store_error'}`) }
    this.stop(entry.uid)
  }
  protectOffline(uid, code) {
    if (!this.store.account(uid)) return
    let lease
    try {
      lease = this.store.acquire(uid, this.holder, this.leaseTTL)
      const account = this.store.account(uid)
      this.store.patchAccount(lease, { status: 'paused', connection_state: 'protected_pause', sync_state: 'paused',
        last_error_code: code, needs_user_action: true, coverage: { ...account.coverage, gap_reason: code } })
    } catch (err) { console.warn(`connector_offline_protection_failed:${err.code || 'store_error'}`) }
    finally { if (lease) this.store.release(lease) }
  }
  async pause(uid) {
    return this.exclusive(uid, async () => {
      const entry = this.entries.get(uid)
      if (entry) this.protect(entry, 'collection_paused')
      else {
        const lease = this.store.acquire(uid, this.holder, this.leaseTTL)
        try { this.store.patchAccount(lease, { status: 'paused', sync_state: 'paused', connection_state: 'paused', last_error_code: 'collection_paused' }) }
        finally { this.store.release(lease) }
      }
      return this.metadata(this.store.account(uid))
    })
  }
  async reauthorize(uid) {
    return this.exclusive(uid, async () => {
      this.stop(uid)
      let auth
      try { auth = await this.authorized(uid) }
      catch (err) { this.protectOffline(uid, err.code || 'authorization_unavailable'); throw err }
      this.store.configure(uid, auth)
      const lease = this.store.acquire(uid, this.holder, this.leaseTTL)
      try {
        const credentials = this.store.authGet(lease, 'creds', ['current']).current?.value
        if (!credentials?.registered) {
          this.store.patchAccount(lease, { status: 'reconnect_required', connection_state: 'reauth_required',
            sync_state: 'paused', needs_user_action: true, last_error_code: 'rebind_required' })
          return this.metadata(this.store.account(uid))
        }
        this.store.patchAccount(lease, { status: 'active', connection_state: 'reconnecting', sync_state: 'idle',
          needs_user_action: false, last_error_code: null })
        this.store.republish(lease)
      } catch (err) {
        const account = this.store.account(uid)
        this.store.patchAccount(lease, { status: 'paused', connection_state: 'protected_pause', sync_state: 'paused',
          last_error_code: err.code || 'reauthorize_failed', needs_user_action: true,
          coverage: { ...account.coverage, gap_reason: err.code || 'reauthorize_failed' } })
        throw err
      } finally { this.store.release(lease) }
      await this.start(uid, { auth })
      return this.metadata(this.store.account(uid))
    })
  }
  async revoke(uid) {
    return this.exclusive(uid, async () => {
      const current = this.store.account(uid)
      if (!current) throw error('account_not_found', 404)
      if (current.status === 'revoked') return this.metadata(current)
      const entry = this.entries.get(uid)
      const socket = entry?.socket
      const lease = entry?.lease || this.store.acquire(uid, this.holder, this.leaseTTL)
      // Stop business collection and auth polling before controlled linked-device logout.
      if (entry) this.stop(uid, { preserveSocket: true })
      let logoutState = 'not_attempted_offline'
      try {
        this.store.patchAccount(lease, { status: 'revoking', sync_state: 'paused', connection_state: 'revoking', revoke_state: 'pending' })
        if (socket) {
          let timeout
          const hasIdentity = Boolean(socket.authState?.creds?.me?.id || entry?.auth?.creds?.me?.id)
          try {
            await Promise.race([socket.logout(), new Promise((resolve, reject) => {
              timeout = setTimeout(() => reject(error('logout_timeout')), 10000)
            })]); logoutState = hasIdentity ? 'request_sent' : 'not_sent_no_identity'
          } catch { logoutState = 'request_uncertain' }
          finally { clearTimeout(timeout); try { socket.end(new Error('connector_revoked')) } catch { console.warn('connector_socket_close_failed') } }
        }
        this.store.clearAuth(lease)
        // rc14 logout() resolves after a socket write; it has no peer ACK and may send nothing without me.id.
        this.store.patchAccount(lease, { status: 'paused', connection_state: 'logout_unconfirmed',
          revoke_state: 'remote_unconfirmed', logout_state: logoutState, local_credentials_cleared: true,
          last_error_code: 'remote_logout_unconfirmed', needs_user_action: true })
        return this.metadata(this.store.account(uid))
      } finally { this.store.release(lease) }
    })
  }
  async restore() {
    for (const account of this.store.accounts()) {
      if (!['active', 'binding'].includes(account.status)) continue
      try {
        const entry = await this.start(account.account_uid)
        this.store.patchAccount(entry.lease, { coverage: { ...account.coverage,
          gap_reason: account.coverage?.gap_reason || 'connector_restart_gap' } })
      }
      catch (err) {
        if (err.code !== 'lease_busy') this.protectOffline(account.account_uid, err.code || 'start_failed')
        console.warn(`connector_restore_failed:${err.code || 'start_failed'}`)
      }
    }
  }
  shutdown() { this.closed = true; for (const uid of [...this.entries.keys()]) this.stop(uid) }
}
