import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { captureKeyboardEvidence } from './keyboardInteraction.mjs'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
let privateInput = ''
for await (const chunk of process.stdin) privateInput += chunk.toString('utf8')
const seed = JSON.parse(privateInput); privateInput = ''
const { chromium, request } = createRequire(import.meta.url)(modulePath)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath, headless: true })
const buyer = await browser.newContext({ viewport: { width: 320, height: 1000 }, acceptDownloads: true })
const employee = await request.newContext({ baseURL: origin })
const page = await buyer.newPage(), errors = []
const api = origin + '/api/portal/v1', admin = origin + '/api/portal/admin/v1'
const model = 'M'.repeat(128), color = 'C'.repeat(128), sku = 'S'.repeat(64)
const address = 'A'.repeat(200), contact = 'N'.repeat(100), phone = '+44' + '1'.repeat(37), po = 'P'.repeat(80)
let imageAborts = 0, fontRequests = 0, approvedImageVerified = false
let releaseImageFault
const imageFaultGate = new Promise(resolve => { releaseImageFault = resolve })
page.on('pageerror', error => errors.push(error.name))
page.on('request', request => { if (new URL(request.url()).pathname === '/__owned/unavailable-font.woff2') fontRequests++ })
await buyer.route('**/api/portal/v1/catalog/*/image?version=*', async route => {
 assert.equal(route.request().method(), 'GET')
 assert.match(new URL(route.request().url()).pathname, /^\/api\/portal\/v1\/catalog\/[a-f0-9-]{36}\/image$/)
 await imageFaultGate
 assert.equal(approvedImageVerified, true)
 imageAborts++; await route.abort('failed')
})
async function data(response, status = 200) {
 assert.equal(response.status(), status, 'Unexpected HTTP status at owned business endpoint')
 const body = await response.json(); assert.equal(body.code, status); return body.data
}
async function geometry(label, target = null) {
 for (const width of [1440, 390, 320]) {
  await page.setViewportSize({ width, height: 1000 })
  await writeFile(output + '/layout-progress.json', JSON.stringify({ stage: label, width, ...await page.evaluate(() => ({ documentWidth: document.documentElement.scrollWidth, viewportWidth: innerWidth })) }))
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'Surface must not cause page overflow: ' + label)
  if (target) {
   await target.scrollIntoViewIfNeeded()
   assert.equal(await target.isEnabled(), true)
   assert.ok(await target.evaluate(element => { const bounds = element.getBoundingClientRect(); return bounds.left >= -1 && bounds.right <= innerWidth + 1 }), 'Action must stay within viewport: ' + label)
  }
  await captureKeyboardEvidence(page, output + '/' + label + '-' + width + '.png')
 }
}
try {
 const logged = await employee.post('/api/auth/login', { data: { username: seed.ownerUsername, password: seed.password } })
 assert.equal(logged.status(), 200)
 const headers = { Authorization: 'Bearer ' + (await logged.json()).access_token }
 const mapping = await data(await employee.post(admin + '/customers/' + seed.accessId + '/mapping/publish', {
  headers: { ...headers, 'If-Match': '"' + seed.accessVersion + '"' }, data: { base_version: 0, entries: [
   { kind: 'sku', source_key: seed.itemId, item_id: seed.itemId, display_value: model, customer_sku: sku },
   { kind: 'color', source_key: seed.standardColorKey, display_value: color }] } }), 201)
 assert.equal(mapping.mapping_version, 1)
 await page.goto(origin + '/collection')
 await page.getByLabel('Email address', { exact: true }).fill(seed.buyerEmail)
 const challenged = page.waitForResponse(response => response.url() === api + '/auth/challenges' && response.request().method() === 'POST')
 await page.getByRole('button', { name: /Continue with email/ }).click()
 const challenge = await data(await challenged, 202)
 const mail = await buyer.request.get(origin + '/__owned/otp/' + challenge.challenge_id, { headers: { 'X-Owned-Broker': seed.brokerKey } })
 assert.equal(mail.status(), 200)
 const code = (await mail.json()).code; assert.match(code, /^[0-9]{6}$/)
 await page.getByLabel('Verification code', { exact: true }).fill(code)
 const catalogue = page.waitForResponse(response => response.url().split('?')[0] === api + '/catalog' && response.request().method() === 'GET')
 await page.getByRole('button', { name: /Enter your collection/ }).click()
 const catalog = await data(await catalogue), item = catalog.items.find(item => item.item_id === seed.itemId)
 assert.ok(item); assert.equal(item.model_name, model); assert.equal(item.color_name, color); assert.equal(item.customer_sku, sku)
 assert.match(item.image_url, /^\/api\/portal\/v1\/catalog\/[a-f0-9-]{36}\/image\?version=[1-9][0-9]*$/)
 // Browser routing does not affect APIRequestContext. Prove this is a real
 // approved image served by the actual application before the UI fault.
 const image = await buyer.request.get(origin + item.image_url)
 assert.equal(image.status(), 200); assert.match(image.headers()['content-type'], /^image\/jpeg/)
 assert.equal((await image.body()).subarray(0, 2).toString('hex'), 'ffd8')
 assert.equal(imageAborts, 0)
 approvedImageVerified = true; releaseImageFault()
 const product = page.getByRole('button', { name: 'View ' + model + ', ' + color, exact: true })
 await product.waitFor()
 await product.locator('.product-monogram').waitFor()
 assert.equal(await product.locator('.product-photo').count(), 0)
 assert.ok(imageAborts >= 1)
 const fontFailure = await page.evaluate(async () => {
  const face = new FontFace('OwnedUnavailableFont', 'url("/__owned/unavailable-font.woff2")')
  document.fonts.add(face)
  try { await face.load() } catch { /* The deliberate unavailable face must fail. */ }
  document.body.style.setProperty('--portal-font', 'OwnedUnavailableFont, Arial, sans-serif')
  document.body.style.setProperty('--portal-display', 'OwnedUnavailableFont, Arial, sans-serif')
  return face.status
 })
 assert.equal(fontFailure, 'error'); assert.ok(fontRequests >= 1)
 await geometry('surface-collection', product)
 await product.click()
 const specifications = page.getByRole('dialog')
 assert.equal(await specifications.getByRole('heading', { name: model, exact: true }).innerText(), model)
 await specifications.getByLabel('Quantity', { exact: true }).fill('3')
 await geometry('surface-product', page.getByRole('button', { name: 'Add to selection', exact: true }))
 await page.getByRole('button', { name: 'Add to selection', exact: true }).click()
 await page.getByRole('button', { name: 'Review selection', exact: true }).click()
 for (const [label, value] of Object.entries({ 'Contact name': contact, 'Phone number': phone, 'Address line 1': address, City: 'London', 'Country code (e.g. US, GB)': 'GB', 'Your PO / reference (optional)': po })) {
  await page.getByLabel(label, { exact: true }).fill(value)
  assert.equal(await page.getByLabel(label, { exact: true }).inputValue(), value)
 }
 await geometry('surface-delivery', page.getByRole('button', { name: 'Review request', exact: true }))
 await page.getByRole('button', { name: 'Review request', exact: true }).click()
 const review = page.getByRole('complementary', { name: 'Server review' })
 await review.getByText(address, { exact: false }).waitFor()
 assert.ok((await review.innerText()).includes(model) && (await review.innerText()).includes(color) && (await review.innerText()).includes(sku))
 assert.match(await review.innerText(), /81\.00/)
 await page.getByRole('checkbox').check()
 await geometry('surface-review', page.getByRole('button', { name: 'Submit order request', exact: true }))
 const submitted = page.waitForResponse(response => response.url() === api + '/orders' && response.request().method() === 'POST')
 await page.getByRole('button', { name: 'Submit order request', exact: true }).click()
 const result = await data(await submitted, 201), id = result.request_id
 assert.equal(result.total_amount, null)
 await page.getByRole('button', { name: 'View request', exact: true }).click()
 const proposal = { items: [{ item_id: seed.itemId, quantity: 3 }], delivery: { contact_name: contact, phone, address_line1: address, city: 'London', country_code: 'GB' }, customer_po: po, remark: '', fees: { shipping_amount: '45.00', packaging_amount: '2.00', surcharge_amount: '0.00' }, payment_terms: 'prepaid', valid_for_hours: 24, reason: 'Confirm full long-content test terms' }
 const proposed = await data(await employee.post(admin + '/orders/' + id + '/proposals', { headers: { ...headers, 'If-Match': '"1"' }, data: proposal }))
 const premature = await employee.post(admin + '/orders/' + id + '/approve', { headers: { ...headers, 'If-Match': '"2"' }, data: { accepted_revision_id: proposed.original_receipt.revision_id } })
 assert.equal(premature.status(), 409)
 assert.equal((await premature.json()).data.error_code, 'CUSTOMER_ACCEPTANCE_REQUIRED')
 await page.getByRole('button', { name: 'Refresh details', exact: true }).click()
 await page.getByRole('button', { name: 'Review and accept proposal', exact: true }).waitFor()
 await geometry('surface-proposal', page.getByRole('button', { name: 'Review and accept proposal', exact: true }))
 await page.getByRole('button', { name: 'Review and accept proposal', exact: true }).click()
 const confirm = page.getByRole('dialog', { name: 'Confirm request action' })
 await confirm.getByRole('checkbox').check()
 const accepted = page.waitForResponse(response => response.url().endsWith('/accept') && response.request().method() === 'POST')
 await confirm.getByRole('button', { name: 'Accept proposal', exact: true }).click()
 const acceptedResult = await data(await accepted)
 assert.ok(Number.isInteger(acceptedResult.row_version) && acceptedResult.row_version >= 3)
 const approved = await data(await employee.post(admin + '/orders/' + id + '/approve', { headers: { ...headers, 'If-Match': '"' + acceptedResult.row_version + '"' }, data: { accepted_revision_id: proposed.original_receipt.revision_id } }))
 assert.equal(approved.current_state, 'invoice_created')
 await page.getByRole('button', { name: 'Refresh details', exact: true }).click()
 await page.getByRole('button', { name: 'Download confirmed PI', exact: true }).waitFor()
 await geometry('surface-pi', page.getByRole('button', { name: 'Download confirmed PI', exact: true }))
 const download = page.waitForEvent('download')
 await page.getByRole('button', { name: 'Download confirmed PI', exact: true }).click()
 const pdf = await download; assert.equal(await pdf.failure(), null); await pdf.saveAs(output + '/surface-confirmed.pdf')
 assert.deepEqual(errors, [])
 const report = { status: 'pass', scope: 'Actual app.main/customer UI/local approved image and MySQL; legal field maxima, controlled browser image abort and unavailable FontFace; no production font/storage proof', requestId: id, widths: [1440, 390, 320], lengths: { model: model.length, color: color.length, sku: sku.length, address: address.length, contact: contact.length, phone: phone.length, po: po.length }, businessResponseInterceptions: 0, imageLoadAborts: imageAborts, approvedImageHttp: 200, fontStatus: fontFailure, fontRequests, stages: ['collection', 'product', 'delivery', 'review', 'proposal', 'pi'] }
 await writeFile(output + '/report.json', JSON.stringify(report, null, 2)); console.log(JSON.stringify(report))
} finally { releaseImageFault(); await employee.dispose(); await buyer.close(); await browser.close() }
