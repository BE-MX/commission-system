import test from 'node:test'
import assert from 'node:assert/strict'
import { formatRosterAmount } from '../src/views/trade/rosterAmount.js'

test('roster amount retains exact cents at the DECIMAL(16, 2) limit', () => {
  assert.equal(formatRosterAmount('99999999999999.99'), '99,999,999,999,999.99')
  assert.equal(formatRosterAmount('99999999999999.98'), '99,999,999,999,999.98')
  assert.equal(formatRosterAmount('99999999999999.01'), '99,999,999,999,999.01')
  assert.equal(formatRosterAmount('90071992547409.93'), '90,071,992,547,409.93')
})

test('roster amount formats ordinary, zero, one-cent and leading-zero values', () => {
  for (const [input, output] of [
    ['1234.56', '1,234.56'], ['1000', '1,000.00'], ['12.5', '12.50'],
    ['0.00', '0.00'], ['0.01', '0.01'], ['0001234.50', '1,234.50'],
  ]) assert.equal(formatRosterAmount(input), output)
})

test('missing or malformed roster amounts do not masquerade as zero', () => {
  for (const input of [null, undefined, '', 'invalid', '-1.00', '1.234', '1e10']) {
    assert.equal(formatRosterAmount(input), '—')
  }
})
