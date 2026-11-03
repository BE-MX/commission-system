import test from 'node:test'
import assert from 'node:assert/strict'
import { createLinkedSyncPolling } from '../src/views/invoice/composables/linkedSyncPolling.js'

function setup() {
  const state = { active: true, operation: { id: 'original', status: 'pending' } }
  const pending = new Map()
  let sequence = 0, reads = 0
  const polling = createLinkedSyncPolling(() => state, () => { reads++; state.refreshing = true }, {
    setTimeout(fn, delay) { assert.equal(delay, 3000); pending.set(++sequence, fn); return sequence },
    clearTimeout(id) { pending.delete(id) },
  })
  const tick = () => { for (const [id, fn] of [...pending]) { pending.delete(id); fn() } }
  polling.update()
  return { state, pending, polling, tick, reads: () => reads }
}

test('pending and running refresh without another write, with no overlapping read', () => {
  const c = setup()
  c.tick(); assert.equal(c.reads(), 1); assert.equal(c.pending.size, 0)
  c.tick(); assert.equal(c.reads(), 1)
  c.state.refreshing = false; c.state.operation.status = 'running'; c.polling.update()
  c.tick(); assert.equal(c.reads(), 2)
})

for (const status of ['done', 'manual', 'failed', 'uncertain']) {
  test(`${status} stops automatic refresh`, () => {
    const c = setup(); c.state.operation.status = status; c.polling.update()
    c.tick(); assert.equal(c.reads(), 0); assert.equal(c.pending.size, 0)
  })
}

test('hidden editor, active write and unmount cancel scheduled refresh', () => {
  const c = setup()
  c.state.active = false; c.polling.update(); c.tick(); assert.equal(c.reads(), 0)
  c.state.active = true; c.state.busy = true; c.polling.update(); c.tick(); assert.equal(c.reads(), 0)
  c.state.busy = false; c.polling.update(); assert.equal(c.pending.size, 1)
  c.polling.stop(); c.tick(); assert.equal(c.reads(), 0)
  c.polling.update(); assert.equal(c.pending.size, 0)
})
