import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'

// Family browsing: grid -> detail -> selectors -> add -> mini selection, desktop and 375px.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || 'tmp/browser-qa'
await mkdir(output, { recursive: true })
const identity = { me: { account_public_id: '11111111-1111-4111-8111-111111111111', company_display_name: 'Atelier Test Salon', contact_display_name: 'Test buyer' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'test-csrf' }
const id = n => `${String(n).padStart(8, '0')}-1111-4111-8111-111111111111`
const variant = (n, grade, length, color, type, availability = 'available', stock = '100+') => ({ item_id: id(n), category: 'hair', model_name: 'Genius Weft', color_name: color, customer_sku: null, length_display: length, weight_display: '20', sale_unit: 'piece', image_url: null, availability, inventory_observed_at: availability === 'unknown' ? null : '2026-10-19T10:00:00', stock_display: availability === 'available' ? stock : null, min_order_qty: 1, step_qty: 1, currency: 'USD', unit_price: '27.3500', price_status: 'available', grade, grade_label: grade === 'super' ? 'Super Double Drawn' : 'Standard Double Drawn', length, color_key: color.toLowerCase().replace('#', '').replace('/', '-'), color_code: color, color_label: color === '#9ATP9A/613' ? 'Rose Golden' : color, color_type: type, swatch_url: null, unit_weight_grams: '20' })
const variants = [variant(1, 'standard', '18', '#2', 'solid'), variant(2, 'super', '18', '#2', 'solid', 'available', '42'), variant(3, 'super', '18', '#P2/8', 'piano', 'unavailable'), variant(4, 'super', '18', '#9ATP9A/613', 'balayage'), variant(5, 'super', '20', '#2', 'solid')]
let polls = 0
async function run(viewport, name) {
  const browser = await chromium.launch({ headless: true, ...(process.env.PORTAL_CHROMIUM ? { executablePath: process.env.PORTAL_CHROMIUM } : {}) })
  const context = await browser.newContext({ viewport })
  const errors = []
  await context.route('**/api/portal/v1/**', async route => {
    const url = new URL(route.request().url())
    const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status, message: 'OK', data }) })
    if (url.pathname.endsWith('/session')) return send(identity)
    if (url.pathname.endsWith('/sales-contact')) return send({ assigned: false })
    if (url.pathname.endsWith('/catalog/families')) return send({ items: [{ code: 'genius_weft_20g', display_name: 'Genius Weft 20g/piece', sale_unit: 'piece', unit_weight_grams: '20', min_order_qty: 1, step_qty: 1, image_url: null, variant_count: 5, grades: ['standard', 'super'], lengths: ['18', '20'] }], ungrouped_count: 2, catalog_version: 1 })
    if (url.pathname.endsWith('/catalog/families/genius_weft_20g/availability')) { polls++; return send({ items: [], catalog_version: 1 }) }
    if (url.pathname.endsWith('/catalog/families/genius_weft_20g')) return send({ code: 'genius_weft_20g', display_name: 'Genius Weft 20g/piece', sale_unit: 'piece', unit_weight_grams: '20', min_order_qty: 1, step_qty: 1, grades: ['standard', 'super'], variants, catalog_version: 1, mapping_version: 1 })
    if (url.pathname.endsWith('/catalog')) return send({ items: [], total: 0, page: 1, page_size: 24, facets: { categories: [], colors: [] }, catalog_version: 1, mapping_version: 1 })
    throw new Error(`Unexpected request: ${url.pathname}`)
  })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  const noOverflow = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  try {
    await page.goto(origin + '/collection')
    await page.getByRole('heading', { name: 'Genius Weft 20g/piece' }).waitFor()
    assert.ok(await page.getByRole('heading', { name: 'Other products' }).isVisible())
    await noOverflow()
    await page.screenshot({ path: `${output}/families-${name}.png`, fullPage: true })
    await page.getByRole('link', { name: /Genius Weft 20g\/piece/ }).click()
    await page.getByRole('heading', { level: 1, name: 'Genius Weft 20g/piece' }).waitFor()
    assert.equal(new URL(page.url()).pathname, '/collection/genius_weft_20g')
    // First available grade/length/color is preselected.
    assert.equal(await page.getByRole('button', { name: 'Standard Double Drawn' }).getAttribute('aria-pressed'), 'true')
    await page.getByRole('button', { name: 'Super Double Drawn' }).click()
    assert.ok(await page.getByText('42 in stock').isVisible())
    await page.getByRole('button', { name: /#9ATP9A\/613/ }).click()
    assert.ok(await page.getByText('Rose Golden').isVisible())
    assert.ok(await page.getByText('Balayage').isVisible())
    await page.getByRole('button', { name: /#P2\/8/ }).click()
    assert.ok(await page.getByText('Out of stock').first().isVisible())
    assert.equal(await page.getByRole('button', { name: 'Add to selection' }).count(), 0)
    await page.getByRole('button', { name: /#9ATP9A\/613/ }).click()
    await page.getByRole('button', { name: 'Increase quantity' }).click()
    await page.getByRole('button', { name: 'Increase quantity' }).click()
    assert.equal(await page.getByRole('spinbutton', { name: 'Quantity' }).inputValue(), '3')
    await page.getByRole('button', { name: 'Add to selection' }).click()
    const panel = page.getByRole('complementary', { name: 'Your selection' })
    await panel.getByText('#9ATP9A/613').first().waitFor()
    assert.ok(await panel.getByText('60 g').first().isVisible())
    await panel.getByRole('button', { name: /^Increase Genius Weft/ }).click()
    assert.ok(await panel.getByText('80 g').first().isVisible())
    await noOverflow()
    await page.screenshot({ path: `${output}/family-detail-${name}.png`, fullPage: true })
    await panel.getByRole('button', { name: 'Finish selection' }).click()
    await page.waitForURL(/\/checkout$/)
    assert.deepEqual(errors, [])
  } finally { await browser.close() }
}
await run({ width: 1440, height: 1000 }, 'desktop')
await run({ width: 375, height: 812 }, 'mobile')
console.log(`family browser checks passed (availability polls observed: ${polls})`)
