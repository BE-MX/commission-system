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
  splitDiscountCents,
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
const summaryCard = readFileSync(
  new URL('../src/views/invoice/components/InvoiceSummaryCard.vue', import.meta.url),
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
  assert.match(settlementFields, /\.sgrid :deep\(\.el-input-number\)[^}]*width:\s*100%/s)
  // 预付款/包装数量/包装费用/运费/手续费/折扣（总折扣均分录入框）
  const numericControls = settlementFields.match(/<el-input-number\b/g) || []
  assert.equal(numericControls.length, 6)
})

test('settlement options use the approved fixed values', () => {
  // 3 个店铺信保各拆便捷发货/报关（8 项）+ 现金/支付宝/微信/对公转账（莱莎/旭和）（2026-09-23 增补）
  assert.deepEqual(PAYMENT_METHOD_OPTIONS, [
    'PayPal',
    '大莱莎信保（便捷发货）', '大莱莎信保（报关）',
    '小莱莎信保（便捷发货）', '小莱莎信保（报关）',
    '新莱莎信保（便捷发货）', '新莱莎信保（报关）',
    'TT',
    '现金', '支付宝', '微信', '对公转账（莱莎）', '对公转账（旭和）',
  ])
  assert.deepEqual(EXPRESS_CHANNEL_OPTIONS, ['DHL', 'FEDEX', '顺丰', '其他快递'])
  // 新增付款方式均无自动费率：手续费手填
  for (const method of ['现金', '支付宝', '微信', '对公转账（莱莎）', '对公转账（旭和）']) {
    assert.equal(handlingFeeRate(method), null)
  }
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

test('footer marks the handling fee as Ark-only', () => {
  assert.match(totalsFooter, /订单总金额/)
  assert.match(totalsFooter, /应付合计/)
  assert.match(totalsFooter, /仅方舟记录/)
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

test('settlement inputs live in the side pane; derived amounts moved to the summary card', () => {
  const sideStart = invoiceView.indexOf('<aside class="pane pane-side">')
  assert.ok(sideStart >= 0)
  const sidePane = invoiceView.slice(sideStart)
  assert.ok(sidePane.includes('<InvoiceSummaryCard'), 'summary card should sit in the side pane')
  assert.ok(sidePane.includes('<InvoiceSettlementFields'), 'settlement inputs should sit in the side pane')
  assert.ok(sidePane.includes('<InvoiceReceiptFields'), 'receipt card should sit in the side pane')
  assert.doesNotMatch(invoiceView, /<el-collapse[^>]*class="internal-collapse"/)
  assert.match(settlementFields, /<el-select v-model="form\.internal_payment_method"/)
  assert.match(settlementFields, /label="预付款"/)
  assert.match(settlementFields, /label="尾款"/)
  assert.match(settlementFields, /根据订单总额与预付款自动计算/)
  assert.match(settlementFields, /label="包装费用"/)
  assert.match(settlementFields, /label="手续费"/)
  // 快递渠道移到底部「物流与备注」卡：必填横向单选，不再出现在结算卡
  assert.doesNotMatch(settlementFields, /express_channel/)
  assert.match(invoiceView, /<el-radio-group v-model="form\.express_channel"/)
  // 总折扣录入框：默认=产品行折扣合计，手改后均分到产品行
  assert.match(settlementFields, /label="折扣"/)
  assert.match(settlementFields, /:model-value="totalDiscount"/)
  assert.match(settlementFields, /@change="onTotalDiscountChange"/)
  assert.match(invoiceView, /:total-discount="formHairDiscountAbs"/)
  assert.match(invoiceView, /:on-total-discount-change="applyTotalDiscount"/)
  // 只读推导金额不再伪装成输入框，集中展示在金额汇总卡
  assert.doesNotMatch(settlementFields, /label="头发金额"|label="头发折扣"|label="配件金额"|label="配件折扣"/)
  assert.match(summaryCard, /头发金额/)
  assert.match(summaryCard, /头发折扣/)
  assert.match(summaryCard, /配件金额/)
  assert.match(summaryCard, /配件折扣/)
  assert.match(invoiceView, /:hair-amount="formHairPrice"/)
  assert.doesNotMatch(invoiceView, /v-model="form\.internal_discount"/)
  assert.doesNotMatch(invoiceView, /label="[^"]+（(?:Hair Price|Discount|Packaging|Shipping Fee|Handling Fee)）"/)
})

test('order subsection only contains the approved fields', () => {
  const start = invoiceView.indexOf('<div class="subdiv">订单信息</div>')
  const end = invoiceView.indexOf('<InvoiceHairTable', start)
  const orderSection = invoiceView.slice(start, end)
  assert.match(orderSection, /label="订单号\/发票号"/)
  assert.match(orderSection, /label="下单日期"/)
  assert.match(orderSection, /label="币种"/)
  assert.match(orderSection, /label="小满标记"[^>]*required/)
  // 备注移到底部「物流与备注」卡
  assert.doesNotMatch(orderSection, /label="快递渠道"|label="运费"|label="附加费"|label="付款条款"|label="备注"/)
})

test('total discount splits evenly across lines with the remainder on the last line', () => {
  assert.deepEqual(splitDiscountCents(1000, 3), [333, 333, 334])
  assert.deepEqual(splitDiscountCents(500, 2), [250, 250])
  assert.deepEqual(splitDiscountCents(0, 3), [0, 0, 0])
  assert.deepEqual(splitDiscountCents(100, 0), [])
  // 负数输入按绝对值处理（折扣内部存负值，录入框用正数）
  assert.deepEqual(splitDiscountCents(-999, 2), [499, 500])
  assert.match(invoiceEditor, /function applyTotalDiscount/)
  assert.match(invoiceEditor, /没有可分摊折扣的产品行/)
})

test('product discount precedes TotalPrice and packaging quantity precedes its fee', () => {
  const discountIndex = hairTable.indexOf('<el-table-column label="折扣"')
  const totalPriceIndex = hairTable.indexOf('<el-table-column label="TotalPrice"')
  assert.ok(discountIndex >= 0 && discountIndex < totalPriceIndex)
  assert.match(hairTable, /v-model="row\.discount_amount"/)
  const packagingQuantityIndex = settlementFields.indexOf('label="包装数量"')
  const packagingFeeIndex = settlementFields.indexOf('label="包装费用"')
  assert.ok(packagingQuantityIndex >= 0 && packagingQuantityIndex < packagingFeeIndex)

  for (const label of ['头发金额', '头发折扣', '配件金额', '配件折扣', '包装费用', '运费', '手续费']) {
    assert.ok(summaryCard.includes(label), `${label} should appear in the summary card`)
  }
  assert.doesNotMatch(summaryCard, /Hair Price|Line Discount|Packaging|Shipping Fee|Handling Fee/)
  // 页脚只留合计口径：订单总金额 · 手续费 → 应付合计
  for (const label of ['订单总金额', '手续费', '应付合计']) {
    assert.ok(totalsFooter.includes(label), `${label} should stay in the footer`)
  }
})

test('new invoices take the salesperson snapshot from the selected assignee', () => {
  assert.match(invoiceEditor, /form\.sales_user_name = selected\.username \|\| ''/)
  assert.match(invoiceEditor, /form\.sales_user_id = me\?\.id \|\| salesUserOptions\.value\[0\]\?\.id/)
  assert.doesNotMatch(invoiceEditor, /form\.sales_user_name = me\.real_name/)
})
