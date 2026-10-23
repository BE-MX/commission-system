import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3291'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || 'tmp/portal-oil-ui/after'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.PORTAL_CHROMIUM })
const id = '11111111-1111-4111-8111-111111111111'
const identity = { me: { account_public_id: id, company_display_name: 'Atelier Hair Studio & Extensions' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'local-test' }
const item = { item_id: id, model_name: 'Genius Weft', color_name: 'Champagne', category: 'hair', customer_sku: 'GW-CH', length_display: '22 in', weight_display: '20 g', sale_unit: 'piece', unit_price: '27.35', min_order_qty: 1, step_qty: 1, availability: 'available' }
const errors = [], results = []
try {
 for (const width of [1440, 720, 390, 320]) {
  const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
  let signedIn = false, failAccess = true, unavailable = false
  await context.route('**/api/portal/v1/**', async route => {
   const path = new URL(route.request().url()).pathname
   const send = (data, status = 200) => route.fulfill({ status, json: { code: status, message: status >= 400 ? 'Please try again.' : 'OK', data } })
   if (path.endsWith('/session') && unavailable) return send({ error_code: 'SERVICE_UNAVAILABLE' }, 503)
   if (path.endsWith('/session')) return send(signedIn ? identity : { error_code: 'AUTH_REQUIRED' }, signedIn ? 200 : 401)
   if (path.endsWith('/bootstrap')) return send({ csrf_token: 'test', expires_in: 600 })
   if (path.endsWith('/auth/login')) { signedIn = true; return send(identity) }
   if (path.endsWith('/auth/challenge')) return send({ challenge_id: id, expires_in: 600 }, 202)
   if (path.endsWith('/access-requests')) return send(failAccess ? { error_code: 'TEMPORARILY_UNAVAILABLE' } : { accepted: true }, failAccess ? 503 : 202)
   if (path.endsWith('/catalog/families')) return send({ items: [], ungrouped_count: 0 })
   if (path.endsWith('/catalog')) return send({ items: [item], total: 1, page: 1, page_size: 24 })
   if (path.endsWith('/sales-contact')) return send({ contact: { display_name: 'April', email: 'april@example.test', whatsapp: '+8613800000000' } })
   if (path.endsWith('/ordering-terms')) return send({ payment_terms: [], default_payment_term_code: null, auto_fees: { enabled: false, shipping_tiers: [] } })
   if (path.endsWith('/orders')) return send({ items: [], total: 0 })
   throw new Error('Unexpected local fixture request ' + path)
  })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  async function capture(name) {
   await page.evaluate(() => document.fonts.ready)
   assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, name + ' overflow at ' + width)
   await page.screenshot({ path: `${output}/${name}-${width}.png`, fullPage: true })
   results.push({ name, width, overflow: false })
  }
  await page.goto(origin + '/login')
  await page.getByLabel('Email address', { exact: true }).waitFor()
  await capture('login')
  await page.getByRole('button', { name: 'Request customer portal access', exact: true }).click()
  await page.getByRole('heading', { name: /customer portal access/ }).waitFor()
  await capture('access')
  await page.getByLabel('Full name').fill('Morgan Smith')
  await page.getByLabel('Phone number').fill('+44 123456789')
  await page.getByLabel('Email address', { exact: true }).fill('morgan@example.test')
  await page.getByRole('button', { name: /Request access/ }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByLabel('Full name').inputValue(), 'Morgan Smith')
  await capture('access-error')
  failAccess = false
  await page.getByRole('button', { name: /Request access/ }).click()
  await page.getByRole('heading', { name: 'Request received.' }).waitFor()
  await capture('access-success')
  await page.goto(origin + '/activate#token=local-fixture-only')
  await page.getByRole('heading', { name: 'Set your portal password.' }).waitFor()
  assert.equal(page.url(), origin + '/activate')
  await capture('activate')
  await page.getByLabel('Email address', { exact: true }).fill('morgan@example.test')
  await page.getByRole('button', { name: 'Send verification code' }).click()
  await page.getByLabel('New password').waitFor()
  await capture('activate-code')
  await page.goto(origin + '/activate?token=local-fixture-only')
  await page.getByRole('button', { name: 'Send verification code' }).waitFor()
  assert.equal(page.url(), origin + '/activate')
  await page.goto(origin + '/activate')
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByRole('button', { name: 'Send verification code' }).isDisabled(), true)
  await capture('activate-incomplete')
  signedIn = true
  await page.goto(origin + '/collection')
  await page.getByRole('button', { name: 'View Genius Weft, Champagne' }).waitFor()
  await capture('collection')
  await page.getByRole('button', { name: 'View Genius Weft, Champagne' }).click()
  await page.getByRole('dialog').waitFor()
  await capture('product-dialog')
  await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
  await page.getByRole('button', { name: 'Review selection', exact: true }).click()
  await page.getByLabel('Contact name', { exact: true }).waitFor()
  await capture('checkout')
  await page.getByRole('link', { name: 'Requests', exact: true }).click()
  await page.getByRole('heading', { name: 'Your next chapter starts here.' }).waitFor()
  await capture('orders-empty')
  await page.getByRole('button', { name: 'Contact your representative' }).click()
  await page.getByRole('heading', { name: 'April', exact: true }).waitFor()
  await capture('contact')
  await page.keyboard.press('Escape')
  assert.equal(await page.getByRole('dialog').isVisible(), false)
  unavailable = true
  await page.goto(origin + '/collection')
  await page.getByRole('heading', { name: 'We’ll be right with you.' }).waitFor()
  await capture('unavailable')
  await context.close()
 }
 assert.deepEqual(errors, [])
 await writeFile(`${output}/coverage.json`, JSON.stringify({ scope: 'Local actual Vue application with intercepted synthetic API; 720px models reflow of a 1440px viewport at 200%, not native browser zoom', results, errors }, null, 2))
 console.log(JSON.stringify({ status: 'pass', captures: results.length, widths: [1440, 720, 390, 320], output }))
} finally { await browser.close() }
