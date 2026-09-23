import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { buildOutboundDoc } from '../src/views/shipping/print/printDocs.js'
import { buildInvoicePayload, emptyInvoiceForm, normalizeHairRow } from '../src/views/invoice/composables/invoiceEditorState.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const api = read('../src/api/invoice.js')
const editor = read('../src/views/invoice/composables/useInvoiceEditor.js')
const hairItems = read('../src/views/invoice/composables/useInvoiceHairItems.js')
const invoiceView = read('../src/views/invoice/InvoiceManage.vue')
const hairTable = read('../src/views/invoice/components/InvoiceHairTable.vue')

test('merchandiser select loads role-based options and posts only the id', () => {
  assert.match(api, /export function getInvoiceMerchandisers\(\)/)
  assert.match(api, /\/invoices\/merchandiser-options/)
  assert.match(editor, /async function loadMerchandisers/)
  assert.match(editor, /merchandiserOptions\.value = res\.items \|\| \[\]/)
  assert.match(invoiceView, /label="指定跟单员"/)
  assert.match(invoiceView, /v-model="form\.merchandiser_id"/)
  const form = { ...emptyInvoiceForm(), merchandiser_id: 42 }
  assert.equal(buildInvoicePayload(form, 0).merchandiser_id, 42)
  // 姓名快照由服务端回填，载荷不携带客户端文本
  assert.equal(buildInvoicePayload({ ...form, merchandiser_name: '伪造' }, 0).merchandiser_name, undefined)
})

test('previous invoice number reminder loads per salesperson and order type', () => {
  assert.match(api, /export function getPreviousInvoiceNo/)
  assert.match(api, /\/invoices\/previous-no/)
  assert.match(editor, /async function refreshPreviousInvoiceNo/)
  assert.match(editor, /sales_user_id: form\.sales_user_id,[\s\S]*?order_type: form\.order_type/)
  assert.match(editor, /exclude_id: form\.id \|\| undefined/)
  assert.match(invoiceView, /class="prev-order-tip"/)
  assert.match(invoiceView, /\{\{ previousInvoiceNo \}\}/)
})

test('hair line carries available stock from the matched product instead of showing SKU', () => {
  const row = normalizeHairRow({ sku_id: 7, available_stock: '123.5' })
  assert.equal(row.available_stock, 123.5)
  assert.equal(normalizeHairRow({}).available_stock, null)
  // Product 列：SKU 标签取消，改为库存（可用库存数量）
  assert.doesNotMatch(hairTable, /SKU \{\{ row\.sku_id \}\}/)
  assert.match(hairTable, /库存 \{\{ row\.available_stock == null \? '—' : Math\.round\(row\.available_stock\) \}\}/)
  assert.match(hairItems, /available_stock: result\.item\.available_stock/)
})

test('spec columns collapse and expand via the header toggle', () => {
  assert.match(hairTable, /collapseSpecs = ref\(false\)/)
  assert.match(hairTable, /收起规格列/)
  assert.match(hairTable, /展开规格列/)
  for (const label of ['Model', 'Color', 'Length', 'Net Weight']) {
    assert.match(hairTable, new RegExp(`v-if="[^"]*!collapseSpecs[^"]*" label="${label}"`))
  }
})

test('outbound print shows merchandiser after owner and express channel above remark', () => {
  const doc = buildOutboundDoc({
    record: {
      outbound_no: 'CK20260923-001', outbound_date: '2026-09-23', customer_name: '测试客户',
      owner_name: '张三', merchandiser_name: '李四', express_channel: '顺丰',
      customer_grade: 'A', order_amount_text: 'USD 1.00', remark: '备注内容',
    },
    items: [{ product_name: '发片/16寸', spec: 'B1', qty: 1 }],
  })
  // 负责人之后是跟单员行；未指定时单元格为空
  assert.ok(doc.indexOf('负责人') < doc.indexOf('跟单员'))
  assert.match(doc, /<tr><td>跟单员<\/td><td colspan="3">李四<\/td><\/tr>/)
  const blank = buildOutboundDoc({
    record: { outbound_no: 'X', owner_name: '张三', merchandiser_name: null, express_channel: null },
    items: [],
  })
  assert.match(blank, /<tr><td>跟单员<\/td><td colspan="3"><\/td><\/tr>/)
  assert.match(blank, /快递渠道：—/)
  // 快递渠道位于发货备注框上方
  assert.ok(doc.indexOf('快递渠道：顺丰') > -1 && doc.indexOf('快递渠道：顺丰') < doc.indexOf('发货备注'))
})
