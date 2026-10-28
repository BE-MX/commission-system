import test from 'node:test'
import assert from 'node:assert/strict'
import { describeShift, signed } from '../src/views/color/swatch-library/batchCompare.js'
import { toMeasurementPayload } from '../src/views/color/swatch-library/swatchFormat.js'

test('shift labels mirror backend describe_shift (darker / redder / bluer)', () => {
  assert.deepEqual(describeShift([38, 4, 9], [40.2, 2.1, 10.1]), ['偏黑缺白', '偏红缺绿', '偏蓝缺黄'])
  assert.deepEqual(describeShift([41, 0, 12], [40, 1, 10]), ['偏白缺黑', '偏绿缺红', '偏黄缺蓝'])
})

test('differences below the threshold are not labelled', () => {
  assert.deepEqual(describeShift([40.1, 2.2, 10.0], [40.2, 2.1, 10.1]), [null, null, null])
  assert.equal(describeShift(null, [1, 2, 3]), null)
})

test('signed delta formatting', () => {
  assert.equal(signed(0.4211), '+0.42')
  assert.equal(signed(-1.5), '-1.50')
  assert.equal(signed(null), '—')
})

test('payload carries record type and position tag', () => {
  const p = toMeasurementPayload({ lab: [1, 2, 3] }, { recordType: 'batch', positionTag: 'head' })
  assert.equal(p.record_type, 'batch')
  assert.equal(p.position_tag, 'head')
  const d = toMeasurementPayload({ lab: [1, 2, 3] })
  assert.equal(d.record_type, 'standard')
  assert.equal(d.position_tag, null)
})
