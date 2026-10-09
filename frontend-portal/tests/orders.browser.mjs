import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || 'tmp/browser-qa'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.PORTAL_CHROMIUM ? { executablePath: process.env.PORTAL_CHROMIUM } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true })
const uuid = n => `${n}1111111-1111-4111-8111-111111111111`
const identity = { me: { account_public_id: uuid(9), company_display_name: 'Atelier Test Salon' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'test-csrf' }
const delivery = { contact_name: 'Test buyer', phone: '+44 123456', address_line1: '10 Test Lane', country_code: 'GB', address_line2: '', city: 'London', region: '', postal_code: '' }
const line = { line_key: uuid(8), quantity: 2, unit_price: '35.2750', discount_amount: '0.00', line_amount: '70.55', display_snapshot: { item_id: uuid(7), model_name: 'Genius Weft', color_name: 'Champagne', customer_sku: 'GW-CH', length: '22 in', weight: '25 g', unit: 'pack' } }
const previous = { ...structuredClone(line), quantity: 1, line_amount: '35.28' }
const changes = { items: [{ line_key: line.line_key, change: 'changed', before: previous, after: line }], fields: [{ field: 'shipping_amount', before: null, after: '45.00' }, { field: 'total_amount', before: null, after: '115.55' }, { field: 'delivery', before: { ...delivery, address_line1: 'Old address' }, after: delivery }] }
const base = { submitted_at: '2026-09-30T10:00:00', customer_po: 'PO-TEST', items: [line], delivery, remark: 'Customer note', currency: 'USD', product_amount: '70.55', total_amount: '115.55', payment_terms_snapshot: { code: 'prepay', display_text: 'Full payment before dispatch' }, fees: { status: 'confirmed', shipping_amount: '45.00', packaging_amount: '0.00', surcharge_amount: '0.00', surcharge_name: '' }, customer_safe_timeline: [{ event: 'order.submitted', at: '2026-09-30T10:00:00' }, { event: 'order.proposed', at: '2026-09-30T11:00:00' }] }
const proposal = { revision_id: uuid(4), content_hash: 'a'.repeat(64), expires_at: new Date(Date.now() + 600000).toISOString(), expired: false, accepted: false, changes }
const amendment = { ...structuredClone(base), ...proposal, revision_id: uuid(5), content_hash: 'b'.repeat(64), bound_invoice_document_version: 3, shipping_amount: '65.00', packaging_amount: '0.00', surcharge_amount: '0.00', total_amount: '135.55', fees: undefined, commercial_header: { invoice_no: 'PI-TEST-002', customer_name: 'Atelier Test Salon', express_channel: 'DHL', sales_user_name: 'Test representative' } }
const orders = [
  { ...structuredClone(base), request_id: uuid(1), request_no: 'REQ-TEST-001', status: 'awaiting_customer', row_version: 2, available_actions: ['accept_proposal', 'reject_proposal', 'cancel'], proposal: structuredClone(proposal) },
  { ...structuredClone(base), request_id: uuid(2), request_no: 'REQ-TEST-002', status: 'invoice_created', row_version: 6, available_actions: ['accept_pi', 'reject_pi'], pi_amendment: { status: 'pending_customer', proposal: amendment } },
  { ...structuredClone(base), request_id: uuid(3), request_no: 'REQ-TEST-003', status: 'submitted', row_version: 1, total_amount: null, available_actions: ['cancel'] },
]
const calls = [], errors = []
const injectMismatch = process.env.PORTAL_DECISION_RECEIPT_FAULT === 'wrong_revision'
assert.ok(!process.env.PORTAL_DECISION_RECEIPT_FAULT || injectMismatch)
let mismatchRemaining = injectMismatch
let lost = true, withdrawn = false, signedIn = true, acceptHeaders
await context.route('**/api/portal/v1/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, body = request.postDataJSON()
  calls.push({ path, method: request.method(), body, headers: request.headers() })
  const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status, message: status >= 400 ? 'This PI has changed. Refresh your request.' : 'OK', data }) })
  if (path.endsWith('/session')) return send(signedIn ? identity : { error_code: 'AUTH_REQUIRED' }, signedIn ? 200 : 401)
  if (path.endsWith('/catalog')) return send({ items: [], total: 0 })
  if (path.endsWith('/orders')) { const items = orders.filter(order => !url.searchParams.get('status') || order.status === url.searchParams.get('status')); return send({ items, total: items.length, page: 1, page_size: 20 }) }
  const order = orders.find(order => path.includes(order.request_id))
  if (order && path.endsWith('/action-receipt')) return send({ found: false, command: { request_id: order.request_id, ...Object.fromEntries(url.searchParams) } })
  if (order && path.endsWith('/reject')) { assert.equal(body.reason, 'Please update delivery'); assert.ok(path.includes(uuid(4))); return send({ error_code: 'PROPOSAL_CHANGED' }, 409) }
  if (order && path.endsWith('/accept')) {
    if (order.request_id === uuid(1)) {
      assert.equal(body.proposal_hash, 'a'.repeat(64)); assert.ok(path.includes(uuid(4)))
      if (lost) { acceptHeaders = request.headers()['if-match']; lost = false; order.status = 'ready_for_review'; order.row_version++; order.available_actions = ['cancel']; return route.abort('failed') }
      assert.equal(request.headers()['if-match'], acceptHeaders)
      order.status = 'invoice_created'; order.available_actions = ['download_pi']; order.pi_amendment = { status: 'current', proposal: null }; order.proposal = null; order.row_version++
    } else {
      assert.equal(body.proposal_hash, 'b'.repeat(64)); assert.ok(path.includes(uuid(5)))
      order.pi_amendment.status = 'accepted'; order.available_actions = []; order.row_version++
    }
    const response = { replayed: order.request_id === uuid(1), original_receipt: { request_id: order.request_id, revision_id: order.request_id === uuid(1) ? uuid(4) : uuid(5), content_hash: order.request_id === uuid(1) ? 'a'.repeat(64) : 'b'.repeat(64), row_version: order.request_id === uuid(1) ? 2 : order.row_version, ...(order.request_id === uuid(1) ? { status: 'ready_for_review' } : { invoice_document_version: 3 }) }, current_state: order.status, row_version: order.row_version, ...(order.request_id === uuid(1) ? {} : { amendment_state: order.pi_amendment.status }) }
    if (mismatchRemaining && order.request_id === uuid(1)) { mismatchRemaining = false; response.original_receipt.revision_id = uuid(6) }
    return send(response)
  }
  if (order && path.endsWith('/cancel')) { assert.equal(body.reason, 'No longer needed'); assert.equal(request.headers()['if-match'], '"1"'); order.status = 'cancelled'; order.available_actions = []; order.row_version++; return send({ original_receipt: { request_id: order.request_id, status: 'cancelled', row_version: order.row_version }, current_state: 'cancelled', row_version: order.row_version }) }
  if (order && path.endsWith('/pi')) {
    if (withdrawn) { order.pi_amendment = { status: 'withdrawn', proposal: null }; order.available_actions = []; return send({ error_code: 'PI_CHANGED' }, 409) }
    return route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4\n% synthetic test PDF\n%%EOF' })
  }
  if (order && request.method() === 'GET') return send(order)
  if (path.endsWith('/logout')) { signedIn = false; return send({ signed_out: true }) }
  throw new Error(`Unexpected ${path}`)
})
const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message))
try {
  await page.goto(`${origin}/orders`)
  await page.getByRole('heading', { name: 'Your requests.' }).waitFor()
  await page.getByRole('link', { name: /REQ-TEST-003/ }).waitFor()
  assert.equal(await page.locator('.order-list-item').count(), 3)
  await page.getByLabel('Request status').selectOption('awaiting_customer')
  await page.waitForFunction(() => document.querySelectorAll('.order-list-item').length === 1)
  await page.getByLabel('Request status').selectOption('')
  await page.waitForFunction(() => document.querySelectorAll('.order-list-item').length === 3)
  await page.getByRole('link', { name: /REQ-TEST-001/ }).click()
  await page.getByRole('button', { name: 'Review and accept proposal' }).waitFor()
  assert.match(await page.locator('.proposal-diff').innerText(), /Old address/)
  assert.match(await page.locator('.proposal-diff').innerText(), /10 Test Lane/)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1100 }); await page.evaluate(() => scrollTo(0, 0))
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: `${output}/order-proposal-${width}.png`, fullPage: true })
  }
  await page.getByRole('button', { name: 'Request changes', exact: true }).click()
  await page.getByRole('dialog').getByLabel('What would you like to change?').fill('Please update delivery')
  await page.getByRole('dialog').getByRole('button', { name: 'Request changes', exact: true }).click()
  await page.getByRole('alert').waitFor()
  await page.getByRole('button', { name: 'All requests' }).click()
  await page.getByRole('link', { name: /REQ-TEST-003/ }).click()
  await page.getByRole('button', { name: 'Cancel this request' }).waitFor()
  assert.equal(await page.getByRole('alert').count(), 0)
  await page.getByRole('button', { name: 'All requests' }).click()
  await page.getByRole('link', { name: /REQ-TEST-001/ }).click()
  await page.getByRole('button', { name: 'Review and accept proposal' }).waitFor()
  await page.getByRole('button', { name: 'Review and accept proposal' }).click()
  const dialog = page.getByRole('dialog', { name: 'Confirm request action' })
  assert.equal(await dialog.getByRole('button', { name: 'Accept proposal', exact: true }).isDisabled(), true)
  await page.keyboard.press('Escape')
  assert.equal(await page.getByRole('button', { name: 'Review and accept proposal' }).evaluate(el => el === document.activeElement), true)
  await page.getByRole('button', { name: 'Review and accept proposal' }).click()
  await dialog.getByRole('checkbox').check(); await dialog.getByRole('button', { name: 'Accept proposal', exact: true }).click()
  await page.getByRole('heading', { name: 'The action result needs confirmation.' }).waitFor()
  assert.equal(calls.filter(call => call.path.endsWith('/accept')).length, 1)
  await page.getByRole('link', { name: 'Collection', exact: true }).click()
  await page.getByRole('button', { name: 'View action status' }).click()
  const mismatchObservation = injectMismatch ? page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname.endsWith('/orders/' + uuid(1))) : null
  await page.getByRole('button', { name: 'Retry original action' }).click()
  if (injectMismatch) {
    const observed = await mismatchObservation; await observed.finished()
    await page.getByRole('heading', { name: 'The action result needs confirmation.' }).waitFor()
    assert.equal(await page.locator('.session-notice').filter({ hasText: 'Original action on' }).count(), 0)
    assert.equal(await page.getByRole('button', { name: 'Cancel this request' }).isDisabled(), true)
    assert.equal(calls.filter(call => call.path.endsWith('/accept')).length, 2)
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1100 })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      await page.screenshot({ path: `${output}/wrong-receipt-pending-${width}.png`, fullPage: true })
    }
    await page.getByRole('button', { name: 'Retry original action' }).click()
  }
  await page.locator('.session-notice').filter({ hasText: 'Original action on' }).waitFor()
  await page.getByRole('button', { name: 'Download confirmed PI' }).waitFor()
  assert.match(await page.locator('.session-notice').innerText(), /Request status when checked: PI created/)
  await page.getByRole('button', { name: 'All requests' }).click()
  await page.getByRole('link', { name: /REQ-TEST-003/ }).click()
  await page.getByRole('button', { name: 'Cancel this request' }).waitFor()
  assert.equal(await page.locator('.session-notice').count(), 0)
  await page.getByRole('button', { name: 'Cancel this request' }).click()
  await dialog.getByLabel('Reason for cancelling').fill('No longer needed')
  await dialog.getByRole('button', { name: 'Cancel request', exact: true }).click()
  await page.getByText('Request status when checked: Cancelled', { exact: false }).waitFor()
  await page.getByRole('button', { name: 'All requests' }).click()
  await page.getByRole('link', { name: /REQ-TEST-002/ }).click()
  await page.getByRole('button', { name: 'Review and accept PI update' }).waitFor()
  assert.equal(await page.locator('.session-notice').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Download confirmed PI' }).count(), 0)
  identity.capabilities.view_price = false; identity.capabilities.place_order = false
  orders[1].available_actions = []
  await page.reload()
  await page.getByRole('heading', { name: 'Last published request details' }).waitFor()
  assert.ok(!(await page.locator('.orders-page').innerText()).includes('USD'))
  assert.equal(await page.locator('.proposal-panel').count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Download confirmed PI' }).count(), 0)
  identity.capabilities.view_price = true; identity.capabilities.place_order = true
  orders[1].available_actions = ['accept_pi', 'reject_pi']
  await page.reload()
  await page.getByRole('button', { name: 'Review and accept PI update' }).waitFor()
  assert.match(await page.locator('.proposal-panel').innerText(), /USD 135.55/)
  assert.match(await page.locator('.proposal-panel').innerText(), /PI-TEST-002/)
  await page.getByRole('button', { name: 'Review and accept PI update' }).click()
  await dialog.getByRole('checkbox').check(); await dialog.getByRole('button', { name: 'Accept PI update', exact: true }).click()
  await page.getByRole('heading', { name: 'PI update accepted. Awaiting publication.' }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Download confirmed PI' }).count(), 0)
  orders[1].pi_amendment = { status: 'current', proposal: null }; orders[1].available_actions = ['download_pi']
  await page.getByRole('button', { name: 'Refresh details' }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download confirmed PI' }).click()
  assert.equal((await downloaded).suggestedFilename(), `LeShine-PI-${uuid(2)}.pdf`)
  withdrawn = true
  await page.getByRole('button', { name: 'Download confirmed PI' }).click()
  await page.getByRole('heading', { name: 'Your PI is being revised.' }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Download confirmed PI' }).count(), 0)
  const other = await context.newPage(); await other.goto(origin)
  await other.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.getByRole('button', { name: 'Continue with email' }).waitFor()
  assert.equal(await page.locator('.order-document').count(), 0)
  assert.deepEqual(errors, [])
  assert.ok(calls.filter(call => call.method === 'POST').every(call => call.headers['x-portal-csrf'] && !call.headers.authorization))
  console.log(JSON.stringify({ status: 'pass', injectedMismatch: injectMismatch, scope: 'Built frontend with intercepted test API and synthetic PDF only', assertions: ['direct order route and scoped status filter', 'proposal full diff and 1440/390/320 layout', 'explicit consent and modal focus', 'unknown action survives navigation and retries exact version/hash', 'replay uses current state', 'cancel reason and If-Match', 'confirmed and failed notices never cross orders', 'price-hidden scope omits money and proposal controls', 'PI update waits for publication', 'authenticated PDF download and changed-PI refresh', 'cross-tab logout clears details'], apiCalls: calls.length, screenshots: output }))
} finally { await browser.close() }
