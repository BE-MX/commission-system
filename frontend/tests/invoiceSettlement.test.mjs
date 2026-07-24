import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  EXPRESS_CHANNEL_OPTIONS,
  PAYMENT_METHOD_OPTIONS,
  PAYMENT_METHOD_RATES,
  calculateBalance,
  calculateInvoiceTotal,
  calculateLineTotal,
  computeHandlingFee,
  handlingFeeRate,
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

test('settlement and accessory numeric controls fill their bounded containers', () => {
  assert.match(settlementFields, /\.head-grid :deep\(\.el-input-number\)[^}]*width:\s*100%/s)
  const numericControls = settlementFields.match(/<el-input-number\b/g) || []
  assert.equal(numericControls.length, 5)
})

test('settlement options use the approved fixed values', () => {
  // 3 个店铺信保各拆便捷发货/报关，共 8 项
  assert.deepEqual(PAYMENT_METHOD_OPTIONS, [
    'PayPal',
    '大莱莎信保（便捷发货）', '大莱莎信保（报关）',
    '小莱莎信保（便捷发货）', '小莱莎信保（报关）',
    '新莱莎信保（便捷发货）', '新莱莎信保（报关）',
    'TT',
  ])
  assert.deepEqual(EXPRESS_CHANNEL_OPTIONS, ['DHL', 'FEDEX', '其他'])
})

test('handling fee rate: paypal 5%, 便捷发货 3%, TT 0, 报关/未选 manual', () => {
  assert.equal(handlingFeeRate('PayPal'), 0.05)
  assert.equal(handlingFeeRate('大莱莎信保（便捷发货）'), 0.03)
  assert.equal(handlingFeeRate('小莱莎信保（便捷发货）'), 0.03)
  assert.equal(handlingFeeRate('新莱莎信保（便捷发货）'), 0.03)
  assert.equal(handlingFeeRate('TT'), 0)
  // 报关与未选：null = 不自动算、手填
  assert.equal(handlingFeeRate('大莱莎信保（报关）'), null)
  assert.equal(handlingFeeRate(''), null)
  assert.equal(handlingFeeRate(undefined), null)
  // 每个便捷发货项都有费率、每个报关项都手填
  for (const method of PAYMENT_METHOD_OPTIONS) {
    if (method.includes('便捷发货')) assert.equal(PAYMENT_METHOD_RATES[method], 0.03)
    if (method.includes('报关')) assert.equal(method in PAYMENT_METHOD_RATES, false)
  }
})

test('computeHandlingFee = rate x base with currency rounding', () => {
  assert.equal(computeHandlingFee(0.05, 1000), 50)
  assert.equal(computeHandlingFee(0.03, 980), 29.4)
  assert.equal(computeHandlingFee(0, 1000), 0)
  // 分位四舍五入：0.05 * 333.33 = 16.6665 → 16.67
  assert.equal(computeHandlingFee(0.05, 333.33), 16.67)
})

test('order total (base) excludes the handling fee for auto-calc', () => {
  // 基数 = 产品+包装+运费（handling=0），不含手续费 → 破循环依赖
  assert.equal(calculateInvoiceTotal(900, 20, 80, 0), 1000)
  // 应付合计（结算/导出口径）仍含手续费
  assert.equal(calculateInvoiceTotal(900, 20, 80, 50), 1050)
})

test('editor wires payment-method auto-calc and base amount', () => {
  assert.match(invoiceEditor, /formBaseAmount/)
  assert.match(invoiceEditor, /handlingFeeRate/)
  assert.match(invoiceEditor, /handlingFeeTouched/)
  assert.match(invoiceEditor, /onPaymentMethodChange/)
  assert.match(settlementFields, /@change="onPaymentMethodChange"/)
  assert.match(settlementFields, /@change="onHandlingFeeInput"/)
})

test('switching to a manual/no-rate method clears the stale auto handling fee', () => {
  // P1-A：切到报关/清空付款方式时清掉别的方法公式留下的自动残值
  assert.match(invoiceEditor, /if \(rate == null\) \{\s*\n\s*\/\/[^\n]*\n\s*form\.surcharge_amount = 0/)
})

test('handling hint warns when the fee no longer matches the rate x base', () => {
  // P2-1：编辑单改产品/手改后手续费与费率不符时给重算引导
  assert.match(settlementFields, /重选付款方式可重算/)
  assert.match(settlementFields, /computeHandlingFee/)
})

test('footer separates order total (base) from the deducted handling fee', () => {
  assert.match(totalsFooter, /订单总金额/)
  assert.match(totalsFooter, /应付合计/)
  assert.match(totalsFooter, /OKKI 侧扣减/)
  assert.match(invoiceView, /:base-amount="formBaseAmount"/)
})

test('first-return shows the customer last order date reference', () => {
  assert.match(invoiceView, /lastOrderDate/)
  assert.match(invoiceView, /上次订单成交日期/)
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
