import test from 'node:test'
import assert from 'node:assert/strict'
import { createNotificationCommand } from '../src/views/portal/notificationDelivery.mjs'

const input = () => ({ id: 'request1', eventId: 'event1', key: 'key1', body: { fingerprint: 'a'.repeat(64), reason: 'Recovered mail transport' } })
const receipt = value => ({ replayed: false, original_receipt: { request_id: value.id, event_id: value.eventId, command_key: value.key, status: 'pending' }, current: { id: value.eventId, status: 'pending' } })
test('unknown result freezes and replays exact event, command key and body', async () => {
  const sent = []
  const command = createNotificationCommand(async value => { sent.push(value); if (sent.length === 1) throw new Error('offline'); return receipt(value) })
  const value = input()
  await assert.rejects(command.execute(value)); value.body.reason = 'changed'
  assert.equal(command.state, 'uncertain')
  await assert.rejects(command.execute(value))
  const result = await command.execute()
  assert.deepEqual(sent[0], sent[1]); assert.equal(result.current_state, 'pending')
})
for (const field of ['request_id', 'event_id', 'command_key', 'status']) test(`mismatched receipt ${field} remains uncertain`, async () => {
  const command = createNotificationCommand(async value => { const result = receipt(value); result.original_receipt[field] = 'wrong'; return result })
  await assert.rejects(command.execute(input())); assert.equal(command.state, 'uncertain')
})
test('replay reports current sent state without inventing a new enqueue', async () => {
  const command = createNotificationCommand(async value => ({ ...receipt(value), replayed: true, current: { id: value.eventId, status: 'sent' } }))
  assert.equal((await command.execute(input())).current_state, 'sent')
})
test('identity reset drops late receipt', async () => {
  let resolve
  const command = createNotificationCommand(value => new Promise(done => { resolve = () => done(receipt(value)) }))
  const pending = command.execute(input()); command.clear(); resolve()
  assert.equal(await pending, null); assert.equal(command.pending, null)
})
for (const scope of ['mapping', 'order']) test(`${scope} notification receipt cannot impersonate the other scope`, async () => {
  const field = scope === 'mapping' ? 'access_id' : 'request_id'
  const other = scope === 'mapping' ? 'request_id' : 'access_id'
  const command = createNotificationCommand(async value => {
    const result = receipt(value)
    result.original_receipt = { ...result.original_receipt, [field]: 'wrong', [other]: value.id }
    return result
  }, { scope })
  await assert.rejects(command.execute(input())); assert.equal(command.state, 'uncertain')
})
test('mapping notification retry recovers exact access receipt and current state', async () => {
  const calls=[]
  const command=createNotificationCommand(async value => {
    calls.push(value)
    if(calls.length===1) throw new Error('response lost')
    const result=receipt(value); delete result.original_receipt.request_id
    result.original_receipt.access_id=value.id; result.replayed=true; result.current.status='sent'
    return result
  },{scope:'mapping'})
  await assert.rejects(command.execute(input()))
  assert.equal(command.state,'uncertain')
  const replay=await command.execute()
  assert.deepEqual(calls[0],calls[1]); assert.equal(replay.current_state,'sent')
  assert.equal(replay.original_receipt.access_id,input().id)
  assert.ok(!('request_id' in replay.original_receipt))
})
test('unsupported notification scope is refused before sending', () => {
  assert.throws(()=>createNotificationCommand(()=>assert.fail(),{scope:'employee'}))
})
