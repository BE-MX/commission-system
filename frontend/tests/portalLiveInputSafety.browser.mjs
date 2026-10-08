import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const [employeeOrigin, customerOrigin, modulePath, executablePath, output] = process.argv.slice(2)
for (const origin of [employeeOrigin, customerOrigin]) assert.match(origin, /^https?:\/\/127\.0\.0\.1:\d+$/)
let input = ''; for await (const part of process.stdin) input += part
const seed = JSON.parse(input)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const employee = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
const customer = await browser.newContext({ viewport: { width: 1440, height: 1050 }, acceptDownloads: true, ignoreHTTPSErrors: true })
const errors = [], probes = [], checkpoints = []
async function watch(context) {
  await context.addInitScript(({ origin }) => {
    window.__portalXss = 0
    // Only the employee app needs the synthetic welcome flag. Opaque browser
    // documents/PDF frames have no storage authority and must not be touched.
    if (location.origin === origin) sessionStorage.setItem('leshine_welcome_shown_session', '1')
  }, { origin: employeeOrigin })
  context.on('request', request => { if (new URL(request.url()).pathname === '/xss-probe') probes.push(request.url()) })
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)))
}
async function safe(page, name, values = []) {
  for (const value of values) assert.ok((await page.locator('body').innerText()).includes(value), `${name}: expected literal text`)
  assert.equal(await page.evaluate(() => window.__portalXss), 0, `${name}: script executed`)
  assert.equal(await page.locator('[onerror*="__portalXss"], [onload*="__portalXss"], a[href^="javascript:"], img[src="/xss-probe"]').count(), 0)
  assert.deepEqual(probes, [], `${name}: injected resource requested`)
  checkpoints.push(name)
}
async function responseData(response, status = 200) {
  assert.equal(response.status(), status, `Unexpected response: ${new URL(response.url()).pathname}`)
  return (await response.json()).data
}
try {
  // Positive control uses a separate context without credentials or application pages.
  const controlContext = await browser.newContext(), control = await controlContext.newPage()
  await control.evaluate(() => { window.__portalXss = 0 })
  await control.setContent('<img src="data:invalid" onerror="window.__portalXss++"><svg onload="window.__portalXss++"></svg>')
  await control.waitForFunction(() => window.__portalXss === 2)
  await controlContext.close()
  await watch(employee); await watch(customer)
  await customer.addCookies([{ name: '__Host-portal_session', value: seed.session, url: customerOrigin,
    httpOnly: true, secure: true, sameSite: 'Lax' }])
  const admin = await employee.newPage()
  await admin.goto(employeeOrigin + '/portal/customers')
  await admin.getByLabel('用户名', { exact: true }).fill(seed.username)
  await admin.getByLabel('密码', { exact: true }).fill(seed.password)
  const login = admin.waitForResponse(r => r.url() === employeeOrigin + '/api/auth/login' && r.request().method() === 'POST')
  await admin.locator('button[type="submit"]').click()
  const loggedIn = await login; assert.equal(loggedIn.status(), 200)
  const token = (await loggedIn.json()).access_token
  assert.ok(token.split('.').length === 3)
  await admin.getByRole('cell', { name: seed.attack_color, exact: true }).waitFor()
  await safe(admin, 'customer-management', [seed.attack_color])
  await admin.getByRole('button', { name: '管理', exact: true }).click()
  await admin.getByRole('button', { name: '型号颜色映射', exact: true }).click()
  const mapping = admin.locator('.portal-mapping-dialog:visible')
  await mapping.getByRole('textbox', { name: '客户展示名 1', exact: true }).fill(seed.attack_model)
  await mapping.getByRole('textbox', { name: '客户货号 1', exact: true }).fill(seed.attack_sku)
  await mapping.getByRole('textbox', { name: '客户展示名 2', exact: true }).fill(seed.attack_color)
  const deniedPreview = admin.waitForResponse(r => r.url().endsWith('/mapping/preview'))
  await mapping.getByRole('button', { name: '校验并预览', exact: true }).click()
  const rejected = await deniedPreview
  assert.equal(rejected.status(),422); assert.equal((await rejected.json()).data.error_code,'INVALID_INPUT')
  assert.equal(await mapping.getByRole('button', { name:'发布映射', exact:true }).isDisabled(),true)
  assert.equal(await mapping.getByRole('textbox', { name:'客户展示名 1',exact:true }).inputValue(),seed.attack_model)
  await safe(admin,'invalid-mapping-rejected')
  await mapping.getByRole('textbox', { name: '客户展示名 1', exact: true }).fill(seed.model)
  await mapping.getByRole('textbox', { name: '客户货号 1', exact: true }).fill(seed.sku)
  await mapping.getByRole('textbox', { name: '客户展示名 2', exact: true }).fill(seed.color)
  const previewResponse = admin.waitForResponse(r => r.url().endsWith('/mapping/preview'))
  await mapping.getByRole('button', { name: '校验并预览', exact: true }).click()
  await responseData(await previewResponse)
  await mapping.getByRole('cell', { name: seed.model, exact: true }).waitFor()
  await safe(admin, 'mapping-preview-and-diff', [seed.model, seed.color, seed.sku])
  await mapping.locator('.el-checkbox').filter({ hasText: '我已核对完整展示效果' }).click()
  const publication = admin.waitForResponse(r => r.url().endsWith('/mapping/publish'))
  await mapping.getByRole('button', { name: '发布映射', exact: true }).click()
  await responseData(await publication,201); await mapping.waitFor({ state: 'hidden' })

  const buyer = await customer.newPage()
  await buyer.goto(customerOrigin + '/collection')
  const product = buyer.getByRole('button', { name: `View ${seed.model}, ${seed.color}`, exact: true })
  await product.waitFor(); await safe(buyer, 'collection', [seed.model, seed.color, seed.sku])
  await product.click()
  await safe(buyer, 'product-dialog', [seed.model, seed.color, seed.sku])
  await buyer.getByRole('dialog').getByLabel('Quantity').fill('3')
  await buyer.getByRole('button', { name: 'Add to selection', exact: true }).click()
  await buyer.getByRole('button', { name: 'Review selection', exact: true }).click()
  const fields = { 'Contact name': seed.delivery.contact_name, 'Phone number': seed.delivery.phone,
    'Address line 1': seed.delivery.address_line1, 'Address line 2 (optional)': seed.delivery.address_line2,
    City: seed.delivery.city, 'Country code (e.g. US, GB)': 'GB' }
  for (const [name,value] of Object.entries(fields)) await buyer.getByLabel(name, { exact: true }).fill(value)
  await buyer.getByLabel('Your PO / reference (optional)', { exact: true }).fill(seed.formula)
  await buyer.getByLabel('Request notes (optional)', { exact: true }).fill(seed.remark)
  const quoted = buyer.waitForResponse(r => r.url().endsWith('/quotes') && r.request().method() === 'POST')
  await buyer.getByRole('button', { name: 'Review request', exact: true }).click()
  await responseData(await quoted, 201)
  await buyer.getByRole('button', { name: 'Submit order request', exact: true }).waitFor()
  await safe(buyer, 'cart-and-server-review', [seed.model,seed.color,seed.sku,seed.delivery.address_line1,seed.delivery.address_line2,seed.formula,seed.remark])
  await buyer.getByRole('checkbox').check()
  const submitted = buyer.waitForResponse(r => r.url().endsWith('/orders') && r.request().method() === 'POST')
  await buyer.getByRole('button', { name: 'Submit order request', exact: true }).click()
  const order = await responseData(await submitted, 201), id = order.request_id
  await buyer.getByRole('button', { name: 'View request', exact: true }).click()
  await buyer.getByRole('button', { name: 'Refresh details', exact: true }).waitFor()
  await safe(buyer, 'submitted-request', [seed.model,seed.color,seed.sku,seed.formula,seed.remark])

  // The order is handled by its real owner; admin read scope is not delegation.
  const seller = await browser.newContext({ viewport:{width:1440,height:1050} })
  await watch(seller)
  const sales = await seller.newPage()
  await sales.goto(employeeOrigin + '/portal/orders?request=' + id)
  await sales.getByLabel('用户名', {exact:true}).fill(seed.owner)
  await sales.getByLabel('密码', {exact:true}).fill(seed.password)
  const ownLogin = sales.waitForResponse(r => r.url() === employeeOrigin+'/api/auth/login' && r.request().method() === 'POST')
  await sales.locator('button[type="submit"]').click()
  const ownResponse = await ownLogin; assert.equal(ownResponse.status(),200)
  const ownBearer = {Authorization:'Bearer '+(await ownResponse.json()).access_token}

  await sales.getByRole('button', { name: '处理请求', exact: true }).click()
  const review = sales.getByRole('dialog', { name: '处理客户下单请求', exact: true })
  await review.getByText('当前版本完整条款', { exact: true }).waitFor()
  await safe(sales, 'employee-order-and-review', [seed.model,seed.color,seed.sku,seed.delivery.address_line1,seed.delivery.address_line2,seed.formula,seed.remark])
  await review.getByRole('button', { name: '关闭', exact: true }).click()
  await review.waitFor({ state: 'hidden' })
  const proposal = await responseData(await seller.request.post(employeeOrigin + '/api/portal/admin/v1/orders/' + id + '/proposals', {
    headers: { ...ownBearer, 'If-Match': '"1"' }, data: { items: [{ item_id: seed.item_id, quantity: 3 }],
      delivery: seed.delivery, customer_po: seed.formula, remark: seed.remark,
      fees: { shipping_amount: '45.00', packaging_amount: '2.00', surcharge_amount: '0.00' },
      payment_terms: 'prepaid', valid_for_hours: 24, reason: seed.reason } }))
  assert.equal(proposal.current_state, 'awaiting_customer')
  await buyer.getByRole('button', { name: 'Refresh details', exact: true }).click()
  await buyer.getByRole('button', { name: 'Review and accept proposal', exact: true }).waitFor()
  await safe(buyer, 'proposal-and-diff', [seed.model,seed.color,seed.sku,seed.delivery.address_line1,seed.delivery.address_line2,seed.formula,seed.remark])
  await buyer.getByRole('button', { name: 'Review and accept proposal', exact: true }).click()
  const decision = buyer.getByRole('dialog', { name: 'Confirm request action', exact: true })
  await decision.getByRole('checkbox').check()
  const accepted = buyer.waitForResponse(r => r.url().endsWith('/accept'))
  await decision.getByRole('button', { name: 'Accept proposal', exact: true }).click()
  assert.equal((await responseData(await accepted)).current_state, 'ready_for_review')
  await decision.waitFor({ state: 'hidden' })
  await sales.reload()
  await sales.getByRole('button', { name: '处理请求', exact: true }).click()
  await review.getByText('当前版本完整条款', { exact: true }).waitFor()
  await review.locator('.el-radio-button').filter({ hasText: '审核并生成正式 PI' }).click()
  await safe(sales, 'final-employee-review', [seed.model,seed.color,seed.sku,seed.formula,seed.remark])
  await review.locator('.el-checkbox').click()
  const approved = sales.waitForResponse(r => r.url().endsWith('/approve'))
  await review.getByRole('button', { name: '确认操作', exact: true }).click()
  assert.equal((await responseData(await approved)).current_state, 'invoice_created')
  await review.waitFor({ state: 'hidden' })
  await sales.getByRole('button', { name: '查看操作审计', exact: true }).click()
  const audit = sales.getByRole('dialog', { name: '订单操作审计', exact: true })
  await audit.getByText('提出确认方案', { exact: true }).waitFor()
  await safe(sales, 'persisted-audit-reason', [seed.reason])
  await audit.screenshot({ animations: 'disabled', path: output+'/input-audit.png' })
  await buyer.getByRole('button', { name: 'Refresh details', exact: true }).click()
  await buyer.getByRole('button', { name: 'Download confirmed PI', exact: true }).waitFor()
  await safe(buyer, 'published-request', [seed.model,seed.color,seed.sku,seed.formula,seed.remark])
  const downloaded = buyer.waitForEvent('download')
  await buyer.getByRole('button', { name: 'Download confirmed PI', exact: true }).click()
  await (await downloaded).saveAs(output+'/input-safety.pdf')
  await buyer.screenshot({ animations: 'disabled', path: output+'/input-customer.png', fullPage: true })
  assert.equal(await buyer.getByRole('button', { name: /export.*csv/i }).count(), 0)
  assert.deepEqual(errors, []); assert.deepEqual(probes, [])
  console.log(JSON.stringify({ status:'pass', apiInterceptions:0, positiveControlExecutions:2,
    checkpoints:checkpoints.length, injectedRequests:probes.length, request_id:id }))
} finally { await browser.close() }