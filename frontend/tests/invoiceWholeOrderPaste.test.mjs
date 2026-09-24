import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  parseWholeOrderClipboard,
  resolveExpressChannel,
  resolvePaymentMethod,
} from '../src/views/invoice/composables/useInvoiceWholeOrderPaste.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const invoiceView = read('../src/views/invoice/InvoiceManage.vue')
const editor = read('../src/views/invoice/composables/useInvoiceEditor.js')

// 复刻附件《刘源发票+Stephanie Powers + 9.22.xlsx》C6:I23 的剪贴板形态：
// 全角冒号、Paymetn 误拼、packages 行多列数字、带引号的多行地址单元格
const SAMPLE = [
  '\tTo：\tStephanie Powers\t\t\tFrom：\tStella\t',
  '\tTEL/Fax：\t1 5592307249\t\t\tTEL：\t86185 6271 7765\t',
  '\tE-mail：\tStephanie.herron724@gmail.com\t\t\tE-mail：\tstella@leshinehair.com\t',
  '\t"Delivery \n   address："\t"11654 N Bella Verde Ave, Fresno, CA 93730\nUSA"\t\t\tDate：\t2026/9/23\t',
  '\t产品名称\tProduct\tLength\tColor\tWeight\tQuantity\tUnit Price\tTotal Price                ',
  '\tSuper Double Drawn Genius Weft/24/#5ATP5A/1006/20g\tSuper Double Drawn Genius Weft\t24\t#5ATP5A/1006\t20g\t6\t45.55\t273.3',
  '\thair price\t\t\t\t6\t\t273.3',
  '\t10% Discount\t\t\t\t\t\t-27.33',
  '\tFinal Price\t\t\t\t\t\t245.97',
  '\tpackages\t\t\t\t500\t1\t0',
  '\tshipping fee\t\t\t\t\t\t40.16',
  '\tTotal\t全款100%\t\t\t\t\t286.13',
  '\thandling fee\tPayPal\t\t\t\t\t14.31',
  '\tPaymetn term\t联邦普货',
  '\t\t\t头发提成\t4.9194',
].join('\n')

test('whole-order clipboard parses header fields with quoted multiline address', () => {
  const parsed = parseWholeOrderClipboard(SAMPLE)
  assert.equal(parsed.customer_name, 'Stephanie Powers')
  assert.equal(parsed.contact_phone, '1 5592307249')
  assert.equal(parsed.contact_email, 'Stephanie.herron724@gmail.com')
  assert.match(parsed.delivery_address, /11654 N Bella Verde Ave/)
  assert.match(parsed.delivery_address, /\nUSA$/)
})

test('fee rows follow the keyword rules: discount-without-after, package, shipping, handling', () => {
  const parsed = parseWholeOrderClipboard(SAMPLE)
  // 10% Discount（不含 after）→ 折扣总价取绝对值
  assert.equal(parsed.discount_total, 27.33)
  // packages 行取最后一个数值（I 列总额 0，而不是数量 500/1）
  assert.equal(parsed.packaging_fee, 0)
  assert.equal(parsed.shipping_fee, 40.16)
  assert.equal(parsed.handling_fee, 14.31)
  // hair/tool/total/final 行忽略
  assert.ok(parsed.ignored_rows >= 3)
})

test('payment candidates resolve to payment method and express channel', () => {
  const parsed = parseWholeOrderClipboard(SAMPLE)
  // handling 行 D 列 PayPal → 付款方式；Paymetn term 行 D 列联邦普货 → 快递渠道
  assert.equal(parsed.payment_method, 'PayPal')
  assert.equal(parsed.express_channel, 'FEDEX')
})

test('discount label containing after is not extracted', () => {
  const parsed = parseWholeOrderClipboard('\t10% Discount After Tax\t\t\t\t\t\t-27.33')
  assert.equal(parsed.discount_total, null)
})

test('payment and express resolvers cover aliases and exact options', () => {
  assert.equal(resolvePaymentMethod('paypal'), 'PayPal')
  assert.equal(resolvePaymentMethod('tt'), 'TT')
  assert.equal(resolvePaymentMethod('T/T'), 'TT')
  assert.equal(resolvePaymentMethod('支付宝'), '支付宝')
  assert.equal(resolvePaymentMethod('微信'), '微信')
  assert.equal(resolvePaymentMethod('大莱莎信保（便捷发货）'), '大莱莎信保（便捷发货）')
  assert.equal(resolvePaymentMethod('新莱莎信保 报关'), '新莱莎信保（报关）')
  assert.equal(resolvePaymentMethod('对公转账（莱莎）'), '对公转账（莱莎）')
  assert.equal(resolvePaymentMethod('联邦普货'), null)
  assert.equal(resolveExpressChannel('联邦普货'), 'FEDEX')
  assert.equal(resolveExpressChannel('dhl'), 'DHL')
  assert.equal(resolveExpressChannel('顺丰'), '顺丰')
  assert.equal(resolveExpressChannel('PayPal'), null)
})

