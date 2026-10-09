import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const id = '12345678-1234-1234-1234-123456789abc', revision = '12345678-1234-1234-1234-123456789def'
const errors = [], sent = []
async function run(mode) {
  const context = await browser.newContext({ viewport: { width: mode === 'propose' ? 390 : 1440, height: 950 } })
  const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message))
  await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-pi-test'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
  const doc = { commercial_header: { invoice_no: 'PI-QA-001', customer_name: 'Current PI Buyer', invoice_date: '2026-10-03', express_channel: 'DHL', contact_email: 'qa@example.test', sales_user_name: 'QA salesperson', sales_phone: '123456', sales_email: 'sales@example.test', packaging_quantity: '2' }, currency: 'USD', product_amount: '100.00', total_amount: '125.00', fees: { shipping_amount: '25.00', packaging_amount: '0.00', surcharge_amount: '0.00' }, payment_terms_snapshot: { display_text: '100% prepaid' }, delivery: { contact_name: 'QA Recipient', phone: '123456', formatted_address: 'QA complete delivery address\nSynthetic City' }, remark: 'PI test note', items: [{ line_key: 'line1', product_id: '101', sku_id: '201', display_snapshot: { model_name: 'Standard Hair', color_name: '1', length: '20', weight: '100g', unit: '' }, quantity: 2, unit_price: '50.0000', discount_amount: '0.00', line_amount: '100.00' }] }
  const historical = { ...structuredClone(doc), invoice_document_version: 1, total_amount: '120.00', commercial_header: { ...doc.commercial_header, customer_name: 'Historical PI Buyer', express_channel: 'FedEx' }, fees: { ...doc.fees, shipping_amount: '20.00' } }
  const proposal = mode === 'publish' ? { ...structuredClone(doc), revision_id: revision, bound_invoice_document_version: 2, expired: false, expires_at: '2026-10-05T10:00:00' } : null
  const order = { ...historical, request_id: id, request_no: 'REQ-PI-QA', status: 'invoice_created', row_version: 8, submitted_at: '2026-10-03T08:00:00', pi_amendment: { status: 'withdrawn' }, customer_safe_timeline: [] }
  let attempts = 0
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'QA', roles: ['sales'], permissions: ['portal_order:read', 'portal_order:write', 'invoice:write'] } })
    if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-pi-test' } })
    let data = {}
    if (path === '/api/portal/admin/v1/orders') data = { items: [order], total: 1 }
    if (path === `/api/portal/admin/v1/orders/${id}`) data = order
    if (path.endsWith('/pi-review')) {
      if (mode === 'denied') return route.fulfill({ status: 404, json: { code: 404, message: '原 PI 不在当前处理范围。', data: {} } })
      data = { request_id: id, request_no: 'REQ-PI-QA', row_version: 8, invoice_id: '90', invoice_document_version: 2, invoice_status: 'ready', amendment_status: mode === 'publish' ? 'accepted' : 'withdrawn', customer: { company_name: 'QA Company', customer_id: '10', okki_company_id: '20', sales_user_id: '5', invoice_sales_user_id: '6' }, current_invoice: doc, last_published: historical, proposal, available_actions: mode === 'blocked' ? [] : [`${mode === 'publish' ? 'publish' : mode === 'void' ? 'void' : 'propose'}_pi`], blocked_reasons: mode === 'blocked' ? [{ code: 'PI_VOID_REQUIRES_REVIEW', message: 'PI 已有出库记录，须先核对。' }] : [], policy: { proposal_valid_hours: [24, 48] } }
    }
    if (route.request().method() === 'POST' && /\/(pi-proposals|publish-pi|void-pi)$/.test(path)) {
      const command = { path, body: route.request().postDataJSON(), version: route.request().headers()['if-match'] }
      assert.equal(command.version, '"8"'); assert.equal(command.body.invoice_document_version, 2)
      sent.push(command); attempts++
      if (mode === 'publish' && attempts === 1) return route.fulfill({ status: 503, json: { code: 503, message: '模拟操作成功后响应丢失', data: {} } })
      data = { replayed: mode === 'publish', original_receipt: { request_id: id, invoice_document_version: 2 }, current_state: 'invoice_created', row_version: 9 }
    } else if (route.request().method() === 'POST' && !path.startsWith('/api/auth/')) throw new Error(`Unexpected write ${path}`)
    return route.fulfill({ json: { code: 200, message: 'ok', data } })
  })
  await page.goto('http://127.0.0.1:3211/portal/orders')
  await page.getByRole('button', { name: '详情', exact: true }).click()
  await page.getByRole('button', { name: '处理原 PI', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '处理原 PI', exact: true })
  if (mode === 'denied') {
    await dialog.getByText('原 PI 不在当前处理范围。', { exact: true }).waitFor()
    assert.equal(await dialog.getByText('Current PI Buyer', { exact: true }).count(), 0)
  } else {
    await dialog.getByRole('tabpanel', { name: '当前方舟 PI', exact: true }).getByText('Current PI Buyer', { exact: true }).waitFor()
    await dialog.getByRole('tabpanel', { name: '当前方舟 PI', exact: true }).getByText('QA complete delivery address\nSynthetic City', { exact: true }).waitFor()
    await dialog.getByRole('tab', { name: '最近发布历史快照', exact: true }).click()
    await dialog.getByRole('tabpanel', { name: '最近发布历史快照', exact: true }).getByText('Historical PI Buyer', { exact: true }).waitFor()
    await dialog.getByText('FedEx', { exact: true }).waitFor()
    await dialog.getByRole('tab', { name: '当前方舟 PI', exact: true }).click()
    if (mode === 'blocked') {
      await dialog.getByText('PI 已有出库记录，须先核对。', { exact: true }).waitFor()
      assert.equal(await dialog.getByRole('radio').count(), 0)
    } else {
      const label = mode === 'publish' ? '发布已确认 PI' : mode === 'void' ? '作废未流转 PI' : '发送 PI 修改提案'
      await dialog.locator('.el-radio-button').filter({ hasText: label }).click()
      if (mode !== 'publish') await dialog.getByLabel('操作原因', { exact: true }).fill('Reviewed the original PI and customer request')
      await dialog.locator('.el-checkbox').scrollIntoViewIfNeeded()
      assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
      if (process.env.PORTAL_QA_OUTPUT) await dialog.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/pi-${mode}.png` })
      await dialog.locator('.el-checkbox').click()
      assert.ok(await dialog.getByRole('checkbox').isChecked())
      await dialog.getByRole('button', { name: '确认 PI 操作', exact: true }).click()
      if (mode === 'publish') {
        await dialog.getByRole('button', { name: '重试原命令', exact: true }).waitFor()
        assert.equal(attempts, 1)
        await dialog.getByRole('button', { name: '重试原命令', exact: true }).click()
      }
      await dialog.waitFor({ state: 'hidden' })
      if (mode === 'publish') { assert.deepEqual(sent.at(-1), sent.at(-2)); assert.equal(sent.at(-1).body.accepted_revision_id, revision) }
      if (mode === 'propose') assert.equal(sent.at(-1).body.valid_for_hours, 24)
      if (mode === 'void') assert.equal(sent.at(-1).body.reason, 'Reviewed the original PI and customer request')
    }
  }
  await context.close()
}
try { for (const mode of ['propose', 'publish', 'void', 'blocked', 'denied']) await run(mode); assert.deepEqual(errors, []); console.log(JSON.stringify({ status: 'pass', scenarios: 5, writes: sent.length })) }
finally { await browser.close() }
