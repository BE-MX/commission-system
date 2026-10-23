import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'

// Weight-tiered shipping and payment-method surcharge on the review step, desktop and 375px.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || 'tmp/browser-qa'
await mkdir(output, { recursive: true })
const identity = { me: { account_public_id: '11111111-1111-4111-8111-111111111111', company_display_name: 'Atelier Test Salon' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'test-csrf' }
const product = { item_id: '22222222-2222-4222-8222-222222222222', model_name: 'Genius Weft', color_name: '#2', customer_sku: null, length_display: '18', weight_display: '20', sale_unit: 'piece', min_order_qty: 1, step_qty: 1, category: 'hair', unit_price: '27.0000', availability: 'available', stock_display: '100+', currency: 'USD', image_url: null, inventory_observed_at: '2026-10-19T10:00:00' }
const terms = { payment_terms: [{ code: 'bank', label: 'Bank transfer', display_text: 'Bank transfer before shipment', surcharge_percent: '0.00' }, { code: 'paypal', label: 'PayPal', display_text: 'PayPal before shipment', surcharge_percent: '5.00' }], default_payment_term_code: 'bank', auto_fees: { enabled: true, shipping_tiers: [{ max_grams: 300, fee: '40.00' }] } }
const estimate = term => term === 'paypal'
  ? { status: 'confirmed', payment_term_code: 'paypal', surcharge_percent: '5.00', manual_above_grams: 2000, weight_grams: '60', shipping_amount: '40.00', packaging_amount: '0.00', surcharge_amount: '6.05', surcharge_name: 'Payment surcharge (PayPal 5%)', total_amount: '127.05' }
  : { status: 'confirmed', payment_term_code: 'bank', surcharge_percent: '0.00', manual_above_grams: 2000, weight_grams: '60', shipping_amount: '40.00', packaging_amount: '0.00', surcharge_amount: '0.00', surcharge_name: '', total_amount: '121.00' }

async function run(viewport, name) {
  const browser = await chromium.launch({ headless: true, ...(process.env.PORTAL_CHROMIUM ? { executablePath: process.env.PORTAL_CHROMIUM } : {}) })
  const context = await browser.newContext({ viewport })
  const quotes = [], errors = []
  await context.route('**/api/portal/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, body = request.postDataJSON()
    const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status, message: 'OK', data }) })
    if (path.endsWith('/session')) return send(identity)
    if (path.endsWith('/sales-contact')) return send({ assigned: false })
    if (path.endsWith('/catalog/families')) return send({ items: [], ungrouped_count: 0, catalog_version: 1 })
    if (path.endsWith('/catalog')) return send({ items: [product], total: 1, page: 1, page_size: 24, facets: { categories: [], colors: [] } })
    if (path.endsWith('/ordering-terms')) return send(terms)
    if (path.endsWith('/quotes')) {
      quotes.push(body)
      const term = body.payment_term_code || 'bank'
      return send({ quote_id: '33333333-3333-4333-8333-333333333333', status: 'valid', content_hash: 'a'.repeat(64), currency: 'USD', expires_at: new Date(Date.now() + 600000).toISOString(), product_amount: '81.00', total_amount: null, fees: { status: 'pending' }, fee_estimate: estimate(term), fees_confirmed_on_submit: true, payment_terms_snapshot: { code: term, display_text: term === 'paypal' ? 'PayPal before shipment' : 'Bank transfer before shipment' }, delivery: body.delivery, customer_po: body.customer_po, remark: body.remark, items: [{ line_key: product.item_id, item_id: product.item_id, display_snapshot: { model_name: product.model_name, color_name: product.color_name, customer_sku: null, length: '18', weight: '20', unit: 'piece' }, quantity: 3, unit_price: '27.0000', discount_amount: '0.00', line_amount: '81.00', unit_weight_grams: '20', inventory_observed_at: '2026-10-19T10:00:00' }] }, 201)
    }
    if (path.endsWith('/orders')) return send({ request_id: '44444444-4444-4444-8444-444444444444', request_no: 'POR-TEST-001', status: 'ready_for_review', row_version: 1, replayed: false, submitted_at: '2026-10-19T10:00:00', currency: 'USD', product_amount: '81.00', total_amount: '127.05' }, 201)
    throw new Error(`Unexpected request: ${path}`)
  })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto(origin + '/collection')
    await page.getByRole('button', { name: 'View Genius Weft, #2' }).click()
    await page.getByRole('dialog').getByLabel('Quantity').fill('3')
    await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
    await page.getByRole('button', { name: 'Review selection', exact: true }).click()
    await page.getByRole('heading', { name: 'Your selection.' }).waitFor()
    for (const [label, value] of [['Contact name', 'Test buyer'], ['Phone number', '+44 1000000'], ['Address line 1', '1 Test Street'], ['Country code (e.g. US, GB)', 'GB']]) await page.getByLabel(label, { exact: true }).fill(value)
    const paypal = page.getByRole('radio', { name: /PayPal/ })
    await paypal.waitFor()
    assert.equal(await page.getByRole('radio', { name: /Bank transfer/ }).isChecked(), true)
    await page.getByRole('button', { name: 'Review request' }).click()
    const review = page.getByRole('complementary', { name: 'Server review' })
    await review.getByText('USD 121.00').waitFor()
    assert.ok(await review.getByText('60 g').isVisible())
    assert.equal(await review.getByText('Payment surcharge').count(), 0)
    await paypal.check()
    // Changing the method discards the previous review until it is refreshed.
    await page.getByRole('button', { name: 'Review request' }).click()
    await review.getByText('USD 127.05').waitFor()
    assert.ok(await review.getByText('Payment surcharge (PayPal 5%)').isVisible())
    assert.equal(quotes.at(-1).payment_term_code, 'paypal')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    if (viewport.width > 1000) {
      const draft = page.getByRole('region', { name: 'Selection and delivery' })
      const positions = () => page.evaluate(() => ({ left: document.querySelector('.checkout-draft').scrollTop, right: document.querySelector('.checkout-review').scrollTop, outer: window.scrollY }))
      for (const height of [900, 640]) {
        await page.setViewportSize({ width: viewport.width, height })
        await page.evaluate(() => { document.querySelector('.checkout-draft').scrollTop = 0; document.querySelector('.checkout-review').scrollTop = 0 })
        for (const pane of [draft, review]) assert.ok(await pane.evaluate(el => el.scrollHeight > el.clientHeight), 'pane has scrollable content')
        const leftBox = await draft.boundingBox(), rightBox = await review.boundingBox()
        assert.ok(Math.abs(leftBox.height - rightBox.height) < 10)
        for (const box of [leftBox, rightBox]) {
          assert.ok(box.height >= height - 200, 'checkout panes leave at most 200px for navigation, title and footer')
          assert.ok(box.y <= 140, 'checkout content starts near the navigation')
        }
        assert.ok(leftBox.y + leftBox.height <= height && rightBox.y + rightBox.height <= height)
        await writeFile(`${output}/checkout-geometry-${height}.json`, JSON.stringify({ viewport: { width: viewport.width, height }, left: leftBox, right: rightBox }, null, 2))
        await page.screenshot({ animations: 'disabled', path: `${output}/checkout-top-${height}.png` })
        const before = await positions()
        await page.mouse.move(leftBox.x + leftBox.width / 2, leftBox.y + leftBox.height / 2)
        await page.mouse.wheel(0, 400)
        await page.waitForFunction(() => document.querySelector('.checkout-draft').scrollTop > 0)
        const afterLeft = await positions()
        assert.equal(afterLeft.right, before.right); assert.equal(afterLeft.outer, 0)
        await page.mouse.move(rightBox.x + rightBox.width / 2, rightBox.y + rightBox.height / 2)
        await page.mouse.wheel(0, 400)
        await page.waitForFunction(() => document.querySelector('.checkout-review').scrollTop > 0)
        const afterRight = await positions()
        assert.equal(afterRight.left, afterLeft.left); assert.equal(afterRight.outer, 0)
        await page.evaluate(() => { const el = document.querySelector('.checkout-review'); el.scrollTop = el.scrollHeight })
        await page.mouse.wheel(0, 1000)
        assert.equal((await positions()).outer, 0)
        await page.screenshot({ animations: 'disabled', path: `${output}/checkout-independent-${height}.png` })
      }
    } else {
      assert.equal(await page.locator('.checkout-draft').evaluate(el => getComputedStyle(el).overflowY), 'visible')
    }
    await page.screenshot({ animations: 'disabled', path: `${output}/checkout-fees-${name}.png`, fullPage: true })
    await review.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Notify my representative to place the order' }).click()
    await page.getByText('issue the formal PI').waitFor()
    assert.ok(await page.getByText('Total USD 127.05').isVisible())
    assert.deepEqual(errors, [])
  } catch (error) { await page.screenshot({ path: `${output}/checkout-fees-${name}-failure.png`, fullPage: true }); throw error } finally { await browser.close() }
}
await run({ width: 1440, height: 1100 }, 'desktop')
await run({ width: 375, height: 812 }, 'mobile')
console.log('checkout fee browser checks passed')
