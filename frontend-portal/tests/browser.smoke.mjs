import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'

// A caller may select the bundled Playwright runtime without adding it to the app.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || 'tmp/browser-qa'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.PORTAL_CHROMIUM ? { executablePath: process.env.PORTAL_CHROMIUM } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const errors = [], calls = []
let signedIn = false, failLogout = false, catalogMode = 'normal'
const identity = { me: { account_public_id: '11111111-1111-4111-8111-111111111111', company_display_name: 'Atelier Test Salon', contact_display_name: 'Test buyer' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'test-csrf' }
const products = ['Genius Weft', 'Invisible Tape', 'Flat Weft', 'Micro Beads', 'Silk Weft', 'Tape Replacement'].map((model, i) => ({ item_id: `${i + 1}1111111-1111-4111-8111-111111111111`, category: i === 3 ? 'accessory' : 'hair', model_name: model, color_name: ['Midnight','Champagne','Cocoa','Natural','Sandy Blonde','Warm Sand'][i], customer_sku: `TEST-${i + 1}`, length_display: '20 in', weight_display: '20 g', sale_unit: 'pack', min_order_qty: 1, step_qty: 1, unit_price: i === 5 ? null : '27.0000', price_status: i === 5 ? 'unavailable' : 'available', availability: i === 2 ? 'unknown' : i === 4 ? 'unavailable' : 'available' }))
await context.route('**/api/portal/v1/**', async route => {
  const request = route.request(), url = new URL(request.url())
  calls.push({ path: url.pathname, method: request.method(), body: request.postDataJSON(), headers: request.headers() })
  const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status, message: status >= 400 ? 'Please try again.' : 'OK', data }) })
  if (url.pathname.endsWith('/session')) return send(signedIn ? identity : { error_code: 'AUTH_REQUIRED' }, signedIn ? 200 : 401)
  if (url.pathname.endsWith('/bootstrap')) return send({ csrf_token: 'test-preauth', expires_in: 600 })
  if (url.pathname.endsWith('/challenges')) return send({ challenge_id: identity.me.account_public_id, expires_in: 600, resend_after: 60 }, 202)
  if (url.pathname.endsWith('/verify')) {
    if (request.postDataJSON().code !== '123456') return send({ error_code: 'AUTH_FAILED' }, 401)
    signedIn = true; return send(identity)
  }
  if (url.pathname.endsWith('/logout')) {
    if (failLogout) { failLogout = false; return route.abort('failed') }
    signedIn = false; return send({ signed_out: true })
  }
  if (url.pathname.endsWith('/catalog')) {
    if (catalogMode === 'failed') return send({ error_code: 'TEMPORARILY_UNAVAILABLE' }, 503)
    const term = (url.searchParams.get('keyword') || '').toLowerCase()
    let items = products.filter(p => `${p.model_name} ${p.color_name}`.toLowerCase().includes(term))
    if (url.searchParams.get('in_stock_only') === 'true') items = items.filter(p => p.availability === 'available')
    return send({ items, total: items.length, page: 1, page_size: 24, facets: { categories: ['hair','accessory'], colors: [] }, catalog_version: 1, mapping_version: 1 })
  }
  throw new Error(`Unexpected request: ${url.pathname}`)
})

