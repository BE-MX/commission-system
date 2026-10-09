import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
const page = await context.newPage(), errors = [], quotes = []
page.on('pageerror', e => errors.push(e.message))
const products = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'].map((id, i) => ({ item_id: id, model_name: i ? 'Withdrawn Weft' : 'Available Weft', color_name: 'Brown', length_display: '20', weight_display: '20g', sale_unit: 'pack', category: 'hair', availability: 'available', unit_price: '30.0000', min_order_qty: 1, step_qty: 1 }))
await context.route('**/api/**', async route => {
  const req = route.request(), path = new URL(req.url()).pathname
  let data
  if (path.endsWith('/session')) data = { me: { account_public_id: products[0].item_id, company_display_name: 'Recovery QA' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'synthetic' }
  else if (path.endsWith('/catalog')) data = { items: products, total: 2 }
  else if (path.endsWith('/quotes')) {
    const body = req.postDataJSON(); quotes.push(body)
    if (body.items.some(line => line.item_id === products[1].item_id)) return route.fulfill({ status: 404, json: { code: 404, message: 'Remove the unavailable products marked in your selection and review again.', data: { error_code: 'RESOURCE_NOT_FOUND', issues: [{ item_id: products[1].item_id, code: 'ITEM_UNAVAILABLE' }] } } })
    data = { ...body, quote_id: '33333333-3333-4333-8333-333333333333', content_hash: 'a'.repeat(64), status: 'valid', expires_at: '2099-01-01T12:00:00', currency: 'USD', product_amount: '30.00', total_amount: null, fees: { status: 'pending' }, payment_terms_snapshot: { display_text: 'Prepaid' }, items: body.items.map(line => ({ ...line, unit_price: '30.0000', line_amount: '30.00', display_snapshot: { model_name: products[0].model_name, color_name: 'Brown', length: '20', weight: '20g', unit: 'pack' } })) }
  } else throw new Error('Unexpected API ' + path)
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
try {
  await page.goto(origin)
  for (const product of products) {
    await page.getByRole('button', { name: `View ${product.model_name}, Brown`, exact: true }).click()
    await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
    await page.getByRole('button', { name: 'Close product', exact: true }).click()
  }
  await page.getByRole('link', { name: /^Selection/ }).click()
  await page.getByLabel('Contact name', { exact: true }).fill('Buyer')
  await page.getByLabel('Phone number').fill('+44 123456')
  await page.getByLabel('Address line 1', { exact: true }).fill('10 Test Lane')
  await page.getByLabel('Country code (e.g. US, GB)').fill('GB')
  await page.getByLabel('Your PO').fill('KEEP-PO')
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  const withdrawn = page.locator('.cart-line').filter({ hasText: 'Withdrawn Weft' })
  await withdrawn.getByText('No longer available.', { exact: false }).waitFor()
  assert.equal(await withdrawn.getByRole('spinbutton').isDisabled(), true)
  assert.equal(await page.locator('.cart-line').filter({ hasText: 'Available Weft' }).getByRole('spinbutton').isDisabled(), false)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1100 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
    await page.locator('.checkout-draft > .checkout-card').first().screenshot({ path: `${output}/unavailable-${width}.png`, animations: 'disabled' })
  }
  await withdrawn.getByRole('button', { name: 'Remove Withdrawn Weft', exact: true }).click()
  assert.equal(await page.getByLabel('Address line 1', { exact: true }).inputValue(), '10 Test Lane')
  assert.equal(await page.getByLabel('Your PO').inputValue(), 'KEEP-PO')
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.getByRole('button', { name: 'Submit order request', exact: true }).waitFor()
  assert.equal(quotes.length, 2)
  assert.deepEqual(quotes[1].items, [{ item_id: products[0].item_id, quantity: 1 }])
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', checks: ['two items selected', 'only unavailable row marked', 'quantity disabled', '1440/390/320', 'remove preserves delivery and PO', 'fresh quote succeeds'] }))
} finally { await browser.close() }
