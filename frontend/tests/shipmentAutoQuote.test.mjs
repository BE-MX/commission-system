import test from 'node:test'
import assert from 'node:assert/strict'
import { createShipmentQuoteScheduler } from '../src/views/invoice/composables/shipmentAutoQuote.js'

test('rapid edits coalesce and the next quote waits for the current one', async () => {
  let input = 1, release
  const calls = []
  const scheduler = createShipmentQuoteScheduler(async () => {
    calls.push(input)
    if (calls.length === 1) await new Promise(resolve => { release = resolve })
  }, 5)
  const first = scheduler.flush()
  input = 2
  scheduler.schedule()
  input = 3
  scheduler.schedule()
  await new Promise(resolve => setTimeout(resolve, 20))
  assert.deepEqual(calls, [1])
  release()
  await first
  assert.deepEqual(calls, [1, 3])
  scheduler.dispose()
})

test('disposing prevents a queued quote after closing the dialog', async () => {
  let calls = 0
  const scheduler = createShipmentQuoteScheduler(async () => { calls++ }, 5)
  scheduler.schedule()
  scheduler.dispose()
  await new Promise(resolve => setTimeout(resolve, 20))
  await scheduler.flush()
  assert.equal(calls, 0)
})
