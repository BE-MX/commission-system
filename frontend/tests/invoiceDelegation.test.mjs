import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { buildInvoicePayload, emptyInvoiceForm } from '../src/views/invoice/composables/invoiceEditorState.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const invoiceApi = read('../src/api/invoice.js')
const userApi = read('../src/api/userManagement.js')
const editor = read('../src/views/invoice/composables/useInvoiceEditor.js')
const invoiceView = read('../src/views/invoice/InvoiceManage.vue')
const userView = read('../src/views/system/UserManagement.vue')

test('invoice payload carries structured sales ownership', () => {
  const form = emptyInvoiceForm()
  form.sales_user_id = 42
  const payload = buildInvoicePayload(form, 0)
  assert.equal(payload.sales_user_id, 42)
})

test('invoice entry loads assignees and scopes private searches to selected salesperson', () => {
  assert.match(invoiceApi, /export function getInvoiceAssignees/)
  assert.match(editor, /getInvoiceAssignees/)
  assert.match(editor, /sales_user_id:\s*form\.sales_user_id/)
  assert.match(editor, /async function onSalesUserChange/)
  assert.match(editor, /onSalesUserChange\(\)[\s\S]*refreshLinePrice\(line\)[\s\S]*refreshAccessoryPrices\(\)/)
  assert.match(invoiceView, /订单归属业务员/)
  assert.match(invoiceView, /v-model="form\.sales_user_id"/)
  assert.match(invoiceView, /@change="onSalesUserChange"/)
  assert.match(invoiceView, /未绑定OKKI/)
  // 业务员信息压缩为只读资料条（From 姓名 · 电话 · 邮箱），不再占三个输入框
  assert.match(invoiceView, /class="fgrid-c3 sales-readout"/)
  assert.match(invoiceView, /\{\{ form\.sales_user_name \|\| '—' \}\}/)
  assert.match(invoiceView, /\{\{ form\.sales_phone \|\| '—' \}\}/)
  assert.match(invoiceView, /\{\{ form\.sales_email \|\| '—' \}\}/)
})

test('user management exposes and persists delegated salesperson grants', () => {
  assert.match(userApi, /export function getInvoiceDelegateGrants/)
  assert.match(userApi, /export function updateInvoiceDelegateGrants/)
  assert.match(userView, /可代创建订单/)
  assert.match(userView, /form\.invoice_delegate_sales_user_ids/)
  assert.match(userView, /getInvoiceDelegateGrants/)
  assert.match(userView, /updateInvoiceDelegateGrants/)
  assert.match(userView, /delegateLoadSeq/)
  assert.match(userView, /未配置部门/)
})
