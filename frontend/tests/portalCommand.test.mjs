import test from 'node:test'
import assert from 'node:assert/strict'
import { createAdminCommand } from '../src/views/portal/command.mjs'
const sample = () => ({ id: 'request-1', version: 3, action: 'approve', body: { accepted_revision_id: 'revision-1' } })
const receipt = () => ({ original_receipt: { request_id: 'request-1' }, current_state: 'invoice_created' })
test('uncertain retry retains exact original version and body', async () => {
  const sent = []; let attempts = 0
  const controller = createAdminCommand(async value => { sent.push(value); if (++attempts === 1) throw new Error('network lost'); return receipt() })
  const command = sample()
  await assert.rejects(controller.execute(command))
  command.version = 9; command.body.accepted_revision_id = 'other'
  await assert.rejects(controller.execute(sample()), /上一操作/)
  assert.equal(controller.state, 'uncertain')
  await controller.execute()
  assert.deepEqual(sent[0], sent[1]); assert.equal(sent[1].version, 3)
  assert.equal(controller.state, 'success')
})
test('double click never sends a second command', async () => {
  let resolve, sends = 0
  const controller = createAdminCommand(() => { sends++; return new Promise(done => { resolve = done }) })
  const pending = controller.execute(sample())
  await assert.rejects(controller.execute(sample()), /正在提交/)
  resolve(receipt()); await pending; assert.equal(sends, 1)
})
test('known first validation failure releases draft but cannot erase previous uncertainty', async () => {
  const controller = createAdminCommand(async () => { throw { response: { status: 409 } } })
  await assert.rejects(controller.execute(sample())); assert.equal(controller.state, 'failed')
  let n = 0
  const uncertain = createAdminCommand(async () => { if (++n === 1) throw new Error('timeout'); throw { response: { status: 409 } } })
  await assert.rejects(uncertain.execute(sample())); await assert.rejects(uncertain.execute())
  assert.equal(uncertain.state, 'uncertain'); assert.deepEqual(uncertain.pending, sample())
})
test('invalid or unrelated receipt remains uncertain', async () => {
  for (const result of [{ current_state: 'invoice_created' }, { original_receipt: { request_id: 'other' }, current_state: 'submitted' }]) {
    const controller = createAdminCommand(async () => result)
    await assert.rejects(controller.execute(sample())); assert.equal(controller.state, 'uncertain')
  }
})
test('principal change discards late successful response', async () => {
  let resolve
  const controller = createAdminCommand(() => new Promise(done => { resolve = done }))
  const pending = controller.execute(sample()); controller.clear(); resolve(receipt())
  assert.equal(await pending, null); assert.equal(controller.state, 'idle'); assert.equal(controller.pending, null)
})