test('empty paste is rejected with a clear error', () => {
  assert.throws(() => parseWholeOrderClipboard('   '), /请先粘贴 Excel 整单内容/)
})

test('product rows are parsed with the shared column mapping', () => {
  const parsed = parseWholeOrderClipboard(SAMPLE)
  assert.equal(parsed.product_rows.length, 1)
  const row = parsed.product_rows[0]
  assert.equal(row.product, 'Super Double Drawn Genius Weft')
  assert.equal(row.length, '24')
  assert.equal(row.color, '#5ATP5A/1006')
  assert.equal(row.weight, '20g')
  assert.equal(row.quantity, '6')
  assert.equal(row.unit_price, '45.55')
})

test('fee rows below the product section are not mistaken for products', () => {
  const parsed = parseWholeOrderClipboard(SAMPLE)
  // hair price/packages/shipping/handling 等行有效列少，不会进入产品行
  assert.ok(!parsed.product_rows.some(row => /hair|packages|shipping|handling|total/i.test(row.product)))
})

test('whole-order dialog validates product rows through the existing backend preview', () => {
  const dialog = read('../src/views/invoice/components/InvoiceWholeOrderPaste.vue')
  assert.match(dialog, /previewInvoiceImport\(\{[\s\S]*?rows: parsed\.value\.product_rows/)
  // 先用匹配到的客户跑产品校验，客户价/规则才正确
  assert.match(dialog, /customerMatch\.value\.option\.company_id/)
  // 存在待处理行时不允许应用
  assert.match(dialog, /:disabled="hasBlockedRows"/)
  assert.match(dialog, /fingerprint: productPreview\.value\.batch_fingerprint/)
})

test('editor appends product rows before distributing the discount', () => {
  const applyFn = editor.slice(editor.indexOf('async function applyWholeOrderPaste'))
  assert.ok(applyFn.indexOf('appendImportedLines') < applyFn.indexOf('applyTotalDiscount(parsed.discount_total)'))
  assert.match(applyFn, /产品明细 \$\{parsed\.productPreview\.rows\.length\} 行/)
})

test('standalone product paste entry shows only in the legacy drawer', () => {
  const hairTable = read('../src/views/invoice/components/InvoiceHairTable.vue')
  const legacyDrawer = read('../src/views/invoice/components/legacy/InvoiceLegacyDrawer.vue')
  // 按钮保留在组件里，但由 showPasteEntry 门控：新版不传 = 不显示，旧版传 = 显示
  assert.match(hairTable, /v-if="showPasteEntry"/)
  assert.match(hairTable, /showPasteEntry: Boolean/)
  assert.match(legacyDrawer, /show-paste-entry/)
  assert.match(legacyDrawer, /@paste="\$emit\('open-legacy-paste'\)"/)
  assert.match(invoiceView, /@open-legacy-paste="pasteImportVisible = true"/)
  // 新版抽屉的明细表不带该 prop
  const newDrawerTable = invoiceView.slice(invoiceView.indexOf('<InvoiceHairTable'), invoiceView.indexOf('<InvoiceAccessoryTable'))
  assert.doesNotMatch(newDrawerTable, /show-paste-entry/)
  assert.match(invoiceView, /整单粘贴/)
})

test('whole-order paste is wired into the drawer and applies in a safe order', () => {
  // 入口按钮 + 对话框挂载
  assert.match(invoiceView, /整单粘贴/)
  assert.match(invoiceView, /<InvoiceWholeOrderPaste/)
  assert.match(invoiceView, /:match-customer="matchWholeOrderCustomer"/)
  assert.match(invoiceView, /@apply="applyWholeOrderPaste"/)
  // 编辑器：唯一公司级匹配才自动选用
  assert.match(editor, /option\.kind !== 'contact'/)
  // 应用顺序：先付款方式（触发费率重算），后手续费（标记手改防覆盖）
  const applyFn = editor.slice(editor.indexOf('async function applyWholeOrderPaste'))
  assert.ok(applyFn.indexOf('internal_payment_method') < applyFn.indexOf('surcharge_amount'))
  assert.match(applyFn, /markHandlingFeeTouched\(\)/)
  // 无产品行时折扣不分摊，转为人工提示
  assert.match(applyFn, /暂无产品行可分摊/)
})
