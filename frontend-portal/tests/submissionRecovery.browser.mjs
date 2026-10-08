import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT; assert.ok(output); await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.PORTAL_CHROMIUM })
const buyer = '11111111-1111-4111-8111-111111111111', key = '33333333-3333-4333-8333-333333333333'
const slot = 'leshine.portal.pending:' + buyer, raw = '{PRIVATE_INVALID_RECOVERY_RECORD'
const identity = { me: { account_public_id: buyer, company_display_name: 'Synthetic Recovery Buyer' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'synthetic-csrf' }
const product = { item_id: '22222222-2222-4222-8222-222222222222', model_name: 'Synthetic Weft', color_name: 'Synthetic Blonde', customer_sku: 'TEST-01', sale_unit: 'pack', min_order_qty: 1, step_qty: 1, unit_price: '32.0000', availability: 'available' }
const receipt = { request_id: key, request_no: 'SYNTHETIC-REQUEST-01', status: 'submitted' }
const results = []
try {
  for (const scenario of ['corrupt', 'unreadable']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
    await context.addInitScript(({ slot, raw, fail }) => {
      sessionStorage.setItem(slot, raw)
      window.recoveryReadAllowed = !fail
      const read = Storage.prototype.getItem
      Storage.prototype.getItem = function(k) {
        if (this === sessionStorage && k === slot && !window.recoveryReadAllowed) throw new Error('PRIVATE_READ_ERROR')
        return read.call(this, k)
      }
    }, { slot, raw, fail: scenario === 'unreadable' })
    const calls = [], errors = []
    await context.route('**/api/portal/v1/**', async route => {
      const request = route.request(), url = new URL(request.url()), body = request.postDataJSON()
      calls.push({ path: url.pathname, method: request.method() })
      const send = data => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ code: 200, message: 'OK', data }) })
      if (url.pathname.endsWith('/session')) return send(identity)
      if (url.pathname.endsWith('/catalog')) return send({ items: [product], total: 1, page: 1, page_size: 24 })
      if (url.pathname.endsWith('/quotes')) return send({ ...body, quote_id: key, content_hash: 'a'.repeat(64), status: 'valid', currency: 'USD', product_amount: '32.00', total_amount: null, expires_at: new Date(Date.now() + 600000).toISOString(), fees: { status: 'pending', shipping_amount: null, packaging_amount: null, surcharge_amount: null }, items: [{ line_key: product.item_id, item_id: product.item_id, quantity: 1, unit_price: '32.0000', discount_amount: '0.00', line_amount: '32.00', display_snapshot: { model_name: product.model_name, color_name: product.color_name, customer_sku: product.customer_sku, unit: 'pack' } }] })
      if (url.pathname.endsWith('/orders') && request.method() === 'GET') return send({ items: [], total: 0, page: 1, page_size: 20 })
      if (url.pathname.endsWith('/orders/by-key/' + key)) return send(receipt)
      if (url.pathname.endsWith('/logout')) return send({ signed_out: true })
      throw new Error('Unexpected test API: ' + request.method() + ' ' + url.pathname)
    })
    const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message))
    await page.goto(origin)
    const notice = page.getByRole('alert').filter({ has: page.getByRole('button', { name: 'Check recovery reference' }) })
    await notice.waitFor(); assert.equal(await page.getByRole('button', { name: 'Sign out', exact: true }).count(), 1)
    assert.equal(await page.getByRole('button', { name: 'Continue with email' }).count(), 0)
    assert.ok(!/PRIVATE_/.test(await page.locator('body').innerText()))
    await notice.getByRole('button', { name: 'View existing requests' }).click()
    await page.getByRole('heading', { name: 'Your requests.', exact: true }).waitFor()
    assert.ok(calls.some(call => call.path.endsWith('/orders') && call.method === 'GET'))
    await page.getByRole('link', { name: 'Collection', exact: true }).click()
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1100 })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      if (scenario === 'corrupt') await page.screenshot({ path: `${output}/recovery-${width}.png`, fullPage: true })
    }
    await page.setViewportSize({ width: 1440, height: 1100 })
    await page.getByRole('button', { name: 'View Synthetic Weft, Synthetic Blonde' }).click()
    await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
    await page.getByRole('button', { name: 'Review selection', exact: true }).click()
    for (const [label, value] of [['Contact name', 'Synthetic Buyer'], ['Phone number', '+44 123456789'], ['Address line 1', 'Synthetic Address'], ['Country code', 'GB']]) await page.getByLabel(label, { exact: label !== 'Country code' }).fill(value)
    await page.getByRole('button', { name: 'Review request', exact: true }).click()
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Submit order request', exact: true }).click()
    await page.locator('.alert.error').waitFor()
    assert.equal(calls.filter(call => call.path.endsWith('/orders') && call.method === 'POST').length, 0)
    assert.ok(!/PRIVATE_/.test(await page.locator('body').innerText()))
    assert.equal(await page.evaluate(slot => Storage.prototype.getItem.call(sessionStorage, slot), 'unrelated-slot'), null)
    const retained = await page.evaluate(({ slot, key }) => { window.recoveryReadAllowed = true; const retained = sessionStorage.getItem(slot); sessionStorage.setItem(slot, JSON.stringify({ key })); return retained }, { slot, key })
    assert.equal(retained, raw)
    await notice.getByRole('button', { name: 'Check recovery reference' }).click()
    await page.getByRole('heading', { name: 'Let’s confirm the result.' }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Retry original request' }).count(), 0)
    await page.getByRole('button', { name: 'Check request status' }).click()
    await page.getByRole('heading', { name: 'Thank you. We’ll take it from here.' }).waitFor()
    assert.equal(await page.evaluate(slot => sessionStorage.getItem(slot), slot), null)
    assert.equal(calls.filter(call => call.path.endsWith('/orders') && call.method === 'POST').length, 0)
    assert.deepEqual(errors, [])
    results.push({ scenario, loginPreserved: true, existingRequestRead: true, newOrderPosts: 0, repairedReferenceGetOnly: true, widths: [1440, 390, 320], apiCalls: calls.length })
    await context.close()
  }
  const report = { status: 'passed', scope: 'Actual built Vue app and headless Chrome; synthetic intercepted API/auth only, no backend/production or closed-tab durability proof.', results }
  await writeFile(output + '/report.json', JSON.stringify(report, null, 2) + '\n')
  console.log(JSON.stringify(report))
} finally { await browser.close() }
