import test from 'node:test'
import assert from 'node:assert/strict'

import { formatInvoiceDateTime } from '../src/views/invoice/composables/invoiceDateTime.js'

test('invoice timestamps always display in Asia/Shanghai', () => {
  assert.equal(formatInvoiceDateTime('2026-08-12T03:15:00Z'), '2026-08-12 11:15')
  assert.equal(formatInvoiceDateTime('2026-08-12T11:15:00+08:00'), '2026-08-12 11:15')
})

test('invoice timestamp formatter handles empty and invalid values', () => {
  assert.equal(formatInvoiceDateTime(null), '-')
  assert.equal(formatInvoiceDateTime('invalid'), '-')
})
