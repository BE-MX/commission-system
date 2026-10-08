import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createAccessMutation } from '../src/views/portal/customerAccess.mjs'

test('invitation unknown outcome replays exact key/body and blocks replacement', async () => {
  const calls = []
  const runner = createAccessMutation(async value => { calls.push(value); if (calls.length === 1) throw new Error('offline'); return { invitation_id: 'i', event_id: 'e', replayed: true } })
  const original = { action: 'invite', id: 'customer', key: 'same-key', body: { email: 'buyer@example.com' } }
  await assert.rejects(runner.execute(original))
  original.body.email = 'other@example.com'
  await assert.rejects(runner.execute(original))
  assert.equal(calls.length, 1)
  await runner.execute()
  assert.deepEqual(calls[0], calls[1]); assert.equal(runner.state, 'success')
})
test('versioned edits never retry an uncertain mutation', async () => {
  let calls = 0
  const runner = createAccessMutation(async () => { calls++; throw new Error('response lost') })
  await assert.rejects(runner.execute({ action: 'account', id: 'a', version: 2, body: { status: 'disabled' } }))
  await assert.rejects(runner.execute())
  assert.equal(calls, 1); assert.equal(runner.state, 'uncertain')
  runner.clear(); assert.equal(runner.pending, null)
})
test('unknown invitation remains uncertain after a later 409', async () => {
  let count = 0
  const runner = createAccessMutation(async () => { if (++count === 1) throw new Error('offline'); throw { response: { status: 409 } } })
  await assert.rejects(runner.execute({ action: 'invite', key: 'one', body: {} }))
  await assert.rejects(runner.execute()); assert.equal(runner.state, 'uncertain')
})
test('double click and identity changes cannot apply a late receipt', async () => {
  let finish
  const runner = createAccessMutation(() => new Promise(resolve => { finish = resolve }))
  const pending = runner.execute({ action: 'account', id: 'a', version: 1, body: {} })
  await assert.rejects(runner.execute({ action: 'account' }))
  runner.clear(); finish({ id: 'a', row_version: 2 })
  assert.equal(await pending, null); assert.equal(runner.state, 'idle')
})
test('known rejection releases form while malformed receipts remain uncertain', async () => {
  const denied = createAccessMutation(async () => { throw { response: { status: 403 } } })
  await assert.rejects(denied.execute({ action: 'account', id: 'a', version: 1 }))
  assert.equal(denied.state, 'failed'); assert.equal(denied.pending, null)
  const malformed = createAccessMutation(async () => ({ id: 'other', row_version: 9 }))
  await assert.rejects(malformed.execute({ action: 'account', id: 'a', version: 1 }))
  assert.equal(malformed.state, 'uncertain')
})
