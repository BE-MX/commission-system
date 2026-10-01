import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { formatMoney } from '../src/utils/money.js'

const priceConfig = readFileSync(
  new URL('../src/views/invoice/InvoicePriceConfig.vue', import.meta.url),
  'utf8',
)

test('standard prices display and edit with two decimal places', () => {
  assert.match(priceConfig, /formatMoney\(row\.price\)/)
  assert.equal(formatMoney(1234.567), '1,234.57')
  assert.match(priceConfig, /v-model="stdDialog\.form\.price"[^>]*:precision="2"/s)
  assert.doesNotMatch(priceConfig, /Number\(row\.price\)\.toFixed\(4\)/)
  assert.match(priceConfig, /导入完成：标准价格.*已按两位小数四舍五入/)
})
