import assert from 'node:assert/strict'
import test from 'node:test'
import { fixture, fakeManager, message, tick, authorization } from './fixtures.mjs'
import { Projector, conversationId, hash } from '../src/projection.js'
import { makeEventBuffer } from 'baileys/lib/Utils/event-buffer.js'
import pino from 'pino'
import { initAuthCreds } from 'baileys'

const lid = '987654321@lid'
const pn = '15550003333@s.whatsapp.net'
const conversation = store => store.entity('account_a', 'conversation', conversationId('account_a', lid))

test('history mapping joins PN contact metadata to the existing LID conversation without changing identity', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'chats.upsert', [{ id: lid }])
  const before = conversation(store).conversation_uid
  const cursor = Number(store.feed('account_a').next_cursor)
  projector.ingest(lease, 'messaging-history.set', {
    contacts: [{ id: pn, name: 'Saved customer' }], lidPnMappings: [{ lid, pn }], chats: [], messages: [],
  })
  assert.equal(conversation(store).contact_name, 'Saved customer')
  assert.equal(conversation(store).contact_phone, '+15550003333')
  assert.equal(conversation(store).conversation_uid, before)
  assert.equal(store.entities('account_a', 'conversation').length, 1)
  assert.ok(store.feed('account_a', cursor).items.some(row => row.kind === 'conversation'))
})

test('contact alias works before chats, retains metadata through partial updates and propagates later names', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'contacts.upsert', [{ id: pn, lid, name: 'Saved name', notify: 'Nickname' }])
  projector.ingest(lease, 'contacts.update', [{ id: pn, name: undefined, notify: null, imgUrl: 'changed' }])
  projector.ingest(lease, 'chats.upsert', [{ id: lid }])
  assert.equal(conversation(store).contact_name, 'Saved name')
  assert.equal(conversation(store).contact_phone, '+15550003333')
  projector.ingest(lease, 'contacts.update', [{ id: pn, name: 'Updated name' }])
  assert.equal(conversation(store).contact_name, 'Updated name')
})

test('verified names, usernames and chat pnJid are recognized without treating LIDs as phone numbers', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'contacts.upsert', [{ id: lid, verifiedName: 'Business' }])
  projector.ingest(lease, 'chats.upsert', [{ id: lid, pnJid: pn }])
  assert.equal(conversation(store).contact_name, 'Business')
  assert.equal(conversation(store).contact_phone, '+15550003333')
  const other = '88888888@lid'
  projector.ingest(lease, 'contacts.upsert', [{ id: other, username: 'wa_handle' }])
  projector.ingest(lease, 'chats.upsert', [{ id: other }])
  const row = store.entity('account_a', 'conversation', conversationId('account_a', other))
  assert.equal(row.contact_name, 'wa_handle')
  assert.equal(row.contact_phone, null)
})

test('only incoming direct messages supply fallback names; own names and group participants never label customers', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  const ingest = raw => projector.ingest(lease, 'messages.upsert', { type: 'notify', messages: [raw] })
  ingest({ ...message('out', 'test', 1000, { remoteJid: lid, fromMe: true }), pushName: 'Salesperson' })
  assert.equal(conversation(store).contact_name, null)
  ingest({ ...message('in', 'test', 1001, { remoteJid: lid }), pushName: 'Customer nickname' })
  assert.equal(conversation(store).contact_name, 'Customer nickname')
  projector.ingest(lease, 'contacts.upsert', [{ id: lid, name: 'Saved customer' }])
  ingest({ ...message('in2', 'test', 1002, { remoteJid: lid }), pushName: 'Other nickname' })
  assert.equal(conversation(store).contact_name, 'Saved customer')
  ingest(message('group', 'test', 1003, { remoteJid: '12345@g.us', participant: pn }))
  assert.equal(store.entity('account_a', 'conversation', conversationId('account_a', '12345@g.us')).contact_name, null)
})

test('manager consumes live mapping events and leaves other accounts and message identities alone', async t => {
  const { store, manager, sockets } = fakeManager(t)
  store.configure('account_b', { ...authorization, ark_user_id: 8 })
  const otherLease = store.acquire('account_b')
  new Projector(store).ingest(otherLease, 'chats.upsert', [{ id: lid }])
  await manager.start('account_a')
  sockets[0].ev.emit('chats.upsert', [{ id: lid }])
  sockets[0].ev.emit('lid-mapping.update', { lid, pn })
  sockets[0].ev.emit('contacts.upsert', [{ id: pn, notify: 'Live name' }])
  await tick(); await manager.entries.get('account_a').queue
  assert.equal(conversation(store).contact_phone, '+15550003333')
  assert.equal(conversation(store).contact_name, 'Live name')
  assert.equal(store.entity('account_b', 'conversation', conversationId('account_b', lid)).contact_phone, null)
  assert.equal(store.entities('account_a', 'message').length, 0)
})

