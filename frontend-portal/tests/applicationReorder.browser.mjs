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
const buyer = await browser.newContext({ viewport: { width: 320, height: 1000 }, acceptDownloads: true })
const employee = await request.newContext({ baseURL: origin }), page = await buyer.newPage()
const interaction = createBrowserInteraction('keyboard', output), api = origin + '/api/portal/v1', admin = origin + '/api/portal/admin/v1'
let reorderPosts = 0
page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/reorder-quote')) reorderPosts++ })
async function data(response, status = 200) { assert.equal(response.status(), status); const body = await response.json(); assert.equal(body.code, status); return body.data }
async function geometry(label, target) {
 for (const width of [1440, 390, 320]) {
  await page.setViewportSize({ width, height: 1000 }); await target.scrollIntoViewIfNeeded()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
  assert.ok(await target.evaluate(element => { const bounds = element.getBoundingClientRect(); return bounds.left >= 0 && bounds.right <= innerWidth }))
  await captureKeyboardEvidence(page, output + '/' + label + '-' + width + '.png')
 }
}
try {
 const logged = await employee.post('/api/auth/login', { data: { username: seed.ownerUsername, password: seed.password } })
 assert.equal(logged.status(), 200); const headers = { Authorization: 'Bearer ' + (await logged.json()).access_token }
 await page.goto(origin + '/collection')
 await interaction.fill(page.getByLabel('Email address', { exact: true }), seed.buyerEmail, 'repeat-email')
 const challenged = page.waitForResponse(response => response.url() === api + '/auth/challenges' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: /Continue with email/ }), 'repeat-challenge')
 const challenge = await data(await challenged, 202)
 const mail = await buyer.request.get(origin + '/__owned/otp/' + challenge.challenge_id, { headers: { 'X-Owned-Broker': seed.brokerKey } }); assert.equal(mail.status(), 200)
 const code = (await mail.json()).code; assert.match(code, /^[0-9]{6}$/)
 await interaction.fill(page.getByLabel('Verification code', { exact: true }), code, 'repeat-code')
 const catalogue = page.waitForResponse(response => response.url().split('?')[0] === api + '/catalog' && response.request().method() === 'GET')
 await interaction.click(page.getByRole('button', { name: /Enter your collection/ }), 'repeat-login')
 const catalog = await data(await catalogue), item = catalog.items.find(item => item.item_id === seed.itemId)
 assert.ok(item); assert.equal(item.model_name, 'Current Straight'); assert.equal(item.unit_price, '24.0000')
 await interaction.click(page.getByRole('button', { name: 'View Current Straight, Current Black', exact: true }), 'repeat-current-product')
 await interaction.fill(page.getByRole('dialog').getByLabel('Quantity', { exact: true }), '1', 'repeat-existing-quantity')
 await interaction.click(page.getByRole('button', { name: 'Add to selection', exact: true }), 'repeat-existing-add')
 await interaction.click(page.getByRole('button', { name: 'Review selection', exact: true }), 'repeat-existing-selection')
 await interaction.fill(page.getByLabel('Address line 1', { exact: true }), 'Existing draft address', 'repeat-existing-address')
 const listed = page.waitForResponse(response => response.url().split('?')[0] === api + '/orders' && response.request().method() === 'GET')
 await interaction.click(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Requests', exact: true }), 'repeat-history-list')
 const list = await data(await listed); assert.equal(list.total, 1); const sourceId = list.items[0].request_id
 const detailed = page.waitForResponse(response => response.url() === api + '/orders/' + sourceId && response.request().method() === 'GET')
 await interaction.click(page.getByRole('link', { name: new RegExp(list.items[0].request_no) }), 'repeat-source-detail')
 const history = await data(await detailed)
 assert.equal(history.items.length, 1); assert.equal(history.items[0].display_snapshot.model_name, 'History Straight')
 assert.equal(history.customer_po, 'HISTORY-PO'); assert.equal(history.product_amount, '81.00')
 await interaction.click(page.getByRole('button', { name: 'Repeat selected products', exact: true }), 'repeat-open')
 const dialog = page.getByRole('dialog', { name: 'Repeat request products' }), prepare = dialog.getByRole('button', { name: 'Review fresh quote', exact: true })
 assert.equal(await prepare.isDisabled(), true); assert.equal(reorderPosts, 0)
 assert.equal(await dialog.getByRole('checkbox', { name: 'Repeat History Straight, History Black', exact: true }).isChecked(), true)
 await interaction.check(dialog.getByRole('checkbox', { name: /Replace my current selection/ }), 'repeat-replacement-consent')
 assert.equal(await prepare.isEnabled(), true)
 await geometry('repeat-confirm', prepare)
 const quoted = page.waitForResponse(response => response.url() === api + '/orders/' + sourceId + '/reorder-quote' && response.request().method() === 'POST')
 await interaction.click(prepare, 'repeat-create-quote')
 const quoteResponse = await quoted, fresh = await data(quoteResponse, 201)
 assert.deepEqual(quoteResponse.request().postDataJSON(), { line_keys: [history.items[0].line_key] })
 assert.equal(fresh.reorder.source_request_id, sourceId); assert.equal(fresh.customer_po, ''); assert.equal(fresh.total_amount, null)
 assert.equal(fresh.product_amount, '72.00'); assert.equal(fresh.fees.status, 'pending')
 assert.equal(fresh.items[0].unit_price, '24.0000'); assert.equal(fresh.items[0].quantity, 3)
 assert.equal(fresh.items[0].display_snapshot.model_name, 'Current Straight'); assert.equal(fresh.items[0].display_snapshot.customer_sku, 'CURRENT-SKU')
 await page.getByRole('heading', { name: 'Since your previous request', exact: true }).waitFor()
 const comparison = await page.locator('.reorder-comparison').innerText()
 assert.ok(['History Straight', 'Current Straight', '81.00', '72.00'].every(value => comparison.includes(value)))
 assert.equal(await page.getByLabel('Quantity', { exact: true }).inputValue(), '3')
 assert.equal(await page.getByLabel('Address line 1', { exact: true }).inputValue(), '10 Test Street')
 assert.equal(await page.getByLabel('Your PO / reference (optional)', { exact: true }).inputValue(), '')
 assert.equal(await page.getByLabel('Request notes (optional)', { exact: true }).inputValue(), 'Historical repeat note')
 const submit = page.getByRole('button', { name: 'Submit order request', exact: true })
 assert.equal(await submit.isDisabled(), true)
 await interaction.check(page.getByRole('checkbox'), 'repeat-new-quote-consent')
 const submitted = page.waitForResponse(response => response.url() === api + '/orders' && response.request().method() === 'POST')
 await interaction.click(submit, 'repeat-submit')
 const result = await data(await submitted, 201), id = result.request_id
 assert.notEqual(id, sourceId); assert.equal(result.total_amount, null); assert.equal(result.product_amount, '72.00')
 await interaction.click(page.getByRole('button', { name: 'View request', exact: true }), 'repeat-new-detail')
 const proposal = { items: [{ item_id: seed.itemId, quantity: 3 }], delivery: fresh.delivery, customer_po: '', remark: fresh.remark, fees: { shipping_amount: '0.00', packaging_amount: '0.00', surcharge_amount: '0.00' }, payment_terms: 'prepaid', valid_for_hours: 24, reason: 'Confirm repeated request current terms' }
 const proposed = await data(await employee.post(admin + '/orders/' + id + '/proposals', { headers: { ...headers, 'If-Match': '"1"' }, data: proposal }))
 await interaction.click(page.getByRole('button', { name: 'Refresh details', exact: true }), 'repeat-proposal-refresh')
 await interaction.click(page.getByRole('button', { name: 'Review and accept proposal', exact: true }), 'repeat-review-proposal')
 const confirm = page.getByRole('dialog', { name: 'Confirm request action' })
 await interaction.check(confirm.getByRole('checkbox'), 'repeat-proposal-consent')
 const accepted = page.waitForResponse(response => response.url().endsWith('/accept') && response.request().method() === 'POST')
 await interaction.click(confirm.getByRole('button', { name: 'Accept proposal', exact: true }), 'repeat-accept-proposal')
 const acceptedResult = await data(await accepted)
 const approved = await data(await employee.post(admin + '/orders/' + id + '/approve', { headers: { ...headers, 'If-Match': '"' + acceptedResult.row_version + '"' }, data: { accepted_revision_id: proposed.original_receipt.revision_id } }))
 assert.equal(approved.current_state, 'invoice_created')
 await interaction.click(page.getByRole('button', { name: 'Refresh details', exact: true }), 'repeat-pi-refresh')
 const download = page.waitForEvent('download')
 await interaction.click(page.getByRole('button', { name: 'Download confirmed PI', exact: true }), 'repeat-pi-download')
 const pdf = await download; assert.equal(await pdf.failure(), null); await pdf.saveAs(output + '/repeat-confirmed.pdf')
 assert.deepEqual(await data(await buyer.request.get(api + '/orders/' + sourceId)), history)
 assert.equal(reorderPosts, 1)
 const report = { status: 'pass', scope: 'Actual app.main/customer keyboard repeat flow and owned MySQL; synthetic upstream and service-created history; employee proposals/approval are real HTTP, not new employee UI proof', sourceId, requestId: id, quoteId: fresh.quote_id, reorderPosts, businessResponseInterceptions: 0, widths: [1440, 390, 320], interaction: interaction.summary() }
 await writeFile(output + '/report.json', JSON.stringify(report, null, 2)); console.log(JSON.stringify(report))
} finally { await employee.dispose(); await buyer.close(); await browser.close() }
