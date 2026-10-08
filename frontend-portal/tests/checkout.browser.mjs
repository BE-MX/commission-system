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
const identity = { me: { account_public_id: '11111111-1111-4111-8111-111111111111', company_display_name: 'Atelier Test Salon' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'test-csrf' }
const product = { item_id: '22222222-2222-4222-8222-222222222222', model_name: 'Genius Weft', color_name: 'Champagne', customer_sku: 'GW-CH', length_display: '20 in', weight_display: '20 g', sale_unit: 'pack', min_order_qty: 3, step_qty: 2, category: 'hair', unit_price: '32.0000', availability: 'available' }
const receipt = { request_id: '33333333-3333-4333-8333-333333333333', request_no: 'REQ-TEST-001', status: 'submitted', row_version: 1, currency: 'USD', product_amount: '141.10', total_amount: null }
const calls = [], errors = []
let quoteFail = false, submitMode = 'lost', recoveryFound = false, signedIn = true, submittedBody, submittedKey
await context.route('**/api/portal/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname, body = request.postDataJSON()
  calls.push({ path, method: request.method(), body, headers: request.headers() })
  const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status, message: status >= 400 ? 'Please refresh and try again.' : 'OK', data }) })
  if (path.endsWith('/session')) return send(signedIn ? identity : { error_code: 'AUTH_REQUIRED' }, signedIn ? 200 : 401)
  if (path.endsWith('/catalog')) return send({ items: [product], total: 1, page: 1, page_size: 24 })
  if (path.endsWith('/quotes')) {
    if (quoteFail) return send({ error_code: 'INVENTORY_UNAVAILABLE' }, 503)
    assert.deepEqual(body.items, [{ item_id: product.item_id, quantity: 4 }])
    return send({ ...body, quote_id: receipt.request_id, status: 'valid', content_hash: 'a'.repeat(64), currency: 'USD', expires_at: new Date(Date.now() + 600000).toISOString(), product_amount: '141.10', total_amount: null, fees: { status: 'pending', shipping_amount: null, packaging_amount: null, surcharge_amount: null }, payment_terms_snapshot: { display_text: 'Full payment before dispatch' }, items: [{ line_key: product.item_id, item_id: product.item_id, display_snapshot: { model_name: product.model_name, color_name: product.color_name, customer_sku: product.customer_sku, length: '22 in', weight: '25 g', unit: 'pack' }, quantity: 4, unit_price: '35.2750', discount_amount: '0.00', line_amount: '141.10' }] })
  }
  if (path.endsWith('/orders')) {
    if (submitMode === 'reject') return send({ error_code: 'PRICE_CHANGED' }, 409)
    if (submittedKey) { assert.equal(request.headers()['idempotency-key'], submittedKey); assert.deepEqual(body, submittedBody) }
    submittedBody = body; submittedKey = request.headers()['idempotency-key']
    if (submitMode === 'lost') return route.abort('failed')
    return send(receipt, 201)
  }
  if (path.includes('/orders/by-key/')) {
    assert.equal(path.split('/').at(-1), submittedKey)
    return send(recoveryFound ? receipt : { error_code: 'NOT_FOUND' }, recoveryFound ? 200 : 404)
  }
  if (path.endsWith('/logout')) { signedIn = false; return send({ signed_out: true }) }
  throw new Error(`Unexpected request ${path}`)
})
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
const select = async () => {
  await page.getByRole('button', { name: 'View Genius Weft, Champagne' }).click()
  assert.equal(await page.getByRole('dialog').getByLabel('Quantity').inputValue(), '4')
  await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
  await page.getByRole('button', { name: 'Review selection', exact: true }).click()
  await page.getByRole('heading', { name: 'Your selection.' }).waitFor()
}
const fill = async () => {
  await page.getByLabel('Contact name', { exact: true }).fill('Test buyer')
  await page.getByLabel('Phone number').fill('+44 123456789')
  await page.getByLabel('Address line 1', { exact: true }).fill('10 Test Lane')
  await page.getByLabel('Country code').fill('GB')
  await page.getByLabel('Your PO').fill('PO-TEST')
  await page.getByLabel('Request notes').fill('Test note')
}
try {
  await page.goto(origin); await select(); await fill()
  quoteFail = true
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByRole('alert').evaluate(el => el === document.activeElement), true)
  assert.equal(await page.getByLabel('Contact name').inputValue(), 'Test buyer')
  quoteFail = false
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.getByRole('button', { name: 'Submit order request', exact: true }).waitFor()
  const review = page.getByRole('complementary', { name: 'Server review' })
  assert.match(await review.innerText(), /Length: 22 in/)
  assert.match(await review.innerText(), /Weight: 25 g/)
  assert.match(await review.innerText(), /Updated since selection/)
  assert.match(await review.innerText(), /USD 35.275/)
  assert.match(await review.innerText(), /Pending review/)
  assert.equal(await page.getByRole('button', { name: 'Submit order request' }).isDisabled(), true)
  await page.getByRole('checkbox').check()
  await page.getByLabel('Phone number').fill('+44 987654321')
  assert.equal(await page.getByRole('button', { name: 'Submit order request' }).count(), 0)
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.getByRole('button', { name: 'Submit order request' }).waitFor()
  assert.equal(await page.getByRole('checkbox').isChecked(), false)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1100 })
    await page.evaluate(() => window.scrollTo(0, 0))
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: `${output}/checkout-${width}.png`, fullPage: true })
  }
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Submit order request' }).click()
  await page.getByRole('heading', { name: 'Let’s confirm the result.' }).waitFor()
  assert.equal(calls.filter(call => call.path.endsWith('/orders')).length, 1)
  const saved = await page.evaluate(() => Object.entries(sessionStorage))
  assert.deepEqual(saved, [[`leshine.portal.pending:${identity.me.account_public_id}`, JSON.stringify({ key: submittedKey })]])
  assert.equal(submittedBody.customer_po, 'PO-TEST'); assert.equal(submittedBody.remark, 'Test note')
  await page.getByRole('button', { name: 'Retry original request' }).click()
  await page.getByRole('heading', { name: 'Let’s confirm the result.' }).waitFor()
  assert.equal(calls.filter(call => call.path.endsWith('/orders')).length, 2)
  await page.reload()
  await page.getByRole('heading', { name: 'Let’s confirm the result.' }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Retry original request' }).count(), 0)
  assert.equal(await page.getByLabel('Contact name').count(), 0)
  recoveryFound = true
  await page.getByRole('button', { name: 'Check request status' }).click()
  await page.getByRole('heading', { name: 'Thank you. We’ll take it from here.' }).waitFor()
  assert.equal(await page.evaluate(() => sessionStorage.length), 0)
  assert.equal(calls.filter(call => call.path.endsWith('/orders')).length, 2)
  await page.screenshot({ path: `${output}/checkout-recovered.png`, fullPage: true })
  await page.getByRole('button', { name: 'Back to collection', exact: true }).click()
  await select(); await fill()
  submitMode = 'reject'
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Submit order request' }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByRole('button', { name: 'Submit order request' }).count(), 0)
  assert.equal(await page.getByLabel('Contact name').inputValue(), 'Test buyer')
  const other = await context.newPage(); await other.goto(origin)
  await other.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.getByRole('button', { name: 'Continue with email' }).waitFor()
  assert.equal(await page.getByLabel('Contact name').count(), 0)
  assert.equal(await page.locator('.cart-line').count(), 0)
  assert.deepEqual(errors, [])
  assert.ok(calls.filter(call => call.method === 'POST').every(call => call.headers['x-portal-csrf'] && !call.headers.authorization))
  console.log(JSON.stringify({ status: 'pass', scope: 'Built frontend, intercepted test API only', assertions: ['MOQ/step aligned initial quantity', 'quote failure retains form', 'changed server specs and price shown', 'edit invalidates quote and consent', '1440/390/320 layout', 'unknown outcome and same-key retry', 'refresh GET-only recovery without customer payload persistence', 'definite rejection keeps editable draft', 'another-tab logout clears checkout'], apiCalls: calls.length, screenshots: output }))
} finally { await browser.close() }
