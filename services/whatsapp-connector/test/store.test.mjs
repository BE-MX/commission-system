import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { statSync } from 'node:fs'
import { fork } from 'node:child_process'
import { once } from 'node:events'
import { Store } from '../src/store.js'
import { authState } from '../src/auth-state.js'
import { Projector, hash, messageId, phone } from '../src/projection.js'
import { Cipher } from '../src/crypto.js'
import { proto } from 'baileys'
import { encryptionKey, authorization, fixture, message, sleep } from './fixtures.mjs'

test('AES domains, identity binding and required key fail closed', () => {
  for (const key of ['', 'short', Buffer.alloc(31).toString('base64')]) assert.throws(() => new Cipher(key), /key/)
  const cipher = new Cipher(encryptionKey)
  const sealed = cipher.seal({ secret: Buffer.from('synthetic-key') }, 'auth', 'account_a:session:1')
  assert.deepEqual(cipher.open(sealed, 'auth', 'account_a:session:1').secret, Buffer.from('synthetic-key'))
  assert.throws(() => cipher.open(sealed, 'data', 'account_a:session:1'), /unreadable/)
  assert.throws(() => cipher.open(sealed, 'auth', 'account_b:session:1'), /unreadable/)
  assert.throws(() => new Cipher(encryptionKey, '2').open(sealed, 'auth', 'account_a:session:1'), /version/)
})

test('auth buffers and all Signal categories persist atomically, CAS and null deletion survive reopen', t => {
  const { store, filename } = fixture(t)
  const lease = store.acquire('account_a', 'first')
  const state = authState(store, lease, () => {})
  state.saveCreds({ registered: true })
  const updates = { session: { 'sender-device': Buffer.from('secret-signal-key') },
    'pre-key': { '8': { key: Buffer.from('pre-key') } }, 'sender-key': { group: Buffer.from('group-key') },
    'app-state-sync-key': { abc: { keyData: Buffer.from('state-key'), timestamp: 1, fingerprint: { rawId: 2 } } },
    'lid-mapping': { lid: '15550003333@s.whatsapp.net' } }
  return state.state.keys.set(updates).then(async () => {
    const restored = await state.state.keys.get('app-state-sync-key', ['abc'])
    assert.deepEqual(Buffer.from(restored.abc.keyData), Buffer.from('state-key'))
    const rev = store.authGet(lease, 'session', ['sender-device'])['sender-device'].revision
    assert.throws(() => store.authSet(lease, { session: { 'sender-device': Buffer.from('bad'), second: 'must-not-persist' } },
      { 'session:sender-device': rev - 1 }), /cas_conflict/)
    assert.equal(store.authGet(lease, 'session', ['second']).second, null)
    store.authSet(lease, { session: { 'sender-device': null } }, { 'session:sender-device': rev })
    assert.equal(store.authGet(lease, 'session', ['sender-device'])['sender-device'].value, null)
    assert.throws(() => store.authSet(lease, { session: { 'sender-device': 'stale-recreate' } },
      { 'session:sender-device': rev }), /cas_conflict/)
    store.release(lease)
    const second = new Store(filename, { encryptionKey })
    try {
      const lease2 = second.acquire('account_a', 'restored')
      const auth = authState(second, lease2, () => {})
      assert.equal(auth.state.creds.registered, true)
      assert.equal(Buffer.isBuffer(auth.state.creds.noiseKey.private), true)
      assert.equal((await auth.state.keys.get('session', ['sender-device']))['sender-device'], null)
      assert.deepEqual((await auth.state.keys.get('pre-key', ['8']))['8'].key, Buffer.from('pre-key'))
      assert.deepEqual((await auth.state.keys.get('sender-key', ['group'])).group, Buffer.from('group-key'))
      second.release(lease2)
    } finally { second.close() }
    for (const suffix of ['', '-wal']) {
      const raw = readFileSync(filename + suffix)
      assert.equal(raw.includes(Buffer.from('secret-signal-key')), false)
      assert.equal(raw.includes(Buffer.from('Synthetic body')), false)
    }
  })
})

