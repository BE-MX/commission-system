import test from 'node:test'
import assert from 'node:assert/strict'
import {
  fmt, formatBeijing, normalizeCode, sizeLabel, toMeasurementPayload, verdict,
} from '../src/views/color/swatch-library/swatchFormat.js'

test('color code normalisation matches backend uniqueness key', () => {
  assert.equal(normalizeCode(' #1c '), '#1C')
  assert.equal(normalizeCode('#8 / 60'), '#8/60')
  assert.equal(normalizeCode(null), '')
})

test('display helpers', () => {
  assert.equal(fmt(null), '—')
  assert.equal(fmt(0.123), '0.12')
  assert.equal(fmt(0.30125, 4), '0.3013')
  assert.equal(sizeLabel(18, 'inch'), '18″')
  assert.equal(sizeLabel(45, 'cm'), '45 cm')
})

test('verdict mirrors server rule', () => {
  assert.equal(verdict({ count: 0 }, 1.5), 'none')
  assert.equal(verdict({ count: 2, base_de: null }, 1.5), 'ok')
  assert.equal(verdict({ count: 2, base_de: 1.5 }, 1.5), 'ok')
  assert.equal(verdict({ count: 2, base_de: 1.51 }, 1.5), 'warn')
})

test('server naive Beijing time renders without client-zone shift', () => {
  assert.equal(formatBeijing('2026-10-28T07:30:00'), '10/28 07:30')
  assert.equal(formatBeijing('2026-10-28 00:05:12'), '10/28 00:05')
  assert.equal(formatBeijing(null), '—')
})

test('reading maps to measurement payload with offset-bearing ISO times', () => {
  const at = new Date(Date.UTC(2026, 9, 27, 23, 30))
  const p = toMeasurementPayload({
    lab: [20.6, -1.62, 2.41], luv: [1, 2, 3], lch: [4, 5, 6], yxy: [7, 0.3, 0.33],
    cmyk: [0, 5, 8, 84], rgb: [40, 35, 33], raw: 'AB44', source: 'simulation',
    deviceName: 'LS171', deviceSn: '2410803317', deviceFw: '1.52', sessionId: 's1',
    requestedAt: at, receivedAt: at,
  }, { receiptStatus: 'late' })
  assert.ok(p.client_request_id && p.client_request_id.length <= 64)
  assert.equal(p.receipt_status, 'late')
  assert.equal(p.source, 'simulation')
  assert.deepEqual(p.lab, [20.6, -1.62, 2.41])
  assert.equal(p.requested_at, '2026-10-27T23:30:00.000Z')
  assert.equal(p.device_sn, '2410803317')
  assert.notEqual(toMeasurementPayload({ lab: [1, 2, 3] }).client_request_id, p.client_request_id)
})
