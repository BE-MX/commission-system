import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3226'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || '../tmp/portal-customer-experience/customer'
await mkdir(output, { recursive: true })
const id = n => `${String(n).padStart(8, '0')}-1111-4111-8111-111111111111`
const image = n => `/api/portal/v1/catalog/swatches/${id(n)}/image?version=1&size=thumb`
const identity = { me: { account_public_id: id(99), company_display_name: 'Synthetic Independent Buyer' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'synthetic-csrf' }
const variants = [1, 2, 3, 4, 5, 6].map(n => ({ item_id: id(n), model_name: 'Genius Weft', color_name: n === 1 ? '#2B' : `#${n}`, color_code: n === 1 ? '#2B' : `#${n}`, color_key: String(n), color_label: n === 1 ? '#2B' : `#${n}`, color_type: 'solid', grade: 'standard', grade_label: 'Standard Double Drawn', length: '16', length_display: '16', unit_weight_grams: '20', unit_price: '17.22', sale_unit: 'piece', min_order_qty: 1, step_qty: 1, availability: 'available', swatch_url: n === 2 ? null : image(n), image_url: n === 2 ? `/api/portal/v1/catalog/${id(n)}/image?version=1` : null }))

for (const width of [1440, 375]) {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PORTAL_CHROMIUM })
  const context = await browser.newContext({ viewport: { width, height: 900 } })
  let delivery = null, version = 1, writes = 0, lose = false, active = 0, maximum = 0, thumbAttempts = 0
  const order = [], errors = [], quotes = []
  await context.route('**/api/portal/v1/**', async route => {
    const request = route.request(), url = new URL(request.url())
    const send = (data, status = 200) => route.fulfill({ status, json: { code: status, message: 'OK', data } })
    if (url.pathname.endsWith('/image')) {
      active++; maximum = Math.max(maximum, active); order.push(url.searchParams.get('size'))
      try {
        await new Promise(resolve => setTimeout(resolve, 30))
        if (url.pathname.includes(id(1)) && url.searchParams.get('size') === 'thumb' && ++thumbAttempts === 1) return await send({}, 503)
        const dimension = url.searchParams.get('size') === 'full' ? 1200 : 96
        return await route.fulfill({ contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="${dimension}" height="${dimension}"><rect width="100%" height="100%" fill="sienna"/></svg>` })
      } finally { active-- }
    }
    if (url.pathname.endsWith('/session')) return send(identity)
    if (url.pathname.endsWith('/sales-contact')) return send({ contact: null })
    if (url.pathname.endsWith('/delivery-profile')) {
      if (request.method() === 'PUT') {
        assert.equal(request.headers()['x-portal-csrf'], 'synthetic-csrf')
        assert.equal(request.headers()['if-match'], `"${version}"`)
        delivery = request.postDataJSON().delivery; version++; writes++
        if (lose) { lose = false; return route.abort('failed') }
      }
      return send({ delivery, row_version: version })
    }
    if (url.pathname.endsWith('/ordering-terms')) return send({ payment_terms: [], auto_fees: { enabled: false } })
    if (url.pathname.endsWith('/quotes')) {
      const body = request.postDataJSON(); quotes.push(body)
      return send({ quote_id: id(80), status: 'valid', content_hash: 'a'.repeat(64), currency: 'USD', expires_at: new Date(Date.now() + 600000).toISOString(), product_amount: '206.64', total_amount: null, fees: { status: 'pending' }, delivery: body.delivery, payment_terms_snapshot: {}, items: [{ item_id: id(1), display_snapshot: { model_name: 'Genius Weft', color_name: '#2B', length: '16', weight: '20g', unit: 'piece' }, quantity: 12, unit_price: '17.22', line_amount: '206.64' }] })
    }
    if (url.pathname.endsWith('/catalog/families/genius_weft_20g/availability')) return send({ items: [] })
    if (url.pathname.endsWith('/catalog/families/genius_weft_20g')) return send({ code: 'genius_weft_20g', display_name: 'Genius Weft 20g/piece', variants })
    throw new Error(`Unexpected API ${request.method()} ${url.pathname}`)
  })
  const page = await context.newPage()
  page.on('pageerror', problem => errors.push(problem.message))
  const noOverflow = async () => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  try {
    await page.goto(origin + '/delivery-details')
    await page.getByLabel('Contact name', { exact: true }).fill('Saved buyer')
    await page.getByLabel('Phone number', { exact: true }).fill('12345678')
    await page.getByLabel('Address line 1', { exact: true }).fill('Saved address 1')
    await page.getByLabel('Country code (e.g. US, GB)', { exact: true }).fill('')
    await page.getByRole('button', { name: 'Save delivery details', exact: true }).click()
    await page.getByText('Your delivery details are saved.', { exact: true }).waitFor()
    assert.equal(delivery.country_code, ''); assert.equal(writes, 1, 'partial saved address must not be blocked by missing country')
    await noOverflow()
    await page.screenshot({ path: `${output}/delivery-details-${width}.png`, fullPage: true })
    await page.reload()
    await page.waitForFunction(() => document.querySelector('input[name="contact_name"]')?.value === 'Saved buyer')
    await page.getByLabel('Address line 1', { exact: true }).fill('Updated address')
    await page.getByLabel('Country code (e.g. US, GB)', { exact: true }).fill('us')
    lose = true
    await page.getByRole('button', { name: 'Save delivery details', exact: true }).click()
    await page.getByRole('button', { name: 'Check saved details' }).click()
    await page.getByText('Your delivery details are saved.', { exact: true }).waitFor()
    assert.equal(writes, 2, 'lost response is resolved by GET, without another write')
    assert.equal(delivery.country_code, 'US')
    await page.goto(origin + '/collection/genius_weft_20g')
    await page.waitForFunction(() => document.querySelector('.family-image img')?.naturalWidth === 1200)
    const shade = page.getByRole('button', { name: '#2B, In stock', exact: true })
    await shade.locator('img').waitFor()
    assert.equal(thumbAttempts, 2, '503 thumbnail gets exactly one retry')
    assert.equal(order[0], 'full', 'gallery gets the first queue slot')
    assert.ok(maximum <= 2, 'image requests stay bounded')
    await page.getByRole('button', { name: '#2, In stock', exact: true }).locator('img').waitFor()
    assert.match(await page.getByRole('button', { name: '#2, In stock', exact: true }).locator('img').getAttribute('data-source'), /\/catalog\/[^/]+\/image\?version=1&size=thumb$/)
    await page.getByRole('spinbutton', { name: 'Quantity', exact: true }).fill('3')
    await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
    const panel = page.getByRole('complementary', { name: 'Your selection' })
    const quantity = panel.getByRole('spinbutton', { name: 'Quantity for Genius Weft, #2B', exact: true })
    await quantity.fill('12'); await quantity.press('Tab')
    await panel.getByText('240 g', { exact: true }).first().waitFor()
    await quantity.fill('0'); await quantity.press('Tab')
    assert.equal(await quantity.inputValue(), '12')
    await panel.getByRole('alert').waitFor()
    await noOverflow()
    await page.screenshot({ path: `${output}/quantity-${width}.png`, fullPage: true })
    await panel.getByRole('button', { name: 'Finish selection' }).click()
    await page.waitForFunction(() => document.querySelector('input[autocomplete="address-line1"]')?.value === 'Updated address')
    assert.equal(await page.getByLabel('Contact name', { exact: true }).inputValue(), 'Saved buyer')
    assert.equal(await page.locator('.delivery-details').getAttribute('open'), null)
    await page.getByText('Delivery address (optional)', { exact: true }).click()
    await page.getByLabel('Address line 1', { exact: true }).fill('One-off address')
    await page.getByRole('button', { name: 'Manage saved delivery details' }).click()
    await page.getByRole('link', { name: /^Selection/ }).click()
    assert.equal(await page.getByLabel('Address line 1', { exact: true }).inputValue(), 'One-off address')
    // Browser autofill may change the visible value without sending an input event.
    await page.getByLabel('Address line 1', { exact: true }).evaluate(el => { el.value = 'Autofilled visible address' })
    await page.getByRole('button', { name: 'Review request', exact: true }).click()
    await page.getByRole('complementary', { name: 'Server review' }).getByText('Autofilled visible address').waitFor()
    assert.equal(quotes.at(-1).delivery.address_line1, 'Autofilled visible address')
    await noOverflow()
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ width, status: 'pass', maximumImageConcurrency: maximum, profileWrites: writes, thumbAttempts }))
  } finally { await browser.close() }
}
