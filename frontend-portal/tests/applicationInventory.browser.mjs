import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { captureKeyboardEvidence, createBrowserInteraction } from './keyboardInteraction.mjs'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
let privateInput = ''; for await (const chunk of process.stdin) privateInput += chunk.toString('utf8')
const seed = JSON.parse(privateInput); privateInput = ''
const { chromium, request } = createRequire(import.meta.url)(modulePath)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath, headless: true })
const buyer = await browser.newContext({ viewport: { width: 320, height: 1000 }, timezoneId: 'America/Los_Angeles', acceptDownloads: true })
const page = await buyer.newPage(), employee = await request.newContext({ baseURL: origin })
const interaction = createBrowserInteraction('keyboard', output), api = origin + '/api/portal/v1', admin = origin + '/api/portal/admin/v1'
async function data(response, status = 200) { assert.equal(response.status(), status); const body = await response.json(); assert.equal(body.code, status); return body.data }
async function geometry(label) {
 for (const width of [1440,390,320]) {
  await page.setViewportSize({ width, height: 1000 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
  await captureKeyboardEvidence(page, output + '/' + label + '-' + width + '.png')
 }
}
try {
 await page.goto(origin + '/collection')
 await interaction.fill(page.getByLabel('Email address', { exact: true }), seed.buyerEmail, 'stock-email')
 const challengeWait = page.waitForResponse(response => response.url() === api + '/auth/challenges' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: /Continue with email/ }), 'stock-challenge')
 const challenge = await data(await challengeWait,202), mail = await buyer.request.get(origin + '/__owned/otp/' + challenge.challenge_id, { headers: { 'X-Owned-Broker': seed.brokerKey } })
 assert.equal(mail.status(),200); const code = (await mail.json()).code; assert.match(code,/^[0-9]{6}$/)
 await interaction.fill(page.getByLabel('Verification code', { exact: true }), code, 'stock-code')
 const catalogWait = page.waitForResponse(response => response.url().split('?')[0] === api + '/catalog' && response.request().method() === 'GET')
 const verifyWait = page.waitForResponse(response => response.url() === api + '/auth/verify' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: /Enter your collection/ }), 'stock-login')
 const verified = await data(await verifyWait), catalog = await data(await catalogWait), item = catalog.items.find(item => item.item_id === seed.itemId)
 assert.ok(item); assert.equal(item.unit_price,'27.0000'); assert.equal(item.sale_unit,'pack')
 assert.ok(['available','unknown'].includes(item.availability))
 const scenario = item.availability === 'available' ? 'fresh' : 'stale'
 const card = page.getByRole('button', { name: 'View ' + item.model_name + ', ' + item.color_name, exact: true })
 function checked(text) { const expected = new Intl.DateTimeFormat('en-GB', { timeZone:'Asia/Shanghai',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23' }).format(new Date(item.inventory_observed_at + '+08:00')); assert.ok(text.includes('Stock checked ' + expected + ' (Beijing)')) }
 if (scenario === 'fresh') {
  assert.match(item.inventory_observed_at,/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/)
  checked(await card.innerText())
 } else { assert.equal(item.inventory_observed_at,null); assert.ok(!(await card.innerText()).includes('Stock checked')) }
 await geometry('stock-catalog-' + scenario)
 await interaction.click(card, 'stock-product')
 const dialog = page.getByRole('dialog', { name: item.model_name, exact: true })
 if (scenario === 'fresh') checked(await dialog.innerText())
 else {
  assert.ok(!(await dialog.innerText()).includes('Stock checked'))
  assert.ok((await dialog.innerText()).includes('Availability pending'))
  assert.equal(await dialog.getByRole('button', { name: 'Add to selection', exact: true }).count(),0)
 }
 await geometry('stock-detail-' + scenario)
 const delivery = { contact_name:'Owned Buyer', phone:'+44 10000000', address_line1:'10 Example Street', city:'London', country_code:'GB' }
 let result = null, quote = null
 if (scenario === 'stale') {
  const denied = await buyer.request.post(api + '/quotes', { headers: { Origin:origin, 'X-Portal-CSRF':verified.csrf_token }, data: { items:[{ item_id:seed.itemId,quantity:3 }], delivery,customer_po:'',remark:'' } })
  assert.equal(denied.status(),503); const failure = await denied.json(); assert.equal(failure.data.error_code,'INVENTORY_UNAVAILABLE')
  await interaction.click(dialog.getByRole('button', { name:'Back to collection', exact:true }), 'stock-back')
 } else {
  await interaction.fill(dialog.getByLabel('Quantity', { exact:true }), '3', 'stock-quantity')
  await interaction.click(dialog.getByRole('button', { name:'Add to selection', exact:true }), 'stock-add')
  await interaction.click(page.getByRole('button', { name:'Review selection', exact:true }), 'stock-selection')
  for (const [label,value] of Object.entries({ 'Contact name':delivery.contact_name, 'Phone number':delivery.phone, 'Address line 1':delivery.address_line1, City:delivery.city, 'Country code (e.g. US, GB)':'GB' })) await interaction.fill(page.getByLabel(label,{exact:true}), value, 'stock-address-' + label)
  const quoted = page.waitForResponse(response => response.url() === api + '/quotes' && response.request().method() === 'POST')
  await interaction.click(page.getByRole('button', {name:'Review request',exact:true}), 'stock-review')
  quote = await data(await quoted,201); assert.equal(quote.product_amount,'81.00'); assert.equal(quote.total_amount,null)
  await interaction.check(page.getByRole('checkbox'), 'stock-review-consent')
  const submitted = page.waitForResponse(response => response.url() === api + '/orders' && response.request().method() === 'POST')
  await interaction.click(page.getByRole('button', {name:'Submit order request',exact:true}), 'stock-submit')
  result = await data(await submitted,201)
  await interaction.click(page.getByRole('button', {name:'View request',exact:true}), 'stock-request')
  await page.getByRole('button', {name:'Refresh details',exact:true}).waitFor()
  const logged = await employee.post('/api/auth/login', {data:{username:seed.ownerUsername,password:seed.password}}); assert.equal(logged.status(),200)
  const headers = {Authorization:'Bearer ' + (await logged.json()).access_token}
  const proposed = await data(await employee.post(admin + '/orders/' + result.request_id + '/proposals', {headers:{...headers,'If-Match':'"1"'},data:{items:[{item_id:seed.itemId,quantity:3}],delivery,customer_po:'',remark:'',fees:{shipping_amount:'0.00',packaging_amount:'0.00',surcharge_amount:'0.00'},payment_terms:'prepaid',valid_for_hours:24,reason:'Confirm mirror stock order terms'}}))
  await interaction.click(page.getByRole('button', {name:'Refresh details',exact:true}), 'stock-proposal-refresh')
  await interaction.click(page.getByRole('button', {name:'Review and accept proposal',exact:true}), 'stock-proposal-open')
  const confirmation = page.getByRole('dialog', {name:'Confirm request action',exact:true})
  await interaction.check(confirmation.getByRole('checkbox'), 'stock-proposal-consent')
  const accepted = page.waitForResponse(response => response.url().endsWith('/accept') && response.request().method() === 'POST')
  await interaction.click(confirmation.getByRole('button', {name:'Accept proposal',exact:true}), 'stock-accept')
  const receipt = await data(await accepted)
  await data(await employee.post(admin + '/orders/' + result.request_id + '/approve', {headers:{...headers,'If-Match':'"' + receipt.row_version + '"'},data:{accepted_revision_id:proposed.original_receipt.revision_id}}))
  const detailsWait = page.waitForResponse(response => response.url() === api + '/orders/' + result.request_id && response.request().method() === 'GET')
  await interaction.click(page.getByRole('button', {name:'Refresh details',exact:true}), 'stock-pi-refresh')
  const published = await data(await detailsWait); assert.equal(published.status,'invoice_created'); assert.ok(published.available_actions.includes('download_pi'))
  await page.getByRole('button',{name:'Download confirmed PI',exact:true}).waitFor()
  const pdfWait = page.waitForResponse(response => response.url() === api + '/orders/' + result.request_id + '/pi' && response.request().method() === 'GET')
  const download = page.waitForEvent('download'); download.catch(() => {})
  await interaction.click(page.getByRole('button', {name:'Download confirmed PI',exact:true}), 'stock-pi-download')
  const response = await pdfWait
  await writeFile(output + '/download-evidence.json',JSON.stringify({status:response.status(),contentType:response.headers()['content-type'] === 'application/pdf' ? 'application/pdf' : 'other'}))
  assert.equal(response.status(),200); assert.equal(response.headers()['content-type'],'application/pdf')
  const pdf = await download; assert.equal(await pdf.failure(),null); await pdf.saveAs(output + '/stock-confirmed.pdf')
 }
 const report = {status:'pass',scenario,scope:'Actual app.main with real inventory-source SQL and price services on owned synthetic mirror; customer keyboard core320/LosAngeles timezone; three widths only catalog/detail layout; employee proposal/approve HTTP, not production or new employee UI proof',requestId:result?.request_id,quoteId:quote?.quote_id,businessResponseInterceptions:0,widths:[1440,390,320],interaction:interaction.summary()}
 await writeFile(output + '/report.json',JSON.stringify(report,null,2)); console.log(JSON.stringify({status:report.status,scenario}))
} finally { await employee.dispose(); await buyer.close(); await browser.close() }
