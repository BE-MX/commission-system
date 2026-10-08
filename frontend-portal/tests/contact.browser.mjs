import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = []
page.on('pageerror', error => errors.push(error.message))
let contact = { display_name: 'April', email: 'april@example.com', whatsapp: '+8613800000000' }, denied = false
await context.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname
  let data = {}, status = 200
  if (path.endsWith('/session')) data = { me: { account_public_id: '11111111-1111-4111-8111-111111111111', company_display_name: 'Contact QA' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'test-csrf' }
  else if (path.endsWith('/catalog')) data = { items: [], total: 0, page: 1, page_size: 24 }
  else if (path.endsWith('/sales-contact')) { data = denied ? { error_code: 'AUTH_REQUIRED' } : { contact }; status = denied ? 401 : 200 }
  else throw new Error('Unexpected API: ' + path)
  return route.fulfill({ status, json: { code: status, message: status === 200 ? 'ok' : 'Please sign in again.', data } })
})
try {
  await page.goto(origin)
  await page.getByRole('button', { name: 'Contact your representative', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Your LeShine representative', exact: true })
  await dialog.getByRole('heading', { name: 'April', exact: true }).waitFor()
  assert.equal(await dialog.getByRole('link', { name: 'Email April' }).getAttribute('href'), 'mailto:april%40example.com')
  assert.equal(await dialog.getByRole('link', { name: 'Chat on WhatsApp' }).getAttribute('href'), 'https://wa.me/8613800000000')
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await dialog.screenshot({ animations: 'disabled', path: `${output}/contact-${width}.png` })
  }
  contact = null
  await dialog.getByRole('button', { name: 'Refresh contact' }).click()
  await dialog.getByText('Your representative’s contact details are not available here yet.', { exact: false }).waitFor()
  assert.equal(await dialog.getByRole('link').count(), 0)
  contact = { display_name: 'Bella', email: 'bella@example.com', whatsapp: null }
  await dialog.getByRole('button', { name: 'Refresh contact' }).click()
  await dialog.getByRole('heading', { name: 'Bella', exact: true }).waitFor()
  assert.equal(await dialog.getByRole('link', { name: 'Email April' }).count(), 0)
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.equal(await page.getByRole('button', { name: 'Contact your representative' }).evaluate(el => el === document.activeElement), true)
  await page.getByRole('button', { name: 'Contact your representative' }).click()
  await dialog.getByRole('heading', { name: 'Bella', exact: true }).waitFor()
  denied = true
  await dialog.getByRole('button', { name: 'Refresh contact' }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert.equal(await page.getByText('bella@example.com', { exact: false }).count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', scope: 'mocked APIs; real built customer UI', checks: ['links', '1440/390/320', 'approval withdrawal empty state', 'current owner replacement', 'escape focus', 'expired session clears contact'] }))
} finally { await browser.close() }
