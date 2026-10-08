import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const id = '12345678-1234-1234-1234-123456789abc', revision = '12345678-1234-1234-1234-123456789def'
const item = '12345678-1234-1234-1234-123456789aaa'
let sends = [], errors = []
async function scenario(mode) {
  const context = await browser.newContext({ viewport: { width: mode === 'propose' ? 390 : 1440, height: 950 } })
  const page = await context.newPage()
  page.on('pageerror', e => errors.push(e.message))
  await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-review-test'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
  let attempts = 0, completed = false
  const order = { request_id: id, request_no: 'REQ-REVIEW-001', customer_po: 'BUYER-PO-09', row_version: 3, status: mode === 'approve' ? 'ready_for_review' : 'submitted', submitted_at: '2026-09-30T09:00:00', currency: 'USD', product_amount: '100.00', total_amount: '120.00', fees: { status: 'confirmed', shipping_amount: '20.00', packaging_amount: '0.00', surcharge_amount: '0.00', surcharge_name: '' }, proposal: mode === 'approve' ? { revision_id: revision, accepted: true, expired: false, expires_at: '2026-10-05T09:00:00' } : null, payment_terms_snapshot: { code: 'prepaid', display_text: '100% payment before shipment', deposit_percent: '100.00' }, delivery: { contact_name: 'QA Buyer', phone: '123456789', country_code: 'US', address_line1: 'Synthetic address', address_line2: '', city: 'QA City', region: '', postal_code: '12345' }, remark: 'QA remark', items: [{ line_key: 'line1', quantity: 2, display_snapshot: { item_id: item, model_name: 'QA Hair', color_name: 'Natural', customer_sku: 'QA-SKU', length: '20 in', weight: '100 g', unit: 'piece' }, unit_price: '50.0000', discount_amount: '0.00', line_amount: '100.00' }], customer_safe_timeline: [] }
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'QA', roles: ['sales'], permissions: ['portal_order:read', 'portal_order:write', 'invoice:write'] } })
    if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-review-test' } })
    let data = {}
    if (path === '/api/portal/admin/v1/orders') data = { items: [{ ...order, status: completed ? 'awaiting_customer' : order.status }], total: 1 }
    if (path === `/api/portal/admin/v1/orders/${id}`) data = order
    if (path.endsWith('/review')) {
      if (mode === 'denied') return route.fulfill({ status: 404, json: { code: 404, message: '不在当前处理权限范围内。', data: { error_code: 'RESOURCE_NOT_FOUND' } } })
      data = { order, quantity_rules: [{ item_id: item, min_order_qty: 1, step_qty: 1 }], customer: { company_name: 'QA Company', customer_id: '10', okki_company_id: '99', sales_user_id: '5' }, standard_lines: [{ line_key: 'line1', product_id: '101', sku_id: '201', standard: { model: 'Standard Hair', color: '1' } }], available_actions: mode === 'approve' ? ['approve', 'reject', 'propose'] : ['propose', 'reject'], policy: { payment_terms: [order.payment_terms_snapshot], proposal_valid_hours: [24, 48], default_payment_term_code: 'prepaid' } }
    }
    if (path.endsWith('/proposal-preview')) {
      const body = route.request().postDataJSON()
      data = { request_id: id, row_version: 3, currency: 'USD', binding: false, requires_customer_acceptance: true, items: order.items.map(line => ({ ...line, item_id: line.display_snapshot.item_id })), changes: order.items.map(line => ({ item_id: line.display_snapshot.item_id, kind: 'unchanged', changed_fields: [], before: line, after: line })), product_amount: '100.00', previous_product_amount: '100.00', total_amount: '120.00', previous_total_amount: '120.00', fees: body.fees, previous_fees: order.fees, payment_terms_snapshot: order.payment_terms_snapshot, previous_payment_terms_snapshot: order.payment_terms_snapshot, calculated_at: '2026-10-03T10:00:00', valid_for_hours: 24 }
    }
    if (route.request().method() === 'POST' && /\/(approve|proposals|reject)$/.test(path)) {
      const sent = { path, body: route.request().postDataJSON(), version: route.request().headers()['if-match'] }; sends.push(sent); attempts++
      assert.equal(sent.version, '"3"')
      if (mode === 'approve' && attempts === 1) return route.fulfill({ status: 503, json: { code: 503, message: '模拟响应丢失', data: { error_code: 'SERVICE_UNAVAILABLE' } } })
      completed = true
      data = { replayed: mode === 'approve', original_receipt: { request_id: id, row_version: 4 }, current_state: mode === 'approve' ? 'invoice_created' : 'awaiting_customer', row_version: 4 }
    }
    return route.fulfill({ json: { code: 200, message: 'ok', data } })
  })
  await page.goto('http://127.0.0.1:3211/portal/orders')
  await page.getByRole('button', { name: '详情', exact: true }).click()
  await page.getByRole('button', { name: '处理请求', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '处理客户下单请求', exact: true })
  if (mode === 'denied') {
    await dialog.getByText('不在当前处理权限范围内。', { exact: true }).waitFor()
    assert.equal(await dialog.getByText('当前版本完整条款', { exact: true }).count(), 0)
    assert.ok(await dialog.getByRole('button', { name: '确认操作', exact: true }).isDisabled())
  } else {
    await dialog.getByText('当前版本完整条款', { exact: true }).waitFor()
    await dialog.getByText('QA Buyer', { exact: true }).waitFor()
    await dialog.getByText('建票客户：QA Company', { exact: true }).waitFor()
    await dialog.locator('.el-radio-button').filter({ hasText: mode === 'approve' ? '审核并生成正式 PI' : mode === 'reject' ? '拒绝请求' : '发送确认提案' }).click()
    if (mode !== 'approve') await dialog.getByLabel('操作原因', { exact: true }).fill('Confirmed shipping and customer terms')
    if (mode === 'propose') { await dialog.getByRole('button', { name: '预览金额与变化', exact: true }).click(); await dialog.getByText('提案金额与变更预览', { exact: true }).waitFor() }
    await dialog.locator('.el-checkbox').waitFor(); await dialog.locator('.el-checkbox').scrollIntoViewIfNeeded(); assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    if (process.env.PORTAL_QA_OUTPUT) await dialog.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/review-${mode}.png` });
    await dialog.locator('.el-checkbox').click(); assert.ok(await dialog.getByRole('checkbox').isChecked())
    await dialog.getByRole('button', { name: '确认操作', exact: true }).click()
    if (mode === 'approve') {
      await dialog.getByRole('button', { name: '重试原命令', exact: true }).waitFor()
      assert.equal(attempts, 1)
      assert.ok(await dialog.getByRole('button', { name: '关闭', exact: true }).isDisabled())
      await dialog.getByRole('button', { name: '重试原命令', exact: true }).click()
      await dialog.waitFor({ state: 'hidden' })
      assert.equal(attempts, 2); assert.deepEqual(sends[0], sends[1])
      assert.deepEqual(sends[0].body, { accepted_revision_id: revision })
    } else {
      await dialog.waitFor({ state: 'hidden' })
      const sent = sends.at(-1)
      if (mode === 'reject') { assert.deepEqual(sent.body, { reason: 'Confirmed shipping and customer terms' }) } else {
      assert.equal(sent.body.customer_po, 'BUYER-PO-09')
      assert.equal(sent.body.fees.shipping_amount, '20.00')
      assert.equal(sent.body.payment_terms, 'prepaid')
      assert.deepEqual(sent.body.items, [{ item_id: item, quantity: 2 }])
      assert.ok(!('unit_price' in sent.body.items[0]))
      }
    }
  }
  await context.close()
}
try { for (const mode of ['approve', 'propose', 'reject', 'denied']) await scenario(mode); assert.deepEqual(errors, []); console.log(JSON.stringify({ status: 'pass', scenarios: 4, writes: sends.length })) }
finally { await browser.close() }
