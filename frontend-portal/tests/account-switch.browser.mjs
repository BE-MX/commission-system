import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210', output = process.env.PORTAL_QA_OUTPUT
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/); assert.ok(output); await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true }), results = []
const uuid = n => `${n.toString(16).padStart(8, '0')}-1111-4111-8111-111111111111`
const buyer = kind => ({ me: { account_public_id: uuid(kind === 'A' ? 1 : 2), company_display_name: kind + '_PRIVATE_COMPANY' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'synthetic-' + kind })
const product = kind => ({ item_id: uuid(kind === 'A' ? 11 : 12), model_name: kind + '_PRIVATE_MODEL', color_name: kind + '_PRIVATE_COLOR', customer_sku: kind + '_PRIVATE_SKU', length_display: '20in', weight_display: '25g', sale_unit: 'pack', min_order_qty: 1, step_qty: 1, category: 'hair', unit_price: kind === 'A' ? '71.2500' : '35.5000', availability: 'available' })
const orderId = kind => uuid(kind === 'A' ? 21 : 22)
const delivery = kind => ({ contact_name: kind + '_PRIVATE_BUYER', phone: '+44 123456789', address_line1: kind + '_PRIVATE_ADDRESS', address_line2: '', city: '', region: '', postal_code: '', country_code: 'GB' })
const line = kind => ({ line_key: uuid(kind === 'A' ? 31 : 32), item_id: product(kind).item_id, quantity: 1, unit_price: product(kind).unit_price, line_amount: kind === 'A' ? '71.25' : '35.50', discount_amount: '0.00', display_snapshot: { model_name: product(kind).model_name, color_name: product(kind).color_name, customer_sku: product(kind).customer_sku, length: '20in', weight: '25g', unit: 'pack' } })
const order = kind => ({ request_id: orderId(kind), request_no: kind + '_PRIVATE_REQUEST', status: 'invoice_created', row_version: 3, available_actions: ['download_pi'], pi_amendment: { status: 'current', proposal: null }, items: [line(kind)], currency: 'USD', product_amount: kind === 'A' ? '71.25' : '35.50', total_amount: kind === 'A' ? '71.25' : '35.50', delivery: delivery(kind), remark: kind + '_PRIVATE_REMARK', payment_terms_snapshot: { display_text: kind + '_PRIVATE_TERMS' }, fees: { status: 'confirmed', shipping_amount: '0.00', packaging_amount: '0.00', surcharge_amount: '0.00' }, customer_safe_timeline: [] })
async function login(page) {
  await page.getByLabel('Email address').fill('synthetic-b@example.test'); await page.getByRole('button', { name: 'Continue with email' }).click()
  await page.getByLabel('Verification code').fill('123456'); await page.getByRole('button', { name: 'Enter your collection' }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
}
async function select(page, kind) {
  await page.getByRole('button', { name: 'View ' + product(kind).model_name + ', ' + product(kind).color_name }).click()
  await page.getByRole('button', { name: 'Add to selection', exact: true }).click(); await page.getByRole('button', { name: 'Review selection', exact: true }).click()
  await page.getByLabel('Contact name', { exact: true }).fill(delivery(kind).contact_name); await page.getByLabel('Phone number').fill(delivery(kind).phone)
  await page.getByLabel('Address line 1', { exact: true }).fill(delivery(kind).address_line1); await page.getByLabel('Country code').fill('GB')
  await page.getByLabel('Your PO').fill(kind + '_PRIVATE_PO'); await page.getByLabel('Request notes').fill(kind + '_PRIVATE_NOTES')
}
try {
  for (const mode of ['catalog', 'order', 'quote', 'pi', 'contact']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true }), errors = [], calls = []; let current = 'A'
    await context.addInitScript(({ mode, oldOrderId }) => {
      window.__scopeAudit = { mode, marks: [], fetches: [], created: [], revoked: [], clicks: [], staleDom: [], nativeBroadcast: /\[native code\]/.test(String(window.BroadcastChannel)) }
      const audit = window.__scopeAudit, nativeFetch = window.fetch.bind(window), json = Response.prototype.json, blob = Response.prototype.blob
      window.fetch = (input, options = {}) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href)
        if (url.pathname.startsWith('/api/portal/v1/')) audit.fetches.push({ path: url.pathname, method: options.method || 'GET', credentials: options.credentials, cache: options.cache })
        // Ignore transport aborts for held reads; actual client scope/controller checks still execute.
        const next = { ...options }; if (window.__armScopeRead) delete next.signal
        return nativeFetch(input, next)
      }
      async function hold(response, data) {
        const path = new URL(response.url).pathname
        const matches = mode === 'catalog' ? path.endsWith('/catalog') : mode === 'order' ? path.endsWith('/orders/' + oldOrderId) : mode === 'quote' ? path.endsWith('/quotes') : mode === 'pi' ? path.endsWith('/orders/' + oldOrderId + '/pi') : path.endsWith('/sales-contact')
        if (window.__armScopeRead && matches && !audit.held) {
          audit.held = true; audit.heldPrivateA = data instanceof Blob ? (await data.text()).includes('A_PRIVATE_') : JSON.stringify(data).includes('A_PRIVATE_')
          audit.marks.push('body-held'); await new Promise(resolve => { window.__releaseScopeBody = resolve }); audit.marks.push('body-return')
        }
        return data
      }
      Response.prototype.json = async function () { return hold(this, await json.call(this)) }
      Response.prototype.blob = async function () { return hold(this, await blob.call(this)) }
      const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL), click = HTMLAnchorElement.prototype.click
      URL.createObjectURL = value => { const url = create(value); audit.created.push(url); return url }
      URL.revokeObjectURL = url => { audit.revoked.push(url); return revoke(url) }
      HTMLAnchorElement.prototype.click = function () { if (this.href.startsWith('blob:')) audit.clicks.push(this.download); return click.call(this) }
      window.__observeNewScope = () => {
        const observer = new MutationObserver(() => {
          const text = document.body.innerText + [...document.querySelectorAll('input,textarea')].map(el => el.value).join(' ')
          if (text.includes('A_PRIVATE_')) audit.staleDom.push(text.slice(0, 120))
        }); observer.observe(document.body, { childList: true, characterData: true, attributes: true, subtree: true })
      }
    }, { mode, oldOrderId: orderId('A') })
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
    const send = (route, data, status = 200) => route.fulfill({ status, headers: { 'Cache-Control': 'no-store' }, contentType: 'application/json', body: JSON.stringify({ code: status, message: status >= 400 ? 'Not available to this account.' : 'OK', data }) })
    await context.route('**/api/portal/v1/**', route => {
      const request = route.request(), path = new URL(request.url()).pathname, kind = current
      calls.push({ path, method: request.method(), identity: kind })
      if (path.endsWith('/session')) return send(route, current ? buyer(kind) : { error_code: 'AUTH_REQUIRED' }, current ? 200 : 401)
      if (path.endsWith('/auth/logout')) { current = null; return send(route, { signed_out: true }) }
      if (path.endsWith('/auth/bootstrap')) return send(route, { csrf_token: 'synthetic-preauth', expires_in: 600 })
      if (path.endsWith('/auth/challenges')) return send(route, { challenge_id: uuid(40), expires_in: 600, resend_after: 60 }, 202)
      if (path.endsWith('/auth/verify')) { assert.equal(request.postDataJSON().code, '123456'); current = 'B'; return send(route, buyer('B')) }
      assert.ok(current, 'Private request after synthetic logout')
      if (path.endsWith('/catalog')) return send(route, { items: [product(kind)], total: 1, page: 1, page_size: 24 })
      if (path.endsWith('/orders')) return send(route, { items: [order(kind)], total: 1, page: 1, page_size: 20 })
      if (path.endsWith('/orders/' + orderId(kind))) return send(route, order(kind))
      if (path.endsWith('/quotes')) { const body = request.postDataJSON(); assert.deepEqual(body.items, [{ item_id: product(kind).item_id, quantity: 1 }]); return send(route, { ...body, quote_id: uuid(kind === 'A' ? 51 : 52), status: 'valid', content_hash: (kind === 'A' ? 'a' : 'b').repeat(64), currency: 'USD', expires_at: new Date(Date.now() + 600000).toISOString(), product_amount: order(kind).product_amount, total_amount: null, fees: { status: 'pending', shipping_amount: null, packaging_amount: null, surcharge_amount: null }, payment_terms_snapshot: { display_text: kind + '_PRIVATE_TERMS' }, items: [line(kind)] }) }
      if (path.endsWith('/orders/' + orderId(kind) + '/pi')) return route.fulfill({ status: 200, contentType: 'application/pdf', headers: { 'Cache-Control': 'no-store' }, body: '%PDF-1.4\n% ' + kind + '_PRIVATE_PI\n%%EOF' })
      if (path.endsWith('/sales-contact')) return send(route, { contact: { display_name: kind + '_PRIVATE_REP', email: kind.toLowerCase() + '-private@example.test', whatsapp: null } })
      if (path.startsWith('/api/portal/v1/orders/')) return send(route, { error_code: 'RESOURCE_NOT_FOUND' }, 404)
      throw new Error('Unexpected ' + path)
    })
    const page = await context.newPage(), peer = await context.newPage(); page.on('pageerror', e => errors.push(e.message)); peer.on('pageerror', e => errors.push(e.message))
    try {
      await page.goto(origin + (['order', 'pi'].includes(mode) ? '/orders/' + orderId('A') : '/collection')); await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
      if (mode === 'catalog') await page.getByRole('button', { name: 'View A_PRIVATE_MODEL, A_PRIVATE_COLOR' }).waitFor()
      if (mode === 'order' || mode === 'pi') await page.getByRole('button', { name: 'Download confirmed PI' }).waitFor()
      if (mode === 'quote') await select(page, 'A')
      await peer.goto(origin + '/collection'); await peer.getByRole('button', { name: 'View A_PRIVATE_MODEL, A_PRIVATE_COLOR' }).waitFor()
      await page.evaluate(() => { window.__armScopeRead = true })
      if (mode === 'catalog') await page.getByLabel('Sort products').selectOption('name')
      if (mode === 'order') await page.getByRole('button', { name: 'Refresh details' }).click()
      if (mode === 'quote') await page.getByRole('button', { name: 'Review request', exact: true }).click()
      if (mode === 'pi') await page.getByRole('button', { name: 'Download confirmed PI' }).click()
      if (mode === 'contact') await page.getByRole('button', { name: 'Contact your representative' }).click()
      await page.waitForFunction(() => Boolean(window.__releaseScopeBody))
      await peer.getByRole('button', { name: 'Sign out', exact: true }).click(); await peer.getByLabel('Email address').waitFor(); await page.getByLabel('Email address').waitFor()
      await page.getByText('Your session changed in another tab. Sign in again to continue.', { exact: true }).waitFor()
      assert.equal(await page.locator('.portal-shell').count(), 0); assert.equal(await page.getByRole('dialog').count(), 0)
      await login(peer); await login(page); await peer.getByLabel('Email address').waitFor()
      await page.locator('.account-menu > span').filter({ hasText: 'B_PRIVATE_COMPANY' }).waitFor()
      if (mode === 'quote') {
        await page.getByRole('heading', { name: 'A new beginning.' }).waitFor(); await page.getByRole('link', { name: 'Collection', exact: true }).click(); await select(page, 'B')
        await page.getByRole('button', { name: 'Review request', exact: true }).click(); await page.getByRole('button', { name: 'Submit order request' }).waitFor(); assert.equal(await page.getByRole('checkbox').isChecked(), false)
      } else if (mode === 'order' || mode === 'pi') {
        await page.getByRole('link', { name: 'Requests', exact: true }).click(); await page.getByRole('link', { name: /B_PRIVATE_REQUEST/ }).click(); await page.getByRole('button', { name: 'Download confirmed PI' }).waitFor()
      } else if (mode === 'contact') {
        await page.getByRole('button', { name: 'Contact your representative' }).click(); await page.getByRole('heading', { name: 'B_PRIVATE_REP' }).waitFor()
      } else await page.getByRole('button', { name: 'View B_PRIVATE_MODEL, B_PRIVATE_COLOR' }).waitFor()
      await page.evaluate(() => window.__observeNewScope()); await page.evaluate(() => window.__releaseScopeBody())
      const audit = await page.evaluate(async () => { await new Promise(resolve => setTimeout(resolve, 0)); return window.__scopeAudit })
      assert.ok(audit.nativeBroadcast); assert.equal(audit.heldPrivateA, true); assert.ok(audit.marks.includes('body-return')); assert.deepEqual(audit.staleDom, []); assert.equal(audit.created.length, 0); assert.equal(audit.clicks.length, 0)
      const privateView = await page.evaluate(() => document.body.innerText + [...document.querySelectorAll('input,textarea')].map(el => el.value).join(' '))
      assert.equal(privateView.includes('A_PRIVATE_'), false); assert.equal(privateView.includes('USD 71.25'), false); assert.ok(privateView.includes('B_PRIVATE_'))
      if (mode === 'quote') {
        const review = page.getByRole('complementary', { name: 'Server review' }); assert.match(await review.innerText(), /B_PRIVATE_MODEL/); assert.match(await review.innerText(), /B_PRIVATE_ADDRESS/); assert.match(await review.innerText(), /USD 35\.50/)
        assert.equal(await page.getByLabel('Address line 1', { exact: true }).inputValue(), 'B_PRIVATE_ADDRESS'); assert.equal(await page.getByRole('checkbox').isChecked(), false)
      } else if (mode === 'order' || mode === 'pi') {
        await page.getByRole('button', { name: 'Download confirmed PI' }).waitFor(); assert.match(await page.locator('.order-document').innerText(), /B_PRIVATE_MODEL/); assert.match(await page.locator('.order-document').innerText(), /B_PRIVATE_ADDRESS/); assert.match(await page.locator('.order-document').innerText(), /USD 35\.50/)
      } else if (mode === 'contact') { await page.getByRole('heading', { name: 'B_PRIVATE_REP' }).waitFor(); assert.match(await page.getByRole('dialog').innerText(), /b-private@example\.test/) }
      else { await page.getByRole('button', { name: 'View B_PRIVATE_MODEL, B_PRIVATE_COLOR' }).waitFor(); assert.match(await page.locator('.product-bottom').innerText(), /USD 35\.5/) }
      assert.ok(audit.fetches.length); assert.ok(audit.fetches.every(call => call.credentials === 'same-origin' && call.cache === 'no-store'))
      const browserState = await page.evaluate(async () => ({ storage: JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }), caches: await caches.keys(), workers: (await navigator.serviceWorker.getRegistrations()).length }))
      assert.equal(browserState.storage.includes('A_PRIVATE_'), false); assert.equal(browserState.storage.includes('B_PRIVATE_'), false); assert.deepEqual(browserState.caches, []); assert.equal(browserState.workers, 0)
      if (mode === 'pi') {
        const downloaded = page.waitForEvent('download'); await page.getByRole('button', { name: 'Download confirmed PI' }).click(); const file = await downloaded
        assert.equal(file.suggestedFilename(), 'LeShine-PI-' + orderId('B') + '.pdf'); await file.saveAs(output + '/B-synthetic.pdf')
        const bytes = await readFile(output + '/B-synthetic.pdf', 'utf8'); assert.ok(bytes.includes('B_PRIVATE_PI')); assert.equal(bytes.includes('A_PRIVATE_PI'), false)
      }
      assert.deepEqual(errors, []); await page.screenshot({ path: output + '/' + mode + '.png', fullPage: true })
      results.push({ mode, nativeBroadcast: audit.nativeBroadcast, heldBodyReturned: true, staleDom: audit.staleDom.length, oldBlobUrls: audit.created.length, apiCalls: calls.length, noStoreFetches: audit.fetches.length, pageErrors: errors.length })
    } catch (error) { await page.screenshot({ path: output + '/failure-' + mode + '.png', fullPage: true }); await writeFile(output + '/failure-' + mode + '.json', JSON.stringify({ audit: await page.evaluate(() => window.__scopeAudit), calls, errors }, null, 2)); throw error }
    finally { await context.close() }
  }
  await writeFile(output + '/result.json', JSON.stringify({ status: 'pass', scope: 'Real built customer App/client and two native BroadcastChannel tabs; intercepted API identities and synthetic PDF; no actual backend/cookies/proxy cache evidence.', results }, null, 2)); console.log(JSON.stringify({ status: 'pass', cases: results.length, output }))
} finally { await browser.close() }