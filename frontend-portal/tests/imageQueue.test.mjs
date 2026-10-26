import test from 'node:test'
import assert from 'node:assert/strict'
import { createImageQueue } from '../src/state/imageQueue.mjs'
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }

test('image jobs bound concurrency, prioritize the gallery and skip cancelled thumbnails', async () => {
  const queue = createImageQueue(2), gates = [deferred(), deferred()], order = []
  let active = 0, maximum = 0
  const job = (id, gate) => async () => {
    order.push(id); active++; maximum = Math.max(maximum, active)
    if (gate) await gate.promise
    active--; return id
  }
  const first = queue(job('first', gates[0])), second = queue(job('second', gates[1]))
  await Promise.resolve(); await Promise.resolve()
  const controller = new AbortController()
  const cancelled = queue(job('cancelled'), { signal: controller.signal })
  const thumb = queue(job('thumb')), full = queue(job('full'), { priority: 1 })
  controller.abort(); gates[0].resolve(); gates[1].resolve()
  await Promise.all([first, second, cancelled, thumb, full])
  assert.equal(maximum, 2)
  assert.deepEqual(order, ['first', 'second', 'full', 'thumb'])
})

test('failed image jobs release slots for later images', async () => {
  const queue = createImageQueue(1)
  const failed = queue(async () => { throw new Error('Unavailable') })
  const next = queue(async () => 'next')
  await assert.rejects(failed, /Unavailable/)
  assert.equal(await next, 'next')
})