test('authorized startup repairs cached metadata using verified provider mappings, idempotently, without reviving deleted chats', async t => {
  const { store, manager } = fakeManager(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'chats.upsert', [{ id: lid }])
  store.transaction(() => store.putEntity(lease, 'contact', hash(pn), { id: pn, name: 'Cached customer' }, {}, true))
  store.authSet(lease, { 'lid-mapping': { '987654321_reverse': '15550003333', '15550003333': '987654321' } })
  store.authSet(lease, { creds: { current: { ...initAuthCreds(), registered: false,
    me: { id: '15550009999@s.whatsapp.net', lid: '111111111@lid' } } } })
  projector.ingest(lease, 'chats.delete', ['7777777@lid'])
  store.release(lease)
  await manager.start('account_a')
  assert.equal(conversation(store).contact_name, 'Cached customer')
  assert.equal(conversation(store).contact_phone, '+15550003333')
  const deleted = store.entity('account_a', 'conversation', conversationId('account_a', '7777777@lid'))
  assert.equal(deleted.is_deleted, true)
  const revision = conversation(store).source_revision
  await manager.projector.refreshMetadata(manager.entries.get('account_a').lease, async () => {})
  assert.equal(conversation(store).source_revision, revision)
})

test('conflicting mappings quarantine aliases without dropping other history or pausing collection', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'chats.upsert', [{ id: lid }])
  projector.ingest(lease, 'lid-mapping.update', { lid, pn: '12345@g.us' })
  assert.equal(conversation(store).contact_phone, null)
  projector.ingest(lease, 'lid-mapping.update', { lid, pn })
  projector.ingest(lease, 'messaging-history.set', {
    lidPnMappings: [{ lid: '999999999@lid', pn: '15550004444@s.whatsapp.net' }, { lid, pn: '15550005555@s.whatsapp.net' }],
    messages: [message('unrelated', 'still collected')],
  })
  assert.equal(conversation(store).contact_phone, '+15550003333')
  assert.equal(store.entity('account_a', 'contact_alias', hash('999999999@lid')).other, '15550004444@s.whatsapp.net')
  assert.equal(store.entity('account_a', 'contact_alias', hash(lid)).ambiguous, true)
  projector.ingest(lease, 'contacts.update', [{ id: pn, notify: 'Must not cross to old LID' }])
  assert.equal(conversation(store).contact_name, null)
  assert.equal(store.entities('account_a', 'message').length, 1)
  assert.equal(store.account('account_a').coverage.gap_reason, 'contact_identity_conflict')
})

test('same-batch ambiguity cannot first publish an arbitrary name or phone but keeps a PN chat own metadata', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'chats.upsert', [{ id: lid }])
  projector.ingest(lease, 'contacts.upsert', [{ id: pn, name: 'First person' }])
  projector.ingest(lease, 'messaging-history.set', {
    lidPnMappings: [{ lid, pn }, { lid, pn: '15550004444@s.whatsapp.net' }],
    chats: [{ id: pn }], contacts: [], messages: [],
  })
  assert.equal(conversation(store).contact_name, null)
  assert.equal(conversation(store).contact_phone, null)
  const direct = store.entity('account_a', 'conversation', conversationId('account_a', pn))
  assert.equal(direct.contact_phone, '+15550003333')
  assert.equal(direct.contact_name, 'First person')
})

test('pause during startup backfill retains operator state instead of replacing it with a lease error', async t => {
  let calls = 0, unblock, reached
  const entered = new Promise(resolve => { reached = resolve })
  const gate = new Promise(resolve => { unblock = resolve })
  const { store, manager } = fakeManager(t, { authorize: async () => {
    if (++calls === 3) { reached(); await gate }
    return { ...authorization }
  } })
  const lease = store.acquire('account_a')
  store.authSet(lease, { creds: { current: { ...initAuthCreds(), me: { id: '15550009999@s.whatsapp.net' } } } })
  store.patchAccount(lease, { status: 'active' })
  new Projector(store).ingest(lease, 'chats.upsert', [{ id: lid }])
  store.release(lease)
  const restoring = manager.restore()
  await entered
  await manager.pause('account_a')
  unblock(); await restoring
  assert.equal(store.account('account_a').last_error_code, 'collection_paused')
  assert.equal(store.account('account_a').status, 'paused')
  assert.equal(store.account('account_a').contact_metadata_version, undefined)
})

test('real rc14 buffered history recovers mappings from auth while already running, after startup marker', async t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  await projector.refreshMetadata(lease, async () => {})
  store.authSet(lease, { 'lid-mapping': { '987654321_reverse': '15550003333', '15550003333': '987654321' } })
  const events = makeEventBuffer(pino({ level: 'silent' }))
  let observed
  events.on('messaging-history.set', event => { observed = event; projector.ingest(lease, 'messaging-history.set', event) })
  events.buffer()
  events.emit('messaging-history.set', { contacts: [{ id: pn, notify: 'History name' }], chats: [{ id: lid }],
    messages: [], isLatest: true, lidPnMappings: [{ lid, pn }] })
  events.flush()
  assert.equal(observed.lidPnMappings, undefined)
  assert.equal(conversation(store).contact_name, 'History name')
  assert.equal(conversation(store).contact_phone, '+15550003333')
})

