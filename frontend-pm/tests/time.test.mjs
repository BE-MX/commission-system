import test from 'node:test'
import assert from 'node:assert/strict'

import { fmtTime } from '../src/utils/labels.js'

test('PM business timestamps and explicit UTC timestamps display in Beijing time', () => {
  assert.equal(fmtTime('2026-08-26T12:34:00'), '2026-08-26 12:34')
  assert.equal(fmtTime('2026-08-26T12:34:00Z'), '2026-08-26 20:34')
  assert.equal(fmtTime('2026-08-26T12:34:00-05:00'), '2026-08-27 01:34')
  assert.equal(fmtTime('2026-08-26T12:34:00Z', false), '2026-08-26')
})
