import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || 'tmp/browser-qa'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.PORTAL_CHROMIUM ? { executablePath: process.env.PORTAL_CHROMIUM } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
const uuid = n => `${n}1111111-1111-4111-8111-111111111111`
const identity = { me: { account_public_id: uuid(9), company_display_name: 'Atelier Test Salon' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'test-csrf' }
const product = { item_id: uuid(1), model_name: 'Existing cart product', color_name: 'Natural', category: 'hair', sale_unit: 'pack', length_display: '20 in', weight_display: '20 g', min_order_qty: 1, step_qty: 1, unit_price: '30.0000', availability: 'available' }
const oldLine = { line_key: uuid(3), quantity: 4, unit_price: '30.0000', line_amount: '120.00', discount_amount: '0.00', display_snapshot: { item_id: uuid(4), model_name: 'Old client name', color_name: 'Old shade', customer_sku: 'OLD-01', length: '20 in', weight: '20 g', unit: 'pack' } }
const removedLine = { ...structuredClone(oldLine), line_key: uuid(5), display_snapshot: { ...oldLine.display_snapshot, model_name: 'Withdrawn product' } }
const delivery = { contact_name: 'Previous buyer', phone: '123456', address_line1: 'Previous address', country_code: 'GB', address_line2: '', city: 'London', region: '', postal_code: '' }
const order = { request_id: uuid(2), request_no: 'REQ-OLD-001', row_version: 1, status: 'cancelled', submitted_at: '2026-09-29T10:00:00', customer_po: 'OLD-PO', remark: 'Previous note', items: [oldLine, removedLine], delivery, product_amount: '240.00', total_amount: '285.00', fees: { status: 'confirmed', shipping_amount: '45.00', packaging_amount: '0.00', surcharge_amount: '0.00' }, payment_terms_snapshot: { display_text: 'Previous terms' }, available_actions: [], customer_safe_timeline: [] }
const newLine = { ...structuredClone(oldLine), item_id: uuid(4), line_key: uuid(6), min_order_qty: 3, step_qty: 2, unit_price: '35.2750', line_amount: '141.10', display_snapshot: { ...oldLine.display_snapshot, model_name: 'Current client name', color_name: 'Champagne', length: '22 in', weight: '25 g' } }
const quote = { quote_id: uuid(7), content_hash: 'a'.repeat(64), status: 'valid', currency: 'USD', expires_at: new Date(Date.now() + 600000).toISOString(), items: [newLine], product_amount: '141.10', total_amount: null, fees: { status: 'pending', shipping_amount: null, packaging_amount: null, surcharge_amount: null }, delivery, customer_po: '', remark: 'Previous note', payment_terms_snapshot: { display_text: 'Current payment terms' }, reorder: { source_request_id: order.request_id, source_revision_id: uuid(8), changes: [{ line_key: oldLine.line_key, change: 'changed', before: oldLine, after: newLine }] } }
const calls = [], errors = []
let mode = 'late', release
let markStarted
const started = new Promise(resolve => { markStarted = resolve })
await context.route('**/api/portal/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname, body = request.postDataJSON()
  calls.push({ path, method: request.method(), body })
  const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status, message: status >= 400 ? 'Some products are no longer available. Review your selection.' : 'OK', data }) })
  if (path.endsWith('/session')) return send(identity)
  if (path.endsWith('/catalog')) return send({ items: [product], total: 1 })
  if (path.endsWith('/reorder-quote')) {
    assert.ok(body.line_keys.length)
    if (mode === 'late') { await new Promise(resolve => { release = resolve; markStarted() }); return send(quote) }
    if (body.line_keys.includes(removedLine.line_key)) return send({ error_code: 'REORDER_CHANGED', issues: [{ line_key: removedLine.line_key, error_code: 'PRODUCT_UNAVAILABLE' }] }, 409)
    assert.deepEqual(body, { line_keys: [oldLine.line_key] })
    return send(quote)
  }
  if (path.endsWith(`/orders/${order.request_id}`)) return send(order)
  if (path.endsWith('/orders') && request.method() === 'POST') { assert.equal(body.quote_id, quote.quote_id); assert.equal(body.customer_po, ''); return send({ request_id: uuid(8), request_no: 'REQ-NEW-001', status: 'submitted' }, 201) }
  throw new Error(`Unexpected ${path}`)
})
const page = await context.newPage(); page.on('pageerror', problem => errors.push(problem.message))
try {
  await page.goto(origin)
  await page.getByRole('button', { name: 'View Existing cart product, Natural' }).click()
  await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
  await page.getByRole('button', { name: 'Close product' }).click()
  // A history navigation preserves the app-owned draft; a document reload would not.
  await page.evaluate(id => { history.pushState(null, '', `/orders/${id}`); window.dispatchEvent(new PopStateEvent('popstate')) }, order.request_id)
  await page.getByRole('button', { name: 'Repeat selected products' }).click()
  const dialog = page.getByRole('dialog', { name: 'Repeat request products' })
  assert.equal(await dialog.getByRole('button', { name: 'Review fresh quote' }).isDisabled(), true)
  assert.equal(calls.filter(call => call.path.endsWith('/reorder-quote')).length, 0)
  await dialog.getByRole('checkbox', { name: /Replace my current selection/ }).check()
  await dialog.getByRole('button', { name: 'Review fresh quote' }).click()
  await dialog.getByRole('button', { name: 'Preparing fresh quote…' }).waitFor()
  await started
  await dialog.getByRole('button', { name: 'Close repeat request' }).click()
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(button => button.textContent === 'Repeat selected products').disabled)
  release()
  await page.getByRole('link', { name: /Selection/ }).click()
  assert.match(await page.locator('.cart-line').innerText(), /Existing cart product/)
  await page.evaluate(id => { history.pushState(null, '', `/orders/${id}`); window.dispatchEvent(new PopStateEvent('popstate')) }, order.request_id)
  mode = 'available'
  await page.getByRole('button', { name: 'Repeat selected products' }).click()
  await dialog.getByRole('checkbox', { name: /Replace my current selection/ }).check()
  await dialog.getByRole('button', { name: 'Review fresh quote' }).click()
  await dialog.getByRole('alert').waitFor()
  assert.match(await dialog.innerText(), /No longer in your approved collection/)
  assert.equal(await dialog.getByRole('checkbox', { name: /Replace my current selection/ }).isChecked(), true)
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.equal(await dialog.evaluate(el => el.scrollWidth > el.clientWidth), false)
    await page.screenshot({ path: `${output}/reorder-dialog-${width}.png` })
  }
  await dialog.getByRole('checkbox', { name: 'Repeat Withdrawn product, Old shade' }).uncheck()
  await dialog.getByRole('button', { name: 'Review fresh quote' }).click()
  await page.getByRole('heading', { name: 'Your selection.' }).waitFor()
  assert.match(await page.locator('.cart-line').innerText(), /Current client name/)
  assert.ok(!(await page.locator('.cart-line').innerText()).includes('Existing cart product'))
  assert.equal(await page.getByLabel('Your PO').inputValue(), '')
  assert.equal(await page.getByLabel('Contact name').inputValue(), 'Previous buyer')
  assert.match(await page.locator('.reorder-comparison').innerText(), /Old client name/)
  assert.match(await page.locator('.reorder-comparison').innerText(), /Current client name/)
  assert.match(await page.locator('.checkout-review').innerText(), /Pending review/)
  assert.equal(await page.locator('.checkout-review').getByRole('checkbox').isChecked(), false)
  assert.equal(await page.getByRole('button', { name: 'Submit order request' }).isDisabled(), true)
  assert.equal(calls.filter(call => call.path.endsWith('/orders') && call.method === 'POST').length, 0)
  await page.setViewportSize({ width: 1440, height: 1100 }); await page.evaluate(() => scrollTo(0, 0))
  await page.screenshot({ path: `${output}/reorder-review-1440.png`, fullPage: true })
  await page.locator('.checkout-review').getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Submit order request' }).click()
  await page.getByRole('heading', { name: 'Thank you. We’ll take it from here.' }).waitFor()
  assert.equal(calls.filter(call => call.path.endsWith('/orders') && call.method === 'POST').length, 1)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', scope: 'Built frontend with intercepted synthetic API only', assertions: ['explicit existing-cart replacement', 'closing dialog discards late quote', 'unavailable line deselection and retry', '390/320 dialog overflow', 'current alias/spec/price comparison', 'copied address with cleared PO and pending fees', 'no order created until fresh explicit consent'], apiCalls: calls.length, screenshots: output }))
} finally { await browser.close() }
