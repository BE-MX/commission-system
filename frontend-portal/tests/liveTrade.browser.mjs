import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const [origin, backend, modulePath, executablePath, output] = process.argv.slice(2)
let input = ''; for await (const part of process.stdin) input += part
const seed = JSON.parse(input)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } })
// Authentication itself is covered by liveAuth; this test starts with a real, seeded server session.
await context.addCookies([{ name: '__Host-portal_session', value: seed.session, domain: '127.0.0.1', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }])
const page = await context.newPage(), errors = []
page.on('pageerror', error => errors.push(error.message))
const api = origin + '/api/portal/v1', admin = backend + '/api/portal/admin/v1'
const delivery = { contact_name: 'Buyer', phone: '+44 10000000', address_line1: '10 Example Street', city: 'London', country_code: 'GB' }
async function data(response, status = 200) {
  assert.equal(response.status(), status, `Unexpected status for ${new URL(response.url()).pathname}`)
  return (await response.json()).data
}
try {
  await page.goto(origin + '/collection')
  await page.getByRole('button', { name: 'View Silk Collection, Midnight', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Quantity').fill('3')
  await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
  await page.getByRole('button', { name: 'Review selection', exact: true }).click()
  for (const [label, value] of Object.entries({ 'Contact name': delivery.contact_name, 'Phone number': delivery.phone, 'Address line 1': delivery.address_line1, City: delivery.city })) {
    await page.getByLabel(label, { exact: true }).fill(value)
  }
  await page.getByLabel('Country code').fill('GB')
  await page.getByLabel('Your PO').fill('PO-LIVE')
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.getByRole('button', { name: 'Submit order request', exact: true }).waitFor()
  assert.match(await page.getByRole('complementary', { name: 'Server review' }).innerText(), /81.00/)
  assert.equal(await page.getByRole('button', { name: 'Submit order request' }).isDisabled(), true)
  await page.getByRole('checkbox').check()
  const submitted = page.waitForResponse(r => r.url() === api + '/orders' && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Submit order request', exact: true }).click()
  const submission = await submitted, receipt = await data(submission, 201)
  assert.equal(receipt.status, 'submitted'); assert.equal(receipt.total_amount, null)
  await page.getByRole('button', { name: 'View request', exact: true }).waitFor()
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Receipt must fit narrow screens')
  }
  await page.getByRole('button', { name: 'View request', exact: true }).click()
  await page.getByRole('button', { name: 'Refresh details' }).waitFor()
  const id = receipt.request_id
  const original = submission.request()
  const replay = await data(await context.request.post(api + '/orders', { headers: { Origin: origin, 'X-Portal-CSRF': original.headers()['x-portal-csrf'], 'Idempotency-Key': original.headers()['idempotency-key'] }, data: original.postDataJSON() }), 200)
  assert.equal(replay.request_id, id); assert.equal(replay.replayed, true)
  assert.equal((await context.request.get(admin + '/orders/' + id, { headers: { 'X-Test-Actor': '2' } })).status(), 404)
  const body = { items: [{ item_id: seed.item_id, quantity: 3 }], delivery, customer_po: 'PO-LIVE', remark: '', fees: { shipping_amount: '45.00', packaging_amount: '2.00', surcharge_amount: '0.00' }, payment_terms: 'prepaid', valid_for_hours: 24, reason: 'Confirmed freight' }
  const proposal = await data(await context.request.post(admin + '/orders/' + id + '/proposals', { headers: { 'If-Match': '"1"' }, data: body }))
  assert.equal(proposal.current_state, 'awaiting_customer')
  const approval = { accepted_revision_id: proposal.original_receipt.revision_id }
  assert.equal((await context.request.post(admin + '/orders/' + id + '/approve', { headers: { 'If-Match': '"2"' }, data: approval })).status(), 409)
  const detail = await data(await context.request.get(api + '/orders/' + id))
  assert.equal(detail.status, 'awaiting_customer')
  assert.ok(detail.available_actions.includes('accept_proposal'))
  await page.getByRole('button', { name: 'Refresh details' }).click()
  await page.getByRole('button', { name: 'Review and accept proposal' }).waitFor()
  assert.match(await page.locator('.proposal-panel').innerText(), /128.00/)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.screenshot({ path: `${output}/live-proposal-${width}.png`, fullPage: true })
    const overflow = await page.evaluate(() => [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1).map(el => ({ tag: el.tagName, cls: el.className, width: el.getBoundingClientRect().width, text: el.textContent.slice(0, 60) })).slice(0, 20))
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, JSON.stringify({ width, overflow }))
  }
  await page.getByRole('button', { name: 'Review and accept proposal' }).click()
  const dialog = page.getByRole('dialog', { name: 'Confirm request action' })
  await dialog.getByRole('checkbox').check()
  const accepted = page.waitForResponse(r => r.url().endsWith('/accept') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: 'Accept proposal', exact: true }).click()
  assert.equal((await data(await accepted)).current_state, 'ready_for_review')
  assert.equal(await page.getByRole('button', { name: 'Download confirmed PI' }).count(), 0)
  const approved = await data(await context.request.post(admin + '/orders/' + id + '/approve', { headers: { 'If-Match': '"3"' }, data: approval }))
  assert.equal(approved.current_state, 'invoice_created')
  const again = await data(await context.request.post(admin + '/orders/' + id + '/approve', { headers: { 'If-Match': '"3"' }, data: approval }))
  assert.equal(again.replayed, true)
  assert.equal((await context.request.post(admin + '/orders/' + id + '/approve', { headers: { 'If-Match': '"3"', 'X-Test-Actor': '2' }, data: approval })).status(), 404)
  await page.getByRole('button', { name: 'Refresh details' }).click()
  await page.getByRole('button', { name: 'Download confirmed PI' }).waitFor()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download confirmed PI' }).click()
  await (await downloaded).saveAs(`${output}/confirmed.pdf`)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'Published PI and command notice must fit narrow screens')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', network: 'real-local-https', apiInterceptions: 0, scenarios: 9 }))
} finally { await browser.close() }