test('two stores fence expiry and takeover, engine-clock tokens monotonically increase', async t => {
  const { store, filename, onCleanup } = fixture(t)
  const contender = new Store(filename, { encryptionKey })
  onCleanup(() => contender.close())
  const first = store.acquire('account_a', 'first', 70)
  assert.throws(() => contender.acquire('account_a', 'second'), /lease_busy/)
  await sleep(100)
  const second = contender.acquire('account_a', 'second')
  assert.ok(second.token > first.token)
  assert.throws(() => store.authSet(first, { session: { obsolete: 'old' } }), /stale_lease/)
  assert.throws(() => store.ingest(first, 'test', () => {}), /stale_lease/)
  assert.throws(() => store.patchAccount(first, { status: 'active' }), /stale_lease/)
  store.release(first)
  assert.doesNotThrow(() => contender.fence(second))
  contender.release(second)
})

test('real process crash and concurrent process contention preserve shared auth and fencing', async t => {
  const { store, filename } = fixture(t)
  const worker = new URL('./lease-worker.mjs', import.meta.url)
  const first = fork(worker, [filename, encryptionKey, '500'], { stdio: ['ignore', 'ignore', 'ignore', 'ipc'] })
  t.after(() => { if (!first.killed) first.kill() })
  const [acquired] = await once(first, 'message')
  assert.equal(acquired.acquired, true)
  const second = fork(worker, [filename, encryptionKey, '500'], { stdio: ['ignore', 'ignore', 'ignore', 'ipc'] })
  t.after(() => { if (!second.killed) second.kill() })
  const [blocked] = await once(second, 'message')
  assert.equal(blocked.code, 'lease_busy')
  const crashed = once(first, 'exit'); first.kill(); await crashed
  const stopped = once(second, 'exit'); second.kill(); await stopped
  await sleep(550)
  const lease = store.acquire('account_a', 'after-crash')
  assert.ok(lease.token > acquired.token)
  assert.deepEqual(store.authGet(lease, 'session', ['child']).child.value, Buffer.from('synthetic-signal-key'))
  store.release(lease)
})

test('account owner and active lease authority cannot be rebound by another owner or generation', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  assert.throws(() => store.configure('account_a', { ...authorization, ark_user_id: 8 }), /owner_mismatch/)
  assert.throws(() => store.configure('account_a', { ...authorization, session_generation: 2 }), /lease_busy/)
  assert.throws(() => store.configure('account_a', { ...authorization, consent_version: '2' }), /lease_busy/)
  store.release(lease)
  store.configure('account_a', { ...authorization, session_generation: 2 })
  assert.throws(() => store.configure('account_a', authorization), /stale_generation/)
})

test('notify/append/history arrays project all messages, stable IDs, same and old timestamps never lose data', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'messages.upsert', { type: 'notify', messages: [message('one'), message('two')] }, 'event-one')
  const cursor = store.feed('account_a').next_cursor
  projector.ingest(lease, 'messages.upsert', { type: 'append', messages: [message('old', 'old history', 10)] })
  const old = store.feed('account_a', Number(cursor), 100, 'message').items
  assert.equal(old.length, 1)
  assert.equal(old[0].payload.external_message_id, 'old')
  projector.ingest(lease, 'messaging-history.set', { messages: [message('three'), message('four')],
    chats: [{ id: '12345@g.us', name: 'Group' }], contacts: [{ id: '15550002222@s.whatsapp.net', name: 'Known' }], isLatest: true })
  assert.equal(store.entities('account_a', 'message').length, 5)
  assert.equal(store.account('account_a').history_state, 'partial')
  assert.equal(store.account('account_a').history_batch_complete, true)
  assert.equal(store.account('account_a').coverage.earliest_message_at, new Date(10000).toISOString())
  assert.equal(projector.ingest(lease, 'messages.upsert', { messages: [message('duplicate-event')] }, 'event-one'), false)
  assert.equal(store.entities('account_a', 'message').length, 5)
  const end = store.feed('account_a').next_cursor
  assert.equal(store.feed('account_a', Number(end)).next_cursor, end)
  assert.equal(store.feed('account_a', Number(end)).has_more, false)
  store.release(lease)
})

