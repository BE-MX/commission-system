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

test('invoice line tables show prices with two decimals while keeping stored precision', () => {
  // 只改显示：后端与 OKKI 仍按四位成交价计算（导入价如 30.048），界面统一两位（2026-10-12）
  const hairTable = readFileSync(new URL('../src/views/invoice/components/InvoiceHairTable.vue', import.meta.url), 'utf8')
  const accessoryTable = readFileSync(new URL('../src/views/invoice/components/InvoiceAccessoryTable.vue', import.meta.url), 'utf8')
  for (const source of [hairTable, accessoryTable]) {
    assert.doesNotMatch(source, /money4/)
    assert.doesNotMatch(source, /:precision="4"/)
    assert.match(source, /money\(row\.standard_price\)/)
  }
  assert.match(hairTable, /v-model="row\.price_per_piece" :min="0" :precision="2"/)
  assert.match(accessoryTable, /v-model="row\.price_per_piece"[\s\S]*?:precision="2"/)
  assert.match(accessoryTable, /money\(row\.customer_price\)/)
})
