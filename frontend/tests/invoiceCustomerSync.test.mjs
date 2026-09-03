import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const invoiceView = readFileSync(
  new URL('../src/views/invoice/InvoiceManage.vue', import.meta.url),
  'utf8',
)
const syncEntry = readFileSync(
  new URL('../src/views/invoice/components/InvoiceCustomerSyncEntry.vue', import.meta.url),
  'utf8',
)
const syncComposable = readFileSync(
  new URL('../src/views/invoice/composables/useInvoiceCustomerSync.js', import.meta.url),
  'utf8',
)
const editor = readFileSync(
  new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url),
  'utf8',
)
const api = readFileSync(
  new URL('../src/api/invoice.js', import.meta.url),
  'utf8',
)

test('customer selector offers a manual OKKI sync entry next to it', () => {
  // 客户选择框旁（同一 form-item 内）挂同步入口组件
  assert.match(invoiceView, /<InvoiceCustomerSyncEntry :on-select="selectSyncedCustomer" \/>/)
  assert.match(syncEntry, /搜索不到客户？点击这里同步最新客户信息/)
})

test('sync dialog collects company name and shows the sync result', () => {
  assert.match(syncComposable, /syncInvoiceCustomerFromOkki\(\{ company_name: name \}\)/)
  assert.match(syncEntry, /placeholder="客户公司名称（Company Name）"/)
  assert.match(syncEntry, /result\.message/)
  assert.match(syncEntry, /result\.owner_names/)
  // 同步成功展示负责人/公海，便于用户判断能否选用
  assert.match(syncEntry, /公海（暂无负责人）/)
})

test('selecting a synced customer re-passes the current private-sea filter', () => {
  // 选用必须重新走带私海筛选的搜索，找不到就明确提示，不静默绕过归属限制
  assert.match(editor, /async function selectSyncedCustomer\(res\)/)
  assert.match(editor, /await searchCustomers\(res\.company_name\)/)
  assert.match(editor, /不在当前私海范围内/)
})

test('api client posts company name to the sync endpoint', () => {
  assert.match(api, /export function syncInvoiceCustomerFromOkki\(data\)/)
  assert.match(api, /request\.post\('\/customers\/sync-from-okki', data/)
})