test('event inbox/projection/change/account coverage roll back together on invalid batch member', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  assert.throws(() => projector.ingest(lease, 'messages.upsert', { messages: [message('valid'), { key: {} }] }, 'broken'), /invalid_message_key/)
  assert.equal(store.entities('account_a', 'message').length, 0)
  assert.equal(store.feed('account_a').items.length, 0)
  assert.equal(store.db.prepare('SELECT COUNT(*) AS count FROM inbox').get().count, 0)
  assert.equal(store.account('account_a').coverage.last_ingest_at, null)
  store.release(lease)
})

test('full source key prevents ID collisions and preserves LID alternate PN without guessing phone', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const a = message('same', 'group', 100, { remoteJid: '10000@g.us', participant: '777@lid', participantAlt: '15550004444@s.whatsapp.net' })
  const b = message('same', 'other', 100, { remoteJid: '20000@g.us', participant: '888@lid' })
  const c = message('same', 'my copy', 100, { remoteJid: '10000@g.us', participant: '777@lid', fromMe: true })
  const d = message('same', 'second participant', 100, { remoteJid: '10000@g.us', participant: '999@lid' })
  projector.ingest(lease, 'messages.upsert', { messages: [a, b, c, d] })
  const all = store.entities('account_a', 'message')
  assert.equal(new Set(all.map(item => item.message_uid)).size, 4)
  assert.equal(all.find(item => item.content_text === 'group').sender_phone, '+15550004444')
  assert.equal(all.find(item => item.content_text === 'other').sender_phone, null)
  assert.equal(all.every(item => item.message_uid.length < 100), true)
  assert.equal(phone('10000@g.us'), null)
  assert.equal(phone('15550004444@lid'), null)
  assert.deepEqual(store.entity('account_a', 'message', messageId('account_a', a.key)).source_key, a.key)
  store.release(lease)
})

test('edits replace body pointers and tombstones survive delayed history and missing participant deletes', t => {
  const { store, filename } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const raw = message('edit', 'ORIGINAL_PRIVATE_BODY')
  projector.ingest(lease, 'messages.upsert', { messages: [raw] })
  projector.ingest(lease, 'messages.update', [{ key: raw.key, update: { message: { conversation: 'EDITED_PRIVATE_BODY' } } }])
  assert.equal(store.feed('account_a', 0, 100, 'message').items.every(item => item.payload.content_text === 'EDITED_PRIVATE_BODY'), true)
  projector.ingest(lease, 'messages.upsert', { type: 'append', messages: [raw] })
  assert.equal(store.entity('account_a', 'message', messageId('account_a', raw.key)).content_text, 'EDITED_PRIVATE_BODY')
  projector.ingest(lease, 'messages.delete', { keys: [raw.key] })
  projector.ingest(lease, 'messaging-history.set', { messages: [raw] })
  const changes = store.feed('account_a', 0, 100, 'message').items
  assert.equal(changes.every(item => item.payload.is_deleted && item.payload.content_text === ''), true)
  assert.equal(store.entities('account_a', 'conversation')[0].last_message_preview, '')
  const late = message('late-group', 'late body', 100, { remoteJid: '10000@g.us', participant: '999@lid' })
  projector.ingest(lease, 'messages.delete', { keys: [{ ...late.key, participant: undefined }] })
  projector.ingest(lease, 'messaging-history.set', { messages: [late] })
  assert.equal(store.entity('account_a', 'message', messageId('account_a', late.key)), null)
  for (const suffix of ['', '-wal']) {
    const rawFile = readFileSync(filename + suffix)
    assert.equal(rawFile.includes(Buffer.from('ORIGINAL_PRIVATE_BODY')), false)
    assert.equal(rawFile.includes(Buffer.from('EDITED_PRIVATE_BODY')), false)
    assert.equal(rawFile.includes(Buffer.from('15550002222')), false)
  }
  store.release(lease)
})

