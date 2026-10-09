import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
const [origin, modulePath, executablePath, fixture, output] = process.argv.slice(2)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = [], external = []
const id = '22222222-2222-4222-8222-222222222222'
let imageUrl = `/api/portal/v1/catalog/${id}/image?version=1`, fail = false
page.on('pageerror', e => errors.push(e.message))
await context.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.origin !== origin) { external.push(url.href); return route.abort() }
  if (!url.pathname.startsWith('/api/')) return route.continue()
  if (url.pathname.endsWith('/image')) return fail ? route.fulfill({ status: 404, json: { code: 404 } }) : route.fulfill({ contentType: 'image/jpeg', body: readFileSync(fixture), headers: { 'Cache-Control': 'no-store' } })
  let data
  if (url.pathname.endsWith('/session')) data = { me: { account_public_id: id, company_display_name: 'Image QA' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'synthetic' }
  else if (url.pathname.endsWith('/catalog')) data = { items: [{ item_id: id, model_name: 'Silk Weft', color_name: 'Brown', category: 'hair', image_url: imageUrl, unit_price: '30.00', sale_unit: 'pack', availability: 'available', min_order_qty: 1, step_qty: 1 }], total: 1 }
  else throw new Error('Unexpected API ' + url.pathname)
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
try {
  await page.goto(origin)
  await page.locator('.product-photo').waitFor()
  await page.waitForFunction(() => document.querySelector('.product-photo')?.naturalWidth === 80)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1))
    assert.ok(await page.locator('.product-photo').evaluate(el => { const image = el.getBoundingClientRect(), card = el.closest('.product-art').getBoundingClientRect(); return image.left >= card.left - 1 && image.top >= card.top - 1 && image.right <= card.right + 1 && image.bottom <= card.bottom + 1 && image.height < window.innerHeight }))
    await page.screenshot({ animations: 'disabled', path: `${output}/image-customer-${width}.png` })
  }
  fail = true; await page.reload()
  await page.locator('.product-monogram').waitFor()
  assert.equal(await page.locator('.product-photo').count(), 0)
  imageUrl = 'https://untrusted.example/image.jpg'; await page.reload()
  await page.locator('.product-monogram').waitFor()
  assert.deepEqual(external, [])
  imageUrl = `/api/portal/v1/catalog/${id}/image?version=2`; fail = false
  await page.reload(); await page.locator('.product-photo').waitFor()
  await page.waitForFunction(() => document.querySelector('.product-photo')?.naturalWidth === 80)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', scope: 'Real built customer UI with mocked APIs', checks: ['authorized relative image loads', '1440/390/320', '404 fallback', 'external URL never requested', 'new image version loads'] }))
} finally { await browser.close() }
