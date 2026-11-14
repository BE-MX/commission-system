import assert from 'node:assert/strict'
import test from 'node:test'
import { fakeManager, authorization } from './fixtures.mjs'

test('only current credentials publish exact self PN and LID without credential secrets', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].ev.emit('creds.update', { me: { id: '15550001111:4@s.whatsapp.net', lid: '123456789:2@lid' } })
  const result = manager.metadata(store.account('account_a'))
  assert.deepEqual(result.self_identity, { session_generation: 1, pn_jid: '15550001111@s.whatsapp.net', lid_jid: '123456789@lid' })
  assert.equal(result.self_jid, undefined)
  assert.equal(result.creds, undefined)
  manager.stop('account_a')
  assert.deepEqual(manager.metadata(store.account('account_a')).self_identity, result.self_identity)
  store.configure('account_a', { ...authorization, session_generation: 2 })
  assert.equal(manager.metadata(store.account('account_a')).self_identity, undefined)
})

test('startup obtains self identity from already paired credentials without replaying contact mappings', async t => {
  const { manager, store } = fakeManager(t)
  const lease=store.acquire('account_a')
  store.authSet(lease,{creds:{current:{me:{id:'15550001111@s.whatsapp.net',lid:'123456789@lid'}}}})
  store.patchAccount(lease,{contact_metadata_version:1})
  store.release(lease)
  const before=JSON.stringify(store.entities('account_a','contact_alias'))
  await manager.start('account_a')
  assert.equal(manager.metadata(store.account('account_a')).self_identity.lid_jid,'123456789@lid')
  assert.equal(JSON.stringify(store.entities('account_a','contact_alias')),before)
})

test('unknown credential identity is never replaced by contact aliases or another account', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].ev.emit('creds.update',{me:{id:'12345@g.us',lid:'bad@lid'}})
  assert.deepEqual(manager.metadata(store.account('account_a')).self_identity,{session_generation:1,pn_jid:null,lid_jid:null})
  store.configure('account_b',{...authorization,ark_user_id:8})
  assert.equal(manager.metadata(store.account('account_b')).self_identity,undefined)
})

test('logout withdraws published self identity with credentials and preserves messages and conflicts', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].ev.emit('creds.update',{me:{id:'15550001111@s.whatsapp.net',lid:'123456789@lid'}})
  const entry=manager.entries.get('account_a')
  store.putEntity(entry.lease,'contact_alias','ambiguous',{ambiguous:true,jid:'55555555@lid'}, {}, true)
  const before=JSON.stringify(store.entities('account_a','contact_alias'))
  store.clearAuth(entry.lease)
  assert.equal(manager.metadata(store.account('account_a')).self_identity,undefined)
  assert.equal(JSON.stringify(store.entities('account_a','contact_alias')),before)
  assert.equal(store.authGet(entry.lease,'creds',['current']).current,null)
})

test('credential me withdrawal cannot leave the previous self LID in metadata', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].ev.emit('creds.update',{me:{id:'15550001111@s.whatsapp.net',lid:'123456789@lid'}})
  sockets[0].ev.emit('creds.update',{me:null})
  assert.equal(manager.metadata(store.account('account_a')).self_identity.lid_jid,null)
})

test('new generation and explicit fresh credentials atomically retire previous identity', async t => {
  const { manager, store, sockets } = fakeManager(t)
  await manager.start('account_a')
  sockets[0].ev.emit('creds.update',{me:{id:'15550001111@s.whatsapp.net',lid:'123456789@lid'}})
  manager.stop('account_a')
  const write=store.writeAccount.bind(store)
  store.writeAccount=()=>{throw new Error('simulated persistence failure')}
  assert.throws(()=>store.configure('account_a',{...authorization,session_generation:2}),/simulated/)
  store.writeAccount=write
  assert.equal(store.account('account_a').session_generation,1)
  let lease=store.acquire('account_a')
  assert.ok(store.authGet(lease,'creds',['current']).current.value.me)
  store.release(lease)
  store.configure('account_a',{...authorization,session_generation:2})
  lease=store.acquire('account_a')
  assert.equal(store.authGet(lease,'creds',['current']).current,null)
  assert.equal(store.account('account_a').self_identity,undefined)
  store.authSet(lease,{creds:{current:{me:{id:'15550003333@s.whatsapp.net'}}}})
  store.release(lease)
  store.configure('account_a',{...authorization,session_generation:2},{freshCredentials:true})
  lease=store.acquire('account_a')
  assert.equal(store.authGet(lease,'creds',['current']).current,null)
  store.release(lease)
})