test('chat-filtered sequence pagination and disk/row capacity reject gaps visibly without silent truncation', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'messages.upsert', { messages: [message('a'), message('b', 'second', 1, { remoteJid: '15550003333@s.whatsapp.net' })] })
  const data = store.feed('account_a', 0, 1, 'message', hash('15550002222@s.whatsapp.net'))
  assert.equal(data.items.length, 1)
  assert.equal(data.items[0].payload.external_message_id, 'a')
  const empty = store.feed('account_a', Number(data.next_cursor), 1, 'message', hash('15550002222@s.whatsapp.net'))
  assert.equal(empty.next_cursor, data.next_cursor)
  assert.equal(empty.items.length, 0)
  store.maxBytes = 1024
  assert.throws(() => projector.ingest(lease, 'messages.upsert', { messages: [message('overflow')] }), /disk_capacity/)
  store.maxBytes = 1024 ** 3; store.maxRows = 1
  assert.throws(() => projector.ingest(lease, 'messages.upsert', { messages: [message('overflow')] }), /retention_capacity/)
  store.release(lease)
})

test('lease expiry inside real transaction rejects the entire commit', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a', 'short', 50)
  const projector = new Projector(store)
  assert.throws(() => store.ingest(lease, 'synthetic-slow-event', () => {
    projector.message(lease, message('must-rollback'))
    const deadline = Date.now() + 80
    while (Date.now() < deadline) { /* deliberately expire the engine-clock lease before commit */ }
  }), /stale_lease/)
  assert.equal(store.entities('account_a', 'message').length, 0)
  assert.equal(store.db.prepare('SELECT COUNT(*) AS count FROM inbox').get().count, 0)
})

test('group protocol edit without target participant replaces existing full-key body; late delete creates conversation first', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const original = message('group-target', 'before edit', 1, { remoteJid: '10000@g.us', participant: '555@lid' })
  projector.ingest(lease, 'messages.upsert', { messages: [original] })
  const edit = { key: { ...original.key, id: 'protocol-edit' }, messageTimestamp: 2,
    message: { protocolMessage: { type: proto.Message.ProtocolMessage.Type.MESSAGE_EDIT,
      key: { remoteJid: original.key.remoteJid, id: original.key.id, fromMe: false }, editedMessage: { conversation: 'after edit' } } } }
  projector.ingest(lease, 'messages.upsert', { messages: [edit] })
  assert.equal(store.entities('account_a', 'message').length, 1)
  assert.equal(store.entities('account_a', 'message')[0].content_text, 'after edit')
  const cursor = store.feed('account_a').next_cursor
  projector.ingest(lease, 'messages.delete', { keys: [message('never-received', '', 1, { remoteJid: '99999@g.us' }).key] })
  const feed = store.feed('account_a', Number(cursor)).items
  assert.equal(feed[0].kind, 'conversation')
  assert.equal(feed.find(item => item.kind === 'message').payload.is_deleted, true)
  store.release(lease)
})

test('one oversized batch cannot cross the total record quota then commit', t => {
  const { store } = fixture(t, { maxRows: 5 })
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  assert.throws(() => projector.ingest(lease, 'messages.upsert', { messages: [message('a'), message('b')] }), /retention_capacity/)
  assert.equal(store.entities('account_a', 'message').length, 0)
  assert.equal(store.feed('account_a').items.length, 0)
  store.release(lease)
})

