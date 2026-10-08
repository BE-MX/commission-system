import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url), { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } }), page = await context.newPage()
const id = '11111111-1111-4111-8111-111111111111', first = '22222222-2222-4222-8222-222222222222', second = '33333333-3333-4333-8333-333333333333'
const display = (item, name) => ({ item_id: item, model_name: name, color_name: 'Natural', length: '20 in', weight: '20 g', customer_sku: name, unit: 'piece' })
const baseLine = { line_key: 'line-1', quantity: 4, display_snapshot: display(first, 'Original Hair'), unit_price: '50.0000', discount_amount: '0.00', line_amount: '200.00' }
const order = { request_id: id, request_no: 'REQ-PREPARATION-001', customer_po: 'PO-QA', row_version: 1, status: 'submitted', currency: 'USD', product_amount: '200.00', total_amount: null, fees: { status: 'pending', shipping_amount: null, packaging_amount: null, surcharge_amount: null, surcharge_name: '' }, payment_terms_snapshot: { code: 'prepaid', display_text: 'Payment before shipment', deposit_percent: '200.00' }, delivery: { contact_name: 'Test Buyer', phone: '123456789', country_code: 'US', address_line1: 'Synthetic address', address_line2: '', city: 'QA City', region: '', postal_code: '12345' }, remark: '', items: [baseLine], customer_safe_timeline: [] }
const calls = [], previews = [], errors = []
let badPreview = true, attempts = 0, holdCatalog = false, pendingCatalog
page.on('pageerror', e => errors.push(e.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-test-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), path = new URL(req.url()).pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'QA', roles: [], permissions: ['portal_order:read', 'portal_order:write'] } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-test-only' } })
  if (path.endsWith('/proposal-catalog') && holdCatalog) { pendingCatalog = route; return }
  let data = {}
  if (path.endsWith('/orders')) data = { items: [order], total: 1 }
  else if (path.endsWith(`/orders/${id}`)) data = order
  else if (path.endsWith('/review')) data = { order, quantity_rules: [{ item_id: first, min_order_qty: 3, step_qty: 2 }], customer: { company_name: 'Synthetic Buyer', customer_id: '101', okki_company_id: '501', sales_user_id: '5' }, standard_lines: [], available_actions: ['propose', 'reject'], policy: { payment_terms: [order.payment_terms_snapshot], proposal_valid_hours: [24], default_payment_term_code: 'prepaid' } }
  else if (path.endsWith('/proposal-catalog')) data = { request_id: id, row_version: 1, items: [{ item_id: second, display_snapshot: display(second, 'Added Hair'), standard: { model: 'Standard Hair', color: '1' }, product_id: '102', sku_id: '202', min_order_qty: 3, step_qty: 2, sale_unit: 'piece' }], total: 1 }
  else if (path.endsWith('/proposal-preview')) {
    const body = req.postDataJSON(); previews.push(body)
    assert.equal(req.headers()['if-match'], '"1"')
    const items = body.items.map(line => ({ ...line, display_snapshot: display(line.item_id, line.item_id === first ? 'Original Hair' : 'Added Hair'), unit_price: line.item_id === first ? '55.0000' : '30.0000', discount_amount: '0.00', line_amount: (line.quantity * (line.item_id === first ? 55 : 30)).toFixed(2) }))
    const products = items.reduce((total, line) => total + Number(line.line_amount), 0)
    data = { request_id: id, row_version: badPreview ? 9 : 1, currency: 'USD', binding: false, requires_customer_acceptance: true, items, changes: items.map(line => ({ item_id: line.item_id, kind: line.item_id === first ? 'changed' : 'added', changed_fields: line.item_id === first ? ['unit_price', 'line_amount'] : [], before: line.item_id === first ? baseLine : null, after: line })), product_amount: products.toFixed(2), previous_product_amount: '200.00', total_amount: (products + Number(body.fees.shipping_amount)).toFixed(2), previous_total_amount: null, fees: body.fees, previous_fees: order.fees, payment_terms_snapshot: order.payment_terms_snapshot, previous_payment_terms_snapshot: order.payment_terms_snapshot, valid_for_hours: 24, calculated_at: '2026-10-03T12:00:00' }
  } else if (path.endsWith('/proposals')) {
    calls.push({ body: req.postDataJSON(), version: req.headers()['if-match'] }); attempts++
    if (attempts === 1) return route.abort('failed')
    data = { replayed: true, original_receipt: { request_id: id, row_version: 2 }, current_state: 'awaiting_customer', row_version: 2 }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const dialog = () => page.getByRole('dialog', { name: '处理客户下单请求', exact: true })
const previewButton = () => dialog().getByRole('button', { name: '预览金额与变化', exact: true })
const confirmation = () => dialog().getByRole('checkbox', { name: '我已核对内容，确认发送确认提案', exact: true })
try {
  await page.goto('http://127.0.0.1:3211/portal/orders')
  await page.getByRole('button', { name: '详情', exact: true }).click(); await page.getByRole('button', { name: '处理请求', exact: true }).click()
  await dialog().locator('.el-radio-button').filter({ hasText: '发送确认提案' }).click()
  await dialog().locator('.proposal-line').first().locator('.el-input-number__increase').click()
  assert.equal(await dialog().getByRole('spinbutton', { name: '商品数量', exact: true }).first().inputValue(), '6')
  await dialog().getByRole('spinbutton', { name: '商品数量', exact: true }).first().fill('4')
  await dialog().getByRole('button', { name: '新增授权商品', exact: true }).click()
  const add = dialog().getByRole('button', { name: '添加商品 Added Hair Natural', exact: true })
  await add.click(); assert.equal(await add.isDisabled(), true)
  assert.equal(await dialog().getByRole('spinbutton', { name: '商品数量', exact: true }).nth(1).inputValue(), '4')
  await dialog().getByRole('button', { name: '收起授权目录', exact: true }).click()
  for (const [name, value] of [['运费（USD）', '20.00'], ['包装费（USD）', '0.00'], ['附加费（USD）', '0.00']]) await dialog().getByLabel(name, { exact: true }).fill(value)
  await dialog().getByLabel('操作原因', { exact: true }).fill('Reviewed additional product and freight')
  assert.equal(await confirmation().isDisabled(), true)
  await previewButton().click(); await dialog().getByText('预览回执不完整，请重新预览。', { exact: true }).waitFor()
  assert.equal(await confirmation().isDisabled(), true)
  badPreview = false; await previewButton().click(); await dialog().getByText('提案金额与变更预览', { exact: true }).waitFor()
  await dialog().locator('.el-checkbox').click(); assert.equal(await confirmation().isChecked(), true)
  await dialog().getByRole('spinbutton', { name: '商品数量', exact: true }).nth(1).fill('6')
  assert.equal(await dialog().getByText('提案金额与变更预览', { exact: true }).count(), 0)
  assert.equal(await confirmation().isChecked(), false); assert.equal(await confirmation().isDisabled(), true)
  await previewButton().click(); await dialog().getByText('提案金额与变更预览', { exact: true }).waitFor()
  await dialog().locator('.el-checkbox').click(); await dialog().getByLabel('运费（USD）', { exact: true }).fill('25.00')
  assert.equal(await confirmation().isChecked(), false)
  await previewButton().click(); await dialog().getByText('提案金额与变更预览', { exact: true }).waitFor()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    await dialog().locator('.proposal-preview').evaluate(el => el.scrollIntoView({ block: 'start' }))
    assert.ok(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth + 1), `overflow at ${width}`)
    await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/proposal-preparation-${width}.png`, fullPage: true })
  }
  await dialog().getByRole('button', { name: '新增授权商品', exact: true }).click()
  await dialog().getByText('起订 3', { exact: false }).first().waitFor()
  holdCatalog = true; await dialog().getByRole('button', { name: '刷新目录', exact: true }).click()
  await dialog().locator('.el-checkbox').click(); await dialog().getByRole('button', { name: '确认操作', exact: true }).click()
  await dialog().getByRole('button', { name: '重试原命令', exact: true }).waitFor()
  assert.equal(await dialog().getByRole('spinbutton', { name: '商品数量', exact: true }).first().isDisabled(), true)
  assert.equal(await dialog().getByRole('button', { name: '收起授权目录', exact: true }).isDisabled(), true)
  assert.equal(await previewButton().isDisabled(), true); assert.equal(await confirmation().isDisabled(), true)
  assert.equal(calls.length, 1)
  assert.ok(pendingCatalog)
  await pendingCatalog.fulfill({ status: 403, json: { code: 403, message: '目录读取权限已变化', data: {} } })
  await dialog().getByText('目录读取权限已变化，详情已隐藏。原提案结果仍待核对，请重试原命令获取回执。', { exact: true }).waitFor()
  assert.equal(await dialog().getByText('当前版本完整条款', { exact: true }).count(), 0)
  assert.equal(await dialog().getByRole('button', { name: '关闭', exact: true }).isDisabled(), true)
  await dialog().getByRole('button', { name: '重试原命令', exact: true }).click(); await dialog().waitFor({ state: 'hidden' })
  assert.deepEqual(calls[0], calls[1]); assert.deepEqual(calls[0].body, previews.at(-1))
  assert.deepEqual(calls[0].body.items, [{ item_id: first, quantity: 4 }, { item_id: second, quantity: 6 }])
  assert.equal(calls[0].body.fees.shipping_amount, '25.00'); assert.equal('unit_price' in calls[0].body.items[0], false)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', previewReads: previews.length, simulatedCommandAttempts: calls.length, scenarios: ['existing line current quantity step', 'late catalog denial preserves unknown command', 'authorized addition', 'minimum step rounded', 'duplicate blocked', 'preview required', 'bad preview rejected', 'unit price change shown', 'quantity invalidates preview and confirmation', 'fees invalidate preview and confirmation', '1440/390/320 layout', 'unknown freezes additions and amounts', 'exact command replay', 'no client prices'] }))
} finally { await browser.close() }