test('outgoing alternate address and provider self mappings never turn the seller into the customer', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  store.authSet(lease, { creds: { current: { me: { id: pn, lid: '111111111@lid' } } },
    'lid-mapping': { '987654321_reverse': '15550003333', '15550003333': '987654321' } })
  projector.ingest(lease, 'contacts.upsert', [{ id: pn, name: 'Salesperson' }])
  projector.ingest(lease, 'messages.upsert', { messages: [message('out', 'sent', 1000, {
    remoteJid: lid, remoteJidAlt: pn, fromMe: true,
  })] })
  assert.equal(conversation(store).contact_name, null)
  assert.equal(conversation(store).contact_phone, null)
  assert.equal(store.entity('account_a', 'contact_alias', hash(lid)), null)
  projector.ingest(lease, 'chats.upsert', [{ id: lid, pnJid: pn, altJid: pn }])
  assert.equal(conversation(store).contact_phone, null)
  assert.equal(conversation(store).alt_jid, null)
})

test('a later LID contact repairs the existing PN chat using mutually verified provider keys', t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'chats.upsert', [{ id: pn }])
  store.authSet(lease, { 'lid-mapping': { '987654321_reverse': '15550003333', '15550003333': '987654321' } })
  projector.ingest(lease, 'contacts.upsert', [{ id: lid, name: 'LID saved name' }])
  assert.equal(store.entity('account_a', 'conversation', conversationId('account_a', pn)).contact_name, 'LID saved name')
  assert.equal(store.entities('account_a', 'conversation').length, 1)
})

test('fresh binding skips cached backfill and restore retains conflicts discovered by backfill', async t => {
  const { store, manager } = fakeManager(t)
  let lease = store.acquire('account_a')
  const projector = new Projector(store)
  store.authSet(lease, { creds: { current: { ...initAuthCreds(), registered: true } } })
  projector.ingest(lease, 'chats.upsert', [{ id: lid }])
  projector.ingest(lease, 'lid-mapping.update', { lid, pn })
  store.authSet(lease, { 'lid-mapping': { '987654321_reverse': '15550005555', '15550005555': '987654321' } })
  store.release(lease)
  await manager.start('account_a', { freshBind: true })
  assert.equal(store.account('account_a').contact_metadata_version, undefined)
  manager.stop('account_a')
  await manager.restore()
  assert.equal(store.account('account_a').coverage.gap_reason, 'contact_identity_conflict')
  assert.equal(store.account('account_a').contact_metadata_version, 1)
})

test('startup ignores stale reverse mappings and stops on authorization denial before marking repair complete', async t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'chats.upsert', [{ id: lid }])
  store.authSet(lease, { 'lid-mapping': { '987654321_reverse': '15550003333', '15550003333': '111111111' } })
  await assert.rejects(projector.refreshMetadata(lease, async () => { throw new Error('authorization_denied') }), /authorization_denied/)
  assert.equal(store.account('account_a').contact_metadata_version, undefined)
  await projector.refreshMetadata(lease, async () => {})
  assert.equal(conversation(store).contact_phone, null)
})

test('metadata-only repairs preserve all message records and cannot fill names from outgoing messages', async t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'messages.upsert', { messages: [
    { ...message('out', 'body', 1000, { remoteJid: lid, fromMe: true }), pushName: 'Seller' },
  ] })
  const messages = store.entities('account_a', 'message')
  await projector.refreshMetadata(lease, async () => {})
  assert.equal(conversation(store).contact_name, null)
  assert.deepEqual(store.entities('account_a', 'message'), messages)
})

test('startup fills only missing metadata without temporarily publishing a replacement for existing names or numbers', async t => {
  const { store } = fixture(t)
  const lease = store.acquire('account_a')
  const projector = new Projector(store)
  projector.ingest(lease, 'chats.upsert', [{ id: lid, name: 'Familiar nickname' }])
  const current = conversation(store)
  store.transaction(() => {
    store.putEntity(lease, 'conversation', current.conversation_uid, { ...current, contact_phone: '+15550006666' })
    store.putEntity(lease, 'contact', hash(pn), { id: pn, lid, name: 'Different saved name' }, {}, true)
  })
  const snapshots = [], originalPut = store.putEntity.bind(store)
  store.putEntity = (...args) => {
    if (args[1] === 'conversation') snapshots.push([args[3].contact_name, args[3].contact_phone])
    return originalPut(...args)
  }
  await projector.refreshMetadata(lease, async () => {})
  assert.equal(conversation(store).contact_name, 'Familiar nickname')
  assert.equal(conversation(store).contact_phone, '+15550006666')
  assert.ok(snapshots.length > 0)
  assert.ok(snapshots.every(([name, phone]) => name === 'Familiar nickname' && phone === '+15550006666'))
})
