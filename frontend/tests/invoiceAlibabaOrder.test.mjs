import test from 'node:test'
import assert from 'node:assert/strict'
import { alibabaOrderError, alibabaOrderRequired } from '../src/views/invoice/composables/invoiceSettlement.js'
import { emptyInvoiceForm, buildInvoicePayload } from '../src/views/invoice/composables/invoiceEditorState.js'

const convenient = '新莱莎信保（便捷发货）'
test('every save with convenient shipping requires an Alibaba order number', () => {
  const form = { ...emptyInvoiceForm(), internal_payment_method: convenient }
  assert.ok(alibabaOrderError(form))
  form.id = 1
  form.alibaba_order_no = '  '
  assert.equal(alibabaOrderRequired(form), true)
  assert.match(alibabaOrderError(form), /必.*填.*阿里信保订单号/)
  form.alibaba_order_no = ' 00123 456789012345 '
  assert.equal(alibabaOrderError(form), '')
  assert.equal(buildInvoicePayload(form, 0).alibaba_order_no, '00123456789012345')
  form.alibaba_order_no = '１２３４５６７８９０１２３４５'
  assert.ok(alibabaOrderError(form))
  form.internal_payment_method = 'PayPal'
  assert.equal(buildInvoicePayload(form, 0).alibaba_order_no, null)
  form.alibaba_order_no = ''
  assert.equal(alibabaOrderError(form), '')
})
