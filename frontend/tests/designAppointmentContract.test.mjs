import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  formatCustomerOptionLabel,
  normalizeCustomerId,
} from '../src/views/design/appointmentContract.js'

const customerPickerSource = readFileSync(
  new URL('../src/components/design/CustomerInfoPicker.vue', import.meta.url),
  'utf8',
)
const customerOptionSource = customerPickerSource.match(/<el-option[\s\S]*?\/>/)?.[0] || ''

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

test('customer option labels show company and country without ids', () => {
  assert.equal(
    formatCustomerOptionLabel({ id: 'c1', name: 'Alpha Hair', country: 'US' }),
    'Alpha Hair · US',
  )
  assert.equal(
    formatCustomerOptionLabel({ id: 'c1', name: 'Alpha Hair', country: '' }),
    'Alpha Hair · 未知国家',
  )
})

test('customer option labels identify customers with missing names', () => {
  assert.equal(
    formatCustomerOptionLabel({ id: 'c1', name: null, country: 'CN' }),
    '未知客户 · CN',
  )
  assert.equal(
    formatCustomerOptionLabel({ id: 'c1', name: '   ', country: '' }),
    '未知客户 · 未知国家',
  )
})

test('customer picker copy searches by customer or contact name and exposes no ids', () => {
  assert.match(customerPickerSource, /placeholder="输入客户名称或联系人名称搜索"/)
  assert.match(customerOptionSource, /:label="formatCustomerOptionLabel\(item\)"/)
  assert.doesNotMatch(customerOptionSource, /:label="[^"]*item\.id[^"]*"/)
  assert.doesNotMatch(customerPickerSource, /客户ID/)
  assert.doesNotMatch(customerPickerSource, /客户 ID/)
  assert.doesNotMatch(customerPickerSource, /ID \$\{item\.id\}/)
})
