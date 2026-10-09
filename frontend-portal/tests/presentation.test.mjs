import test from 'node:test'
import assert from 'node:assert/strict'
import { unitPrice, beijingTime } from '../src/presentation.mjs'
import { browserChannel } from '../src/state/browserChannel.mjs'

test('price strings retain server precision, including values beyond binary fractional precision', () => {
  assert.equal(unitPrice('27.0000'), 'USD 27.00')
  assert.equal(unitPrice('35.2750'), 'USD 35.275')
  assert.equal(unitPrice('999999999999.9999'), 'USD 999,999,999,999.9999')
  assert.equal(unitPrice('0.0000'), 'USD 0.00')
  assert.equal(unitPrice(null), 'Price on request')
  assert.equal(unitPrice('bad'), 'Price on request')
})

test('storage-event fallback sends only a nonce, receives invalidation and removes listeners', () => {
  let handler, removed, payload
  const browser = { addEventListener: (type, value) => { assert.equal(type, 'storage'); handler = value },
    removeEventListener: (type, value) => { removed = value }, crypto: { randomUUID: () => 'nonce' },
    localStorage: { setItem: (key, value) => { payload = [key, value] } } }
  const channel = browserChannel(browser)
  channel.postMessage({ secret: 'never propagated' })
  assert.deepEqual(payload, ['leshine.portal.session-change', 'nonce'])
  let received
  channel.addEventListener('message', value => { received = value })
  handler({ key: 'other', newValue: 'anything' })
  assert.equal(received, undefined)
  handler({ key: payload[0], newValue: payload[1] })
  assert.deepEqual(received, { data: { type: 'portal-session-changed' } })
  channel.close()
  assert.strictEqual(removed, handler)
})

test('denied channel and storage access reports degraded capability without interrupting logout', () => {
  let unavailable = 0
  const browser = { BroadcastChannel: class { constructor() { throw new Error('denied') } },
    addEventListener() {}, removeEventListener() {}, crypto: { randomUUID: () => 'nonce' },
    localStorage: { setItem() { throw new Error('denied') } } }
  const channel = browserChannel(browser, () => { unavailable++ })
  channel.postMessage({ type: 'portal-session-changed' })
  assert.equal(unavailable, 1)
})

test('Beijing midnight display is independent of client zone and does not add eight hours twice', () => {
  const previousZone = process.env.TZ
  try {
    for (const zone of ['UTC', 'America/Los_Angeles', 'Asia/Shanghai']) {
      process.env.TZ = zone
      for (const source of ['2026-10-05T23:59:59', '2026-10-05T23:59:59+08:00', '2026-10-05T15:59:59Z', '2026-10-05T08:59:59-07:00']) {
        assert.equal(beijingTime(source), '05 Oct 2026, 23:59 (Beijing)', `${zone}: ${source}`)
      }
      for (const source of ['2026-10-06T00:00:01', '2026-10-06T00:00:01+08:00', '2026-10-05T16:00:01Z', '2026-10-05T09:00:01-07:00']) {
        assert.equal(beijingTime(source), '06 Oct 2026, 00:00 (Beijing)', `${zone}: ${source}`)
      }
    }
    assert.equal(beijingTime(null), 'unavailable')
    assert.equal(beijingTime('invalid-date'), 'unavailable')
  } finally {
    if (previousZone === undefined) delete process.env.TZ
    else process.env.TZ = previousZone
  }
})