async function noOverflow(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
}
const page = await context.newPage()
page.on('pageerror', error => errors.push(error.message))
try {
  await page.goto(origin)
  await page.getByRole('button', { name: 'Continue with email' }).waitFor()
  await noOverflow(page)
  await page.screenshot({ path: `${output}/login-desktop.png`, fullPage: true })
  await page.getByLabel('Email address').fill('test@example.test')
  await page.getByRole('button', { name: 'Continue with email' }).click()
  await page.getByLabel('Verification code').fill('000000')
  await page.getByRole('button', { name: 'Enter your collection' }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByLabel('Verification code').inputValue(), '')
  await page.getByLabel('Verification code').fill('123456')
  await page.getByRole('button', { name: 'Enter your collection' }).click()
  await page.getByRole('heading', { name: 'Your next signature.' }).waitFor()
  await page.getByRole('button', { name: 'View Genius Weft, Midnight' }).waitFor()
  assert.equal(await page.locator('.product-card').count(), 6)
  await page.screenshot({ path: `${output}/collection-desktop.png`, fullPage: true })
  await page.getByRole('button', { name: 'View Genius Weft, Midnight' }).click()
  await page.getByRole('dialog').waitFor()
  await page.keyboard.press('Tab')
  assert.equal(await page.evaluate(() => document.querySelector('dialog').contains(document.activeElement)), true)
  await page.keyboard.press('Escape')
  assert.equal(await page.getByRole('button', { name: 'View Genius Weft, Midnight' }).evaluate(el => el === document.activeElement), true)
  await page.getByRole('checkbox', { name: 'Available only' }).check()
  await page.waitForFunction(() => document.querySelectorAll('.product-card').length === 4)
  await page.getByRole('searchbox').fill('nothing-matches')
  await page.getByRole('heading', { name: 'No matches just yet.' }).waitFor()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await page.getByRole('button', { name: 'View Genius Weft, Midnight' }).waitFor()
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    await noOverflow(page)
    await page.screenshot({ path: `${output}/collection-${width}.png`, fullPage: true })
    await page.getByRole('button', { name: 'View Genius Weft, Midnight' }).click()
    await page.getByRole('dialog').waitFor()
    await noOverflow(page)
    await page.screenshot({ path: `${output}/product-${width}.png` })
    await page.getByRole('button', { name: 'Close product' }).click()
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
  assert.equal(await page.getByRole('button', { name: 'Sign out', exact: true }).evaluate(el => getComputedStyle(el).transitionDuration), '0s')
  catalogMode = 'failed'
  await page.getByRole('searchbox').fill('Genius')
  await page.getByRole('heading', { name: 'We couldn’t load your collection.' }).waitFor()
  catalogMode = 'normal'
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.getByRole('button', { name: 'View Genius Weft, Midnight' }).waitFor()
  failLogout = true
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.getByRole('heading', { name: 'Sign-out needs another try.' }).waitFor()
  assert.equal(await page.locator('.product-card').count(), 0)
  await page.getByRole('button', { name: 'Try again' }).click()
  await page.getByRole('button', { name: 'Continue with email' }).waitFor()
  await noOverflow(page)
  await page.screenshot({ path: `${output}/login-mobile.png`, fullPage: true })
  const invitation = 'x'.repeat(48)
  await page.goto(`${origin}/activate#token=${invitation}`)
  await page.getByRole('button', { name: 'Continue with email' }).waitFor()
  assert.equal(new URL(page.url()).hash, '')
  assert.equal(new URL(page.url()).search, '')
  await page.getByLabel('Email address').fill('test@example.test')
  await page.getByRole('button', { name: 'Continue with email' }).click()
  await page.getByLabel('Verification code').fill('123456')
  await page.getByRole('button', { name: 'Activate your access' }).click()
  await page.getByRole('heading', { name: 'Your next signature.' }).waitFor()
  assert.ok(calls.some(call => call.body?.purpose === 'activate' && call.body.invitation_token === invitation))
  const other = await context.newPage()
  await other.goto(origin)
  await other.getByRole('heading', { name: 'Your next signature.' }).waitFor()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.getByRole('button', { name: 'Continue with email' }).waitFor()
  await other.getByRole('button', { name: 'Continue with email' }).waitFor()
  assert.equal(await other.locator('.product-card').count(), 0)
  await other.close()
  const posts = calls.filter(call => call.method === 'POST')
  assert.ok(posts.every(call => call.headers['x-portal-csrf']))
  assert.ok(posts.every(call => !call.headers.authorization))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', scope: 'Built frontend with intercepted test API only; no backend or production traffic', assertions: ['login + incorrect OTP recovery', 'catalog/filter/empty/failure retry', 'dialog keyboard + return focus', '1440/390/320 responsive layout', 'reduced motion', 'failed signout recovery', 'invitation URL cleanup + activation', 'two-tab signout invalidation', 'CSRF and no employee authorization'], screenshots: output, apiCalls: calls.length }))
} finally { await browser.close() }
