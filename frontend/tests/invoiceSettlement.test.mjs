import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  EXPRESS_CHANNEL_OPTIONS,
  PAYMENT_METHOD_OPTIONS,
  calculateBalance,
  calculateInvoiceTotal,
  calculateLineTotal,
  normalizeDiscount,
  settlementMatchesTotal,
} from '../src/views/invoice/composables/invoiceSettlement.js'

const invoiceView = readFileSync(
  new URL('../src/views/invoice/InvoiceManage.vue', import.meta.url),
  'utf8',
)
const invoiceEditor = readFileSync(
  new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url),
  'utf8',
)
const settlementFields = readFileSync(
  new URL('../src/views/invoice/components/InvoiceSettlementFields.vue', import.meta.url),
  'utf8',
)
const hairTable = readFileSync(
  new URL('../src/views/invoice/components/InvoiceHairTable.vue', import.meta.url),
  'utf8',
)
const totalsFooter = readFileSync(
  new URL('../src/views/invoice/components/InvoiceTotalsFooter.vue', import.meta.url),
  'utf8',
)

test('settlement options use the approved fixed values', () => {
  assert.deepEqual(PAYMENT_METHOD_OPTIONS, ['PayPal', '大莱莎信保', '小莱莎信保', '新莱莎信保', 'TT'])
  assert.deepEqual(EXPRESS_CHANNEL_OPTIONS, ['DHL', 'FEDEX', '其他'])
})

test('line discounts are negative and invoice totals do not subtract them twice', () => {
  assert.equal(normalizeDiscount(5), -5)
  assert.equal(normalizeDiscount(-5), -5)
  assert.equal(normalizeDiscount(0), 0)
  assert.equal(calculateLineTotal(2, 10, 5), 15)
  assert.equal(calculateInvoiceTotal(90, 3, 7, 2), 102)
})

test('balance is derived from the grand total with currency rounding', () => {
  assert.equal(calculateBalance(100, 30), 70)
  assert.equal(calculateBalance(100, 0), 100)
  assert.equal(calculateBalance(10.01, 0.02), 9.99)
  assert.equal(calculateBalance(100, null), null)
})

test('settlement validation rejects missing, excessive, and mismatched amounts', () => {
  assert.equal(settlementMatchesTotal(100, null, null), true)
  assert.equal(settlementMatchesTotal(100, 30, 70), true)
  assert.equal(settlementMatchesTotal(100, 30, 60), false)
  assert.equal(settlementMatchesTotal(100, 110, -10), false)
  assert.equal(settlementMatchesTotal(100, 30, null), false)
})

test('fee settlement is always visible before product details and exposes derived balance', () => {
  const settlementIndex = invoiceView.indexOf('<InvoiceSettlementFields')
  const productIndex = invoiceView.indexOf('<InvoiceHairTable')
  assert.ok(settlementIndex >= 0 && settlementIndex < productIndex)
  assert.doesNotMatch(invoiceView, /<el-collapse[^>]*class="internal-collapse"/)
  assert.match(settlementFields, /<el-select v-model="form\.internal_payment_method"/)
  assert.match(settlementFields, /<el-select v-model="form\.express_channel"/)
  assert.match(settlementFields, /label="预付款"/)
  assert.match(settlementFields, /label="尾款"/)
  assert.match(settlementFields, /根据订单总额与预付款自动计算/)
  assert.match(settlementFields, /label="头发金额"[\s\S]*readonly[\s\S]*Hair Price/)
  assert.match(settlementFields, /label="头发折扣"/)
  assert.match(settlementFields, /label="配件金额"/)
  assert.match(settlementFields, /label="配件折扣"/)
  assert.doesNotMatch(invoiceView, /v-model="form\.internal_discount"/)
  assert.match(settlementFields, /label="包装费用"/)
  assert.match(settlementFields, /label="手续费"/)
  assert.doesNotMatch(invoiceView, /label="[^\"]+（(?:Hair Price|Discount|Packaging|Shipping Fee|Handling Fee)）"/)
})

test('order section only contains the approved five fields', () => {
  const start = invoiceView.indexOf('<div class="col-title">订单信息</div>')
  const end = invoiceView.indexOf('<div class="col-title">费用与结算信息</div>')
  const orderSection = invoiceView.slice(start, end)
  assert.match(orderSection, /label="发票号"/)
  assert.match(orderSection, /label="日期"/)
  assert.match(orderSection, /label="币种"/)
  assert.match(orderSection, /label="小满标记"[^>]*required/)
  assert.match(orderSection, /label="备注"/)
  assert.doesNotMatch(orderSection, /label="快递渠道"|label="运费"|label="附加费"|label="付款条款"/)
})

test('product discount precedes TotalPrice and packaging quantity precedes its fee', () => {
  const discountIndex = hairTable.indexOf('<el-table-column label="折扣"')
  const totalPriceIndex = hairTable.indexOf('<el-table-column label="TotalPrice"')
  assert.ok(discountIndex >= 0 && discountIndex < totalPriceIndex)
  assert.match(hairTable, /v-model="row\.discount_amount"/)
  const packagingQuantityIndex = settlementFields.indexOf('label="包装数量"')
  const packagingFeeIndex = settlementFields.indexOf('label="包装费用"')
  assert.ok(packagingQuantityIndex >= 0 && packagingQuantityIndex < packagingFeeIndex)

  const footer = totalsFooter
  for (const label of ['头发金额', '头发折扣', '配件金额', '配件折扣', '包装费用', '运费', '手续费']) {
    assert.ok(footer.includes(label), `${label} should appear in the footer`)
  }
  assert.doesNotMatch(footer, /Hair Price|Line Discount|Packaging|Shipping Fee|Handling Fee/)
})

test('new invoices take the salesperson name from the login username', () => {
  assert.match(invoiceEditor, /form\.sales_user_name = me\.username \|\| ''/)
  assert.doesNotMatch(invoiceEditor, /form\.sales_user_name = me\.real_name/)
})
