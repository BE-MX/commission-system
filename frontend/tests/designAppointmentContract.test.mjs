import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeCustomerId } from '../src/views/design/appointmentContract.js'

test('customer ids stay strings across picker and submit boundaries', () => {
  assert.equal(normalizeCustomerId(14427527374439), '14427527374439')
  assert.equal(normalizeCustomerId(' 14427527374439 '), '14427527374439')
})

test('missing and structured customer values do not become accidental ids', () => {
  assert.equal(normalizeCustomerId(null), '')
  assert.equal(normalizeCustomerId(undefined), '')
  assert.equal(normalizeCustomerId({ id: '14427527374439' }), '')
  assert.equal(normalizeCustomerId(Number.MAX_SAFE_INTEGER + 1), '')
  assert.equal(normalizeCustomerId(Number.NaN), '')
})