test('a deleted chat accepts fresh notify IDs while deleted IDs and late history remain suppressed', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const old = message('before-delete', 'old body', 1)
  projector.ingest(lease, 'messages.upsert', { type: 'notify', messages: [old] })
  projector.ingest(lease, 'chats.delete', [old.key.remoteJid])
  const fresh = message('after-delete', 'new body', 2)
  projector.ingest(lease, 'messages.upsert', { type: 'notify', messages: [fresh] })
  assert.equal(store.entity('account_a', 'message', messageId('account_a', fresh.key)).content_text, 'new body')
  projector.ingest(lease, 'messaging-history.set', { chats: [{ id: old.key.remoteJid }], messages: [old, message('unseen-old', 'historical old body', 1)] })
  assert.equal(store.entity('account_a', 'message', messageId('account_a', old.key)).content_text, '')
  assert.equal(store.entity('account_a', 'message', messageId('account_a', message('unseen-old').key)), null)
  assert.equal(store.entities('account_a', 'conversation')[0].last_message_preview, 'new body')
  store.release(lease)
})

test('rc14 editedMessage event wrapper keeps edited body rather than overwriting it with unsupported placeholder', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const original = message('actual-edit', 'old body', 1)
  projector.ingest(lease, 'messages.upsert', { type: 'notify', messages: [original] })
  projector.ingest(lease, 'messages.update', [{ key: original.key,
    update: { message: { editedMessage: { message: { conversation: 'actual edited body' } } } } }])
  assert.equal(store.entity('account_a', 'message', messageId('account_a', original.key)).content_text, 'actual edited body')
  projector.ingest(lease, 'messages.upsert', { type: 'append', messages: [original] })
  assert.equal(store.entity('account_a', 'message', messageId('account_a', original.key)).content_text, 'actual edited body')
  store.release(lease)
})

test('post-reopen newer append syncs while unproved old edits/ambiguous history expose a gap', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const old = message('deleted', 'old body', 1)
  projector.ingest(lease, 'messages.upsert', { type: 'notify', messages: [old] })
  projector.ingest(lease, 'chats.delete', [old.key.remoteJid])
  const fresh = message('new-live', 'fresh body', 2)
  projector.ingest(lease, 'messages.upsert', { type: 'notify', messages: [fresh] })
  const later = message('new-offline', 'new offline body', 3)
  projector.ingest(lease, 'messages.upsert', { type: 'append', messages: [later] })
  assert.equal(store.entity('account_a', 'message', messageId('account_a', later.key)).content_text, 'new offline body')
  const unknown = message('unknown-old-edit', '', 1)
  projector.ingest(lease, 'messages.update', [{ key: unknown.key, update: { message: { conversation: 'old edited body' }, messageTimestamp: 1 } }])
  assert.equal(store.entity('account_a', 'message', messageId('account_a', unknown.key)), null)
  assert.equal(store.account('account_a').coverage.gap_reason, 'deleted_chat_history_ambiguous')
  projector.ingest(lease, 'messages.update', [{ key: fresh.key, update: { message: { conversation: 'updated fresh' } } }])
  assert.equal(store.entity('account_a', 'message', messageId('account_a', fresh.key)).content_text, 'updated fresh')
  store.release(lease)
})

test('real SQLite uncommitted page expansion cannot commit a batch beyond disk budget', t => {
  const { store, filename } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const batch = { type: 'notify', messages: Array.from({ length: 200 }, (_, i) => message(`small-${i}`, '', 1)) }
  const bytes = Buffer.byteLength(JSON.stringify(batch))
  const size = () => ['', '-wal'].reduce((sum, suffix) => sum + statSync(filename + suffix).size, 0)
  store.maxBytes = size() + bytes * 4 + 8192
  const budget = store.maxBytes
  assert.throws(() => projector.ingest(lease, 'messages.upsert', batch, 'disk-expansion', bytes), /disk_capacity/)
  assert.equal(store.entities('account_a', 'message').length, 0)
  assert.ok(size() <= budget)
  store.release(lease)
})
