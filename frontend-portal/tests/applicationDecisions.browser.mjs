import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { captureKeyboardEvidence, createBrowserInteraction } from './keyboardInteraction.mjs'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
let privateInput = ''
for await (const chunk of process.stdin) privateInput += chunk.toString('utf8')
const seed = JSON.parse(privateInput); privateInput = ''
const { chromium, request } = createRequire(import.meta.url)(modulePath)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath, headless: true })
const buyer = await browser.newContext({ viewport: { width: 320, height: 1000 } })
const employee = await request.newContext({ baseURL: origin }), page = await buyer.newPage()
const interaction = createBrowserInteraction('keyboard', output), api = origin + '/api/portal/v1', admin = origin + '/api/portal/admin/v1'
let rejects = 0, cancels = 0
page.on('request', request => {
 if (request.method() !== 'POST') return
 if (request.url().endsWith('/reject')) rejects++
 if (request.url().endsWith('/cancel')) cancels++
})
async function data(response, status = 200) { assert.equal(response.status(), status); const body = await response.json(); assert.equal(body.code, status); return body.data }
async function geometry(label, dialog) {
 const checks = []
 for (const width of [1440, 390, 320]) {
  await page.setViewportSize({ width, height: 1000 })
  const close = dialog.getByRole('button', { name: 'Close confirmation', exact: true })
  const bounds = await close.evaluate(element => { const b = element.getBoundingClientRect(); return { left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width } })
  checks.push({ width, close: bounds })
  await captureKeyboardEvidence(page, output + '/' + label + '-' + width + '.png')
  await writeFile(output + '/' + label + '-geometry.json', JSON.stringify(checks, null, 2))
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
  assert.ok(bounds.left >= 0 && bounds.right <= width && bounds.top >= 0 && bounds.bottom <= 1000 && bounds.width >= 44)
 }
}
try {
 const logged = await employee.post('/api/auth/login', { data: { username: seed.ownerUsername, password: seed.password } })
 assert.equal(logged.status(), 200); const headers = { Authorization: 'Bearer ' + (await logged.json()).access_token }
 await page.goto(origin + '/collection')
 await interaction.fill(page.getByLabel('Email address', { exact: true }), seed.buyerEmail, 'decision-email')
 const challenged = page.waitForResponse(response => response.url() === api + '/auth/challenges' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: /Continue with email/ }), 'decision-challenge')
 const challenge = await data(await challenged, 202)
 const mail = await buyer.request.get(origin + '/__owned/otp/' + challenge.challenge_id, { headers: { 'X-Owned-Broker': seed.brokerKey } }); assert.equal(mail.status(), 200)
 const code = (await mail.json()).code; assert.match(code, /^[0-9]{6}$/)
 await interaction.fill(page.getByLabel('Verification code', { exact: true }), code, 'decision-code')
 const catalogue = page.waitForResponse(response => response.url().split('?')[0] === api + '/catalog' && response.request().method() === 'GET')
 await interaction.click(page.getByRole('button', { name: /Enter your collection/ }), 'decision-login')
 const catalog = await data(await catalogue), item = catalog.items.find(item => item.item_id === seed.itemId)
 assert.ok(item); assert.equal(item.unit_price, '27.0000')
 await interaction.click(page.getByRole('button', { name: 'View ' + item.model_name + ', ' + item.color_name, exact: true }), 'decision-product')
 await interaction.fill(page.getByRole('dialog').getByLabel('Quantity', { exact: true }), '3', 'decision-quantity')
 await interaction.click(page.getByRole('button', { name: 'Add to selection', exact: true }), 'decision-add')
 await interaction.click(page.getByRole('button', { name: 'Review selection', exact: true }), 'decision-selection')
 const delivery = { contact_name: 'Owned Buyer', phone: '+44 10000000', address_line1: '10 Example Street', city: 'London', country_code: 'GB' }
 for (const [label, value] of Object.entries({ 'Contact name': delivery.contact_name, 'Phone number': delivery.phone, 'Address line 1': delivery.address_line1, City: delivery.city, 'Country code (e.g. US, GB)': 'GB' })) await interaction.fill(page.getByLabel(label, { exact: true }), value, 'decision-delivery-' + label)
 await interaction.fill(page.getByLabel('Your PO / reference (optional)', { exact: true }), 'PO-DECISION', 'decision-po')
 const quoted = page.waitForResponse(response => response.url() === api + '/quotes' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: 'Review request', exact: true }), 'decision-review')
 const quote = await data(await quoted, 201); assert.equal(quote.product_amount, '81.00'); assert.equal(quote.total_amount, null)
 await interaction.check(page.getByRole('checkbox'), 'decision-quote-consent')
 const submitted = page.waitForResponse(response => response.url() === api + '/orders' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: 'Submit order request', exact: true }), 'decision-submit')
 const result = await data(await submitted, 201), id = result.request_id
 await interaction.click(page.getByRole('button', { name: 'View request', exact: true }), 'decision-detail')
 await page.getByRole('button', { name: 'Refresh details', exact: true }).waitFor()
 const proposal = { items: [{ item_id: seed.itemId, quantity: 3 }], delivery, customer_po: 'PO-DECISION', remark: '', fees: { shipping_amount: '45.00', packaging_amount: '2.00', surcharge_amount: '0.00' }, payment_terms: 'prepaid', valid_for_hours: 24, reason: 'Review complete proposal before issuing PI' }
 const proposed = await data(await employee.post(admin + '/orders/' + id + '/proposals', { headers: { ...headers, 'If-Match': '"1"' }, data: proposal }))
 const revisionId = proposed.original_receipt.revision_id
 await interaction.click(page.getByRole('button', { name: 'Refresh details', exact: true }), 'decision-proposal-refresh')
 await page.getByRole('button', { name: 'Request changes', exact: true }).waitFor()
 const before = await data(await buyer.request.get(api + '/orders/' + id)); assert.equal(before.status, 'awaiting_customer'); assert.equal(before.total_amount, '128.00')
 await interaction.click(page.getByRole('button', { name: 'Request changes', exact: true }), 'decision-reject-open')
 const dialog = page.getByRole('dialog', { name: 'Confirm request action', exact: true })
 assert.equal(await dialog.getByRole('button', { name: 'Request changes', exact: true }).isDisabled(), true)
 await geometry('request-changes', dialog)
 await interaction.click(dialog.getByRole('button', { name: 'Close confirmation', exact: true }), 'decision-reject-close')
 assert.equal(await page.getByRole('button', { name: 'Request changes', exact: true }).evaluate(element => element === document.activeElement), true)
 assert.equal(rejects, 0); assert.equal(cancels, 0)
 await interaction.click(page.getByRole('button', { name: 'Request changes', exact: true }), 'decision-reject-reopen')
 await interaction.fill(dialog.getByLabel('What would you like to change?', { exact: true }), '   ', 'decision-reject-blank')
 assert.equal(await dialog.getByRole('button', { name: 'Request changes', exact: true }).isDisabled(), true)
 const rejectReason = ('Please review shipping terms. ' + 'R'.repeat(500)).slice(0, 500)
 await interaction.fill(dialog.getByLabel('What would you like to change?', { exact: true }), rejectReason, 'decision-reject-reason')
 const rejected = page.waitForResponse(response => response.url() === api + '/orders/' + id + '/proposals/' + revisionId + '/reject' && response.request().method() === 'POST')
 await interaction.click(dialog.getByRole('button', { name: 'Request changes', exact: true }), 'decision-reject-send')
 const rejectedResponse = await rejected, rejection = await data(rejectedResponse)
 assert.deepEqual(rejectedResponse.request().postDataJSON(), { reason: rejectReason }); assert.equal(rejectedResponse.request().headers()['if-match'], '"2"')
 assert.equal(rejection.current_state, 'submitted'); assert.equal(rejection.original_receipt.status, 'submitted'); assert.equal(rejection.original_receipt.revision_id, revisionId)
 await page.locator('.session-notice').waitFor(); await page.getByRole('button', { name: 'Cancel this request', exact: true }).waitFor()
 assert.equal(await page.getByRole('button', { name: 'Request changes', exact: true }).count(), 0)
 assert.equal(await page.getByRole('button', { name: 'Download confirmed PI', exact: true }).count(), 0)
 await interaction.click(page.getByRole('button', { name: 'Cancel this request', exact: true }), 'decision-cancel-open')
 assert.equal(await dialog.getByRole('button', { name: 'Cancel request', exact: true }).isDisabled(), true)
 await geometry('cancel-request', dialog)
 const cancelReason = ('Purchase timing changed. ' + 'C'.repeat(500)).slice(0, 500)
 await interaction.fill(dialog.getByLabel('Reason for cancelling', { exact: true }), cancelReason, 'decision-cancel-reason')
 const cancelled = page.waitForResponse(response => response.url() === api + '/orders/' + id + '/cancel' && response.request().method() === 'POST')
 await interaction.click(dialog.getByRole('button', { name: 'Cancel request', exact: true }), 'decision-cancel-send')
 const cancelResponse = await cancelled, cancellation = await data(cancelResponse)
 assert.deepEqual(cancelResponse.request().postDataJSON(), { reason: cancelReason }); assert.equal(cancelResponse.request().headers()['if-match'], '"3"')
 assert.equal(cancellation.current_state, 'cancelled'); assert.equal(cancellation.original_receipt.status, 'cancelled')
 await page.locator('.order-summary-bar .order-badge').filter({ hasText: /^Cancelled$/ }).waitFor()
 assert.equal(await page.getByRole('button', { name: 'Cancel this request', exact: true }).count(), 0)
 assert.equal(await page.getByRole('button', { name: 'Download confirmed PI', exact: true }).count(), 0)
 const after = await data(await buyer.request.get(api + '/orders/' + id)); assert.equal(after.status, 'cancelled'); assert.equal(after.row_version, 4)
 assert.deepEqual(after.items, before.items); assert.equal(after.total_amount, before.total_amount); assert.equal(after.customer_po, before.customer_po)
 assert.equal(rejects, 1); assert.equal(cancels, 1)
 const report = { status: 'pass', scope: 'Actual app.main/customer keyboard proposal rejection and request cancellation; owned MySQL and controlled upstream/mail; employee proposal is real HTTP, no new employee UI proof', requestId: id, revisionId, submittedQuoteId: quote.quote_id, rejectReason, cancelReason, rejects, cancels, businessResponseInterceptions: 0, widths: [1440, 390, 320], coreFlowWidth: 320, interaction: interaction.summary() }
 await writeFile(output + '/report.json', JSON.stringify(report, null, 2)); console.log(JSON.stringify({ status: report.status, rejects, cancels }))
} finally { await employee.dispose(); await buyer.close(); await browser.close() }
