import { DatabaseSync } from 'node:sqlite'
import { mkdirSync, statSync } from 'node:fs'
import { dirname } from 'node:path'
import { randomUUID } from 'node:crypto'
import { Cipher, error } from './crypto.js'

// SQLite engine UTC clock is used only for the cross-process lease protocol.
const CLOCK = "CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER)"
export class Store {
  constructor(filename, { encryptionKey, keyVersion = '1', maxBytes = 1024 ** 3, maxRows = 1000000 } = {}) {
    this.cipher = new Cipher(encryptionKey, keyVersion)
    this.filename = filename
    this.maxBytes = maxBytes
    this.maxRows = maxRows
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1024 || !Number.isSafeInteger(maxRows) || maxRows < 1) throw error('invalid_capacity_config', 500)
    mkdirSync(dirname(filename), { recursive: true, mode: 0o700 })
    this.db = new DatabaseSync(filename)
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;
      PRAGMA secure_delete=ON; PRAGMA cache_spill=OFF;
      CREATE TABLE IF NOT EXISTS accounts(uid TEXT PRIMARY KEY, owner INTEGER NOT NULL,
        generation INTEGER NOT NULL, consent TEXT NOT NULL, data TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS leases(uid TEXT PRIMARY KEY, holder TEXT NOT NULL,
        token INTEGER NOT NULL, expires INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS auth(uid TEXT NOT NULL, category TEXT NOT NULL, id TEXT NOT NULL,
        revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(uid,category,id));
      CREATE TABLE IF NOT EXISTS entities(uid TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
        chat TEXT, external_id TEXT, from_me INTEGER, participant TEXT, tombstone INTEGER NOT NULL DEFAULT 0,
        sequence INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL, PRIMARY KEY(uid,kind,id));
      CREATE INDEX IF NOT EXISTS entity_messages ON entities(uid,kind,chat,external_id,from_me);
      CREATE TABLE IF NOT EXISTS changes(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT NOT NULL, generation INTEGER NOT NULL, consent TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS changes_feed ON changes(uid,generation,sequence);
      CREATE TABLE IF NOT EXISTS inbox(event_id TEXT PRIMARY KEY, uid TEXT NOT NULL,
        generation INTEGER NOT NULL, event_kind TEXT NOT NULL, processed INTEGER NOT NULL);`)
  }
  close() { this.db.close() }
  transaction(fn) {
    this.db.exec('BEGIN IMMEDIATE')
    try { const result = fn(); this.db.exec('COMMIT'); return result }
    catch (err) { this.db.exec('ROLLBACK'); throw err }
  }
  account(uid) {
    const row = this.db.prepare('SELECT * FROM accounts WHERE uid=?').get(uid)
    return row ? this.cipher.open(row.data, 'data', `account:${uid}`) : null
  }
  accounts() { return this.db.prepare('SELECT uid FROM accounts').all().map(row => this.account(row.uid)) }
  configure(uid, authorization) {
    return this.transaction(() => {
      const current = this.account(uid)
      if (current && current.ark_user_id !== authorization.ark_user_id) throw error('owner_mismatch', 403)
      if (current && authorization.session_generation < current.session_generation) throw error('stale_generation')
      const held = this.db.prepare(`SELECT * FROM leases WHERE uid=? AND expires>${CLOCK}`).get(uid)
      if (held && (current?.session_generation !== authorization.session_generation || current?.consent_version !== String(authorization.consent_version))) throw error('lease_busy')
      const changed = current && current.session_generation !== authorization.session_generation
      const account = { ...current, account_uid: uid, ark_user_id: authorization.ark_user_id,
        consent_version: authorization.consent_version, session_generation: authorization.session_generation,
        provider: 'baileys', crm_shared: Boolean(authorization.crm_shared), status: changed || !current ? 'binding' : current.status,
        connection_state: changed || !current ? 'initializing' : current.connection_state,
        sync_state: changed || !current ? 'idle' : current.sync_state,
        history_state: current?.history_state || 'not_started', needs_user_action: false,
        revoke_state: changed || !current ? 'none' : current.revoke_state,
        last_error_code: null, coverage: current?.coverage || { earliest_message_at: null,
          latest_message_at: null, last_ingest_at: null, gap_reason: null } }
      this.writeAccount(account)
      return account
    })
  }
  writeAccount(account) {
    this.db.prepare(`INSERT INTO accounts(uid,owner,generation,consent,data) VALUES(?,?,?,?,?)
      ON CONFLICT(uid) DO UPDATE SET generation=excluded.generation,consent=excluded.consent,data=excluded.data`)
      .run(account.account_uid, account.ark_user_id, account.session_generation, account.consent_version,
        this.cipher.seal(account, 'data', `account:${account.account_uid}`))
  }
  acquire(uid, holder = randomUUID(), ttl = 30000) {
    return this.transaction(() => {
      const account = this.account(uid)
      if (!account) throw error('account_not_found', 404)
      const previous = this.db.prepare('SELECT * FROM leases WHERE uid=?').get(uid)
      const now = this.db.prepare(`SELECT ${CLOCK} AS now`).get().now
      if (previous && previous.expires > now) throw error('lease_busy')
      const token = (previous?.token || 0) + 1
      this.db.prepare(`INSERT INTO leases VALUES(?,?,?,?) ON CONFLICT(uid) DO UPDATE SET
        holder=excluded.holder,token=excluded.token,expires=excluded.expires`).run(uid, holder, token, now + ttl)
      const lease = { uid, holder, token, generation: account.session_generation, consent: account.consent_version, ttl }
      if (previous?.expires > 0) {
        this.writeAccount({ ...account, coverage: { ...account.coverage, gap_reason: 'lease_takeover_gap' } })
        this.change(lease, 'account', uid)
      }
      return lease
    })
  }
  fence(lease, { collection = false } = {}) {
    const row = this.db.prepare(`SELECT * FROM leases WHERE uid=? AND holder=? AND token=? AND expires>${CLOCK}`)
      .get(lease.uid, lease.holder, lease.token)
    if (!row) throw error('stale_lease')
    const account = this.account(lease.uid)
    if (account?.session_generation !== lease.generation) throw error('stale_generation')
    if (account.consent_version !== lease.consent) throw error('stale_consent')
    if (collection && ['paused', 'revoking', 'revoked'].includes(account.status)) throw error('account_paused')
    return account
  }
  renew(lease) {
    return this.transaction(() => {
      this.fence(lease)
      this.db.prepare(`UPDATE leases SET expires=${CLOCK}+? WHERE uid=? AND holder=? AND token=?`)
        .run(lease.ttl, lease.uid, lease.holder, lease.token)
    })
  }
  release(lease) {
    this.db.prepare('UPDATE leases SET expires=0 WHERE uid=? AND holder=? AND token=?')
      .run(lease.uid, lease.holder, lease.token)
  }
  patchAccount(lease, patch) {
    return this.transaction(() => {
      const current = this.fence(lease)
      const account = { ...current, ...patch }
      // Identity and authority are never writable through event data.
      Object.assign(account, { account_uid: current.account_uid, ark_user_id: current.ark_user_id,
        session_generation: current.session_generation, consent_version: current.consent_version })
      this.writeAccount(account)
      this.change(lease, 'account', lease.uid)
      this.fence(lease)
      return account
    })
  }
  authGet(lease, category, ids) {
    this.fence(lease)
    return Object.fromEntries(ids.map(id => {
      const row = this.db.prepare('SELECT * FROM auth WHERE uid=? AND category=? AND id=?').get(lease.uid, category, id)
      return [id, row ? { value: this.cipher.open(row.data, 'auth', `${lease.uid}:${category}:${id}`), revision: row.revision } : null]
    }))
  }
  authSet(lease, updates, expected = {}) {
    this.capacity(Buffer.byteLength(JSON.stringify(updates)))
    return this.transaction(() => {
      this.fence(lease)
      const revisions = {}
      for (const [category, entries] of Object.entries(updates)) for (const [id, value] of Object.entries(entries)) {
        const row = this.db.prepare('SELECT revision FROM auth WHERE uid=? AND category=? AND id=?').get(lease.uid, category, id)
        const revision = row?.revision || 0
        const key = `${category}:${id}`
        if (expected[key] !== undefined && expected[key] !== revision) throw error('auth_cas_conflict')
        this.db.prepare(`INSERT INTO auth VALUES(?,?,?,?,?) ON CONFLICT(uid,category,id)
          DO UPDATE SET revision=excluded.revision,data=excluded.data`).run(lease.uid, category, id, revision + 1,
          this.cipher.seal(value, 'auth', `${lease.uid}:${category}:${id}`))
        revisions[key] = revision + 1
      }
      this.fence(lease)
      this.capacity(0, true)
      return revisions
    })
  }
  clearAuth(lease) { this.transaction(() => { this.fence(lease); this.db.prepare('DELETE FROM auth WHERE uid=?').run(lease.uid) }) }
  republish(lease) {
    this.transaction(() => {
      this.fence(lease)
      for (const kind of ['conversation', 'message']) for (const value of this.iterEntities(lease.uid, kind)) {
        const id = kind === 'message' ? value.message_uid : value.conversation_uid
        const row = this.db.prepare('SELECT * FROM entities WHERE uid=? AND kind=? AND id=?').get(lease.uid, kind, id)
        delete value.source_revision
        delete value.session_generation
        delete value.consent_version
        this.putEntity(lease, row.kind, row.id, value, { chat: row.chat, externalId: row.external_id,
          fromMe: row.from_me === null ? undefined : Boolean(row.from_me), participant: row.participant })
      }
      this.fence(lease)
      this.capacity(0, true)
    })
  }
  capacity(extraBytes = 0, committing = false) {
    let bytes = 0
    let databaseBytes = 0
    for (const suffix of ['', '-wal']) {
      try {
        const size = statSync(`${this.filename}${suffix}`).size
        bytes += size
        if (!suffix) databaseBytes = size
      } catch (err) { if (err.code !== 'ENOENT') throw err }
    }
    // Uncommitted pages do not appear in stat(DB/WAL). Reserve a worst-case WAL frame for every
    // logical SQLite page before COMMIT; disabling cache_spill keeps an aborted batch off disk.
    const pages = committing ? this.db.prepare('PRAGMA page_count').get().page_count : 0
    const pageSize = committing ? this.db.prepare('PRAGMA page_size').get().page_size : 0
    const checkpointGrowth = Math.max(0, pages * pageSize - databaseBytes)
    if (bytes + extraBytes * 4 + pages * (pageSize + 24) + checkpointGrowth + (committing ? 32 : 0) > this.maxBytes) throw error('disk_capacity')
    if (this.db.prepare(`SELECT (SELECT COUNT(*) FROM changes) + (SELECT COUNT(*) FROM inbox)
      + (SELECT COUNT(*) FROM entities) + (SELECT COUNT(*) FROM auth) AS count`).get().count >= this.maxRows) throw error('retention_capacity')
  }
  ingest(lease, eventKind, project, eventId = randomUUID(), bytes = 0) {
    this.capacity(bytes)
    return this.transaction(() => {
      this.fence(lease, { collection: true })
      const inserted = this.db.prepare('INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,0)').run(eventId, lease.uid, lease.generation, eventKind)
      if (!inserted.changes) return false
      project()
      this.fence(lease, { collection: true })
      this.capacity(0, true)
      this.db.prepare('UPDATE inbox SET processed=1 WHERE event_id=?').run(eventId)
      return true
    })
  }
  entity(uid, kind, id) {
    const row = this.db.prepare('SELECT * FROM entities WHERE uid=? AND kind=? AND id=?').get(uid, kind, id)
    return row ? this.cipher.open(row.data, 'data', `${uid}:${kind}:${id}`) : null
  }
  entities(uid, kind, chat = null) {
    const rows = chat ? this.db.prepare('SELECT id FROM entities WHERE uid=? AND kind=? AND chat=?').all(uid, kind, chat)
      : this.db.prepare('SELECT id FROM entities WHERE uid=? AND kind=?').all(uid, kind)
    return rows.map(row => this.entity(uid, kind, row.id))
  }
  *iterEntities(uid, kind, chat = null) {
    let cursor = ''
    while (true) {
      const rows = this.db.prepare(`SELECT id FROM entities WHERE uid=? AND kind=? AND id>?
        AND (? IS NULL OR chat=?) ORDER BY id LIMIT 200`).all(uid, kind, cursor, chat, chat)
      if (!rows.length) return
      for (const row of rows) yield this.entity(uid, kind, row.id)
      cursor = rows.at(-1).id
    }
  }
  putEntity(lease, kind, id, value, indexes = {}, internal = false) {
    const previous = this.entity(lease.uid, kind, id)
    if (previous?.is_deleted && !value.is_deleted && !(kind === 'conversation' && indexes.reopen)) return false
    const payload = { ...value, session_generation: lease.generation, consent_version: this.account(lease.uid).consent_version }
    delete payload.source_revision
    const comparePrevious = previous && { ...previous }
    if (comparePrevious) delete comparePrevious.source_revision
    if (JSON.stringify(comparePrevious) === JSON.stringify(payload)) return false
    const sequence = internal ? 0 : this.change(lease, kind, id)
    payload.source_revision = sequence
    this.db.prepare(`INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(uid,kind,id) DO UPDATE SET
      tombstone=excluded.tombstone,sequence=excluded.sequence,data=excluded.data`)
      .run(lease.uid, kind, id, indexes.chat || null, indexes.externalId || null,
        indexes.fromMe === undefined ? null : Number(indexes.fromMe), indexes.participant || null,
        Number(Boolean(payload.is_deleted)), sequence, this.cipher.seal(payload, 'data', `${lease.uid}:${kind}:${id}`))
    return true
  }
  findMessages(lease, { chat, externalId, fromMe, participant }) {
    const rows = this.db.prepare(`SELECT id FROM entities WHERE uid=? AND kind='message'
      AND chat=? AND external_id=? AND from_me=?`).all(lease.uid, chat, externalId, Number(fromMe))
    return rows.map(row => this.entity(lease.uid, 'message', row.id))
      .filter(value => !participant || value.source_key.participant === participant)
  }
  change(lease, kind, id) {
    const account = this.account(lease.uid)
    return Number(this.db.prepare('INSERT INTO changes(uid,generation,consent,kind,entity_id) VALUES(?,?,?,?,?)')
      .run(lease.uid, lease.generation, account.consent_version, kind, id).lastInsertRowid)
  }
  feed(uid, cursor = 0, limit = 100, kind = null, chat = null) {
    const account = this.account(uid)
    if (!account) throw error('account_not_found', 404)
    if (['paused', 'revoking', 'revoked'].includes(account.status)) throw error(account.status === 'revoked' ? 'revoked' : 'account_paused', 403)
    const rows = this.db.prepare(`SELECT c.* FROM changes c LEFT JOIN entities e
      ON e.uid=c.uid AND e.kind=c.kind AND e.id=c.entity_id
      WHERE c.uid=? AND c.generation=? AND c.consent=? AND c.sequence>? AND (? IS NULL OR c.kind=?)
      AND (? IS NULL OR e.chat=?) ORDER BY c.sequence LIMIT ?`)
      .all(uid, account.session_generation, account.consent_version, cursor, kind, kind, chat, chat, limit + 1)
    const hasMore = rows.length > limit
    const selected = rows.slice(0, limit)
    const items = selected.map(row => ({ sequence: row.sequence, kind: row.kind,
      session_generation: row.generation, consent_version: row.consent,
      payload: row.kind === 'account' ? account : this.entity(uid, row.kind, row.entity_id) }))
    return { items, next_cursor: String(selected.at(-1)?.sequence || cursor), has_more: hasMore, account }
  }
}
