import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const receiptFields = read('../src/views/receipt/ReceiptFields.vue')
const invoiceReceipt = read('../src/views/invoice/components/InvoiceReceiptFields.vue')
const receiptManage = read('../src/views/receipt/ReceiptManage.vue')

test('receipt form can hide the standalone payment-type select', () => {
  assert.match(receiptFields, /hidePaymentType/)
  assert.match(receiptFields, /v-if="!hidePaymentType" label="回款方式"/)
  assert.match(receiptFields, /if \(!props\.hidePaymentType\) loadTypes\(\)/)
})

test('invoice receipt draft defaults the xiaoman payment type to Other', () => {
  // 小满回款方式在其接口中非必填，且与内部付款方式口径不同：自动回款单统一按 Other 提交
  assert.match(invoiceReceipt, /payment_type: 'Other'/)
  assert.match(invoiceReceipt, /小满回款方式默认按 Other 提交/)
  assert.match(invoiceReceipt, /hide-payment-type/)
  // 不再跟随订单付款方式，两个字段完全解耦
  assert.doesNotMatch(invoiceReceipt, /internal_payment_method/)
})

test('receipt amount auto-follows the prepayment until manually edited', () => {
  // 回款金额根据预付款金额自动填充（2026-09-23）；手改后不再跟随；预售单定金除外（手填）
  assert.match(invoiceReceipt, /props\.form\.internal_received > 0 \? props\.form\.internal_received : null/)
  assert.match(invoiceReceipt, /watch\(\(\) => props\.form\.internal_received/)
  assert.match(invoiceReceipt, /draft\.amount === previous/)
  assert.match(invoiceReceipt, /props\.form\.order_type === 'presale' \? null/)
})

test('receipt management keeps the standalone xiaoman payment-type select', () => {
  assert.match(receiptManage, /<ReceiptFields/)
  assert.doesNotMatch(receiptManage, /hide-payment-type/)
})
