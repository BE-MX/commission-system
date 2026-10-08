import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT
assert.ok(output, 'Use an explicit owned evidence directory')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.PORTAL_CHROMIUM })
const uuid = n => `${n}1111111-1111-4111-8111-111111111111`
const results = []
function gate() { let release; const waiting = new Promise(resolve => { release = resolve }); return { waiting, release } }
async function reach(page, target, reverse = false) {
  await target.waitFor({ state: 'visible' })
  for (let i = 0; i < 85; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return
    await page.keyboard.press(reverse ? 'Shift+Tab' : 'Tab')
  }
  throw new Error(`Keyboard cannot reach ${await target.evaluate(el => el.outerHTML)}`)
}
async function activate(page, target, key = 'Enter') { await reach(page, target); await page.keyboard.press(key) }
async function type(page, target, value) { await reach(page, target); await page.keyboard.press('Control+A'); await page.keyboard.type(value) }
async function geometry(page, label) {
  const bad = await page.evaluate(() => {
    const bad = []
    if (document.documentElement.scrollWidth > innerWidth) bad.push(`root ${document.documentElement.scrollWidth}>${innerWidth}`)
    for (const el of document.querySelectorAll('main button, main input, main select, main textarea, dialog[open] button, dialog[open] input')) {
      const r = el.getBoundingClientRect()
      if (r.width && r.height && (r.left < -1 || r.right > innerWidth + 1 || (el.closest('dialog[open]') && (r.top < -1 || r.bottom > innerHeight + 1)))) bad.push(`${el.tagName} ${el.textContent.trim().slice(0, 40)} [${r.left},${r.right}]`)
    }
    return bad
  })
  assert.deepEqual(bad, [], label)
}
try {
  for (const width of [1440, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', acceptDownloads: true })
    const page = await context.newPage(), errors = [], calls = []
    page.on('pageerror', error => errors.push(error.message))
    const model = 'SignatureWeft'.repeat(10).slice(0, 128), color = 'ChampagnePearl'.repeat(10).slice(0, 128)
    const product = { item_id: uuid(2), model_name: model, color_name: color, customer_sku: 'GW'.repeat(32), category: 'hair', availability: 'available', unit_price: '35.2750', min_order_qty: 1, step_qty: 1, length_display: '22 in', weight_display: '25 g', sale_unit: 'pack', image_url: `/api/portal/v1/catalog/${uuid(2)}/image?version=1` }
    const items = [product, { ...product, item_id: uuid(3), model_name: 'Unavailable Weft', color_name: 'Sand', availability: 'unavailable', image_url: null }, { ...product, item_id: uuid(4), model_name: 'Unknown Weft', color_name: 'Cocoa', availability: 'unknown', image_url: null }]
    const identity = { me: { account_public_id: uuid(1), company_display_name: 'Atelier partner salon' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'owned-test-csrf' }
    let signedIn = false, catalogGate = gate(), quoteGate, quoteError = true, submitGate, acceptGate, piGate, order, quoteBody, imageRequests = 0
    const send = (route, data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status, message: status >= 400 ? 'Please review and try again.' : 'OK', data }) })
    await context.route('**/api/portal/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname, body = request.postDataJSON()
      calls.push({ path, method: request.method(), body, headers: request.headers() })
      if (path.endsWith('/image')) { imageRequests++; return route.fulfill({ status: 404 }) }
      if (path.endsWith('/session')) return send(route, signedIn ? identity : { error_code: 'AUTH_REQUIRED' }, signedIn ? 200 : 401)
      if (path.endsWith('/bootstrap')) return send(route, { csrf_token: 'owned-preauth', expires_in: 600 })
      if (path.endsWith('/challenges')) return send(route, { challenge_id: uuid(1), expires_in: 600, resend_after: 60 }, 202)
      if (path.endsWith('/verify')) {
        if (body.code !== '123456') return send(route, { error_code: 'AUTH_FAILED' }, 401)
        signedIn = true; return send(route, identity)
      }
      if (path.endsWith('/catalog')) { await catalogGate.waiting; return send(route, { items, total: items.length, page: 1, page_size: 24 }) }
      if (path.endsWith('/quotes')) {
        await quoteGate.waiting
        if (quoteError) return send(route, { error_code: 'INVENTORY_UNAVAILABLE' }, 503)
        assert.deepEqual(body.items, [{ item_id: product.item_id, quantity: 2 }]); assert.equal(body.delivery.address_line1.length, 200); quoteBody = structuredClone(body)
        return send(route, { ...body, quote_id: uuid(5), content_hash: 'a'.repeat(64), status: 'valid', currency: 'USD', expires_at: new Date(Date.now() + 600000).toISOString(), product_amount: '70.55', total_amount: null, fees: { status: 'pending', shipping_amount: null, packaging_amount: null, surcharge_amount: null }, payment_terms_snapshot: { display_text: 'Full payment before dispatch' }, items: [{ line_key: uuid(8), item_id: product.item_id, display_snapshot: { model_name: model, color_name: color, customer_sku: product.customer_sku, length: '22 in', weight: '25 g', unit: 'pack' }, quantity: 2, unit_price: product.unit_price, discount_amount: '0.00', line_amount: '70.55' }] })
      }
      if (path.endsWith('/orders') && request.method() === 'POST') {
        await submitGate.waiting
        assert.deepEqual(body, { quote_id: uuid(5), quote_content_hash: 'a'.repeat(64), customer_po: 'PO-KEYBOARD', remark: '' })
        const line = { line_key: uuid(8), display_snapshot: { model_name: model, color_name: color, customer_sku: product.customer_sku, length: '22 in', weight: '25 g', unit: 'pack' }, quantity: 2, unit_price: product.unit_price, discount_amount: '0.00', line_amount: '70.55' }
        order = { request_id: uuid(6), request_no: 'REQ-KEYBOARD-001', row_version: 2, status: 'awaiting_customer', submitted_at: '2026-10-04T10:00:00+08:00', currency: 'USD', product_amount: '70.55', total_amount: '115.55', delivery: quoteBody.delivery, customer_po: body.customer_po, remark: body.remark, items: [line], fees: { status: 'confirmed', shipping_amount: '45.00', packaging_amount: '0.00', surcharge_amount: '0.00' }, payment_terms_snapshot: { display_text: 'Full payment before dispatch' }, customer_safe_timeline: [{ event: 'order.submitted', at: '2026-10-04T10:00:00+08:00' }], available_actions: ['accept_proposal', 'reject_proposal'], proposal: { revision_id: uuid(7), content_hash: 'b'.repeat(64), expires_at: new Date(Date.now() + 600000).toISOString(), changes: { items: [], fields: [{ field: 'shipping_amount', before: null, after: '45.00' }] } } }
        return send(route, { request_id: order.request_id, request_no: order.request_no, row_version: 1, status: 'submitted' }, 201)
      }
      if (path.endsWith('/accept')) {
        await acceptGate.waiting
        assert.equal(body.proposal_hash, 'b'.repeat(64)); assert.equal(request.headers()['if-match'], '"2"')
        order.status = 'ready_for_review'; order.row_version = 3; order.proposal = null; order.available_actions = []
        return send(route, { original_receipt: { request_id: order.request_id, status: order.status }, current_state: order.status, row_version: 3 })
      }
      if (path.endsWith('/pi')) { await piGate.waiting; return route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4\n% synthetic keyboard fixture\n%%EOF' }) }
      if (order && path.endsWith('/' + order.request_id)) return send(route, order)
      if (path.endsWith('/logout')) { signedIn = false; return send(route, { signed_out: true }) }
      throw new Error(`Unexpected test API: ${request.method()} ${path}`)
    })
    try {
      await page.goto(origin)
      await type(page, page.getByLabel('Email address'), 'buyer@example.test')
      await activate(page, page.getByRole('button', { name: 'Continue with email' }))
      await page.getByLabel('Verification code').waitFor()
      assert.equal(await page.getByLabel('Verification code').evaluate(el => el === document.activeElement), true)
      await page.keyboard.type('000000'); await page.keyboard.press('Enter')
      await page.getByRole('alert').waitFor()
      assert.equal(await page.getByLabel('Verification code').evaluate(el => el === document.activeElement && el.value === '' && el.getAttribute('aria-invalid') === 'true' && el.getAttribute('aria-describedby').split(' ').includes('login-error')), true)
      await page.keyboard.type('123456'); await page.keyboard.press('Enter')
      await page.getByText('Loading your collection…', { exact: true }).waitFor()
      assert.equal(await page.locator('.collection-results').getAttribute('aria-live'), 'polite')
      catalogGate.release()
      await page.locator('.product-card').first().waitFor()
      await page.waitForFunction(() => document.querySelectorAll('.product-monogram').length === 3)
      assert.equal(imageRequests, 1)
      // Missing preferred font: verify the actual glyph renderer, not only fontFamily text.
      await page.addStyleTag({ content: ':root { --portal-font: "PortalMissingFont142", "Segoe UI", Arial, sans-serif; --portal-display: "PortalMissingFont142", "Segoe UI", Arial, sans-serif; }' })
      const cdp = await context.newCDPSession(page); await cdp.send('DOM.enable'); await cdp.send('CSS.enable')
      const root = await cdp.send('DOM.getDocument'), node = await cdp.send('DOM.querySelector', { nodeId: root.root.nodeId, selector: '.collection-results' })
      const fonts = (await cdp.send('CSS.getPlatformFontsForNode', { nodeId: node.nodeId })).fonts
      assert.ok(fonts.some(font => font.glyphCount > 0 && !font.isCustomFont && !font.familyName.includes('PortalMissingFont142')))
      await geometry(page, `long collection ${width}`)
      await page.screenshot({ path: `${output}/collection-${width}.png`, fullPage: true })
      for (const [name, state] of [['Unavailable Weft, Sand', 'Currently unavailable'], ['Unknown Weft, Cocoa', 'Availability pending']]) {
        const trigger = page.getByRole('button', { name: `View ${name}`, exact: true })
        await activate(page, trigger)
        const dialog = page.getByRole('dialog')
        assert.match(await dialog.innerText(), new RegExp(state)); assert.equal(await dialog.getByRole('button', { name: 'Add to selection' }).count(), 0)
        await geometry(page, `${state} ${width}`); await page.keyboard.press('Escape')
        assert.equal(await trigger.evaluate(el => el === document.activeElement), true)
      }
      await activate(page, page.getByRole('button', { name: `View ${model}, ${color}`, exact: true }))
      await geometry(page, `long dialog ${width}`)
      const specifications = page.getByRole('region', { name: 'Product specifications' })
      if (width <= 390) {
        await reach(page, specifications)
        assert.equal(await specifications.evaluate(el => el.scrollHeight > el.clientHeight), true)
        await page.keyboard.press('PageDown')
        await page.waitForFunction(() => document.querySelector('[aria-label="Product specifications"]').scrollTop > 0)
        await page.keyboard.press('End')
        await page.waitForFunction(() => { const el = document.querySelector('[aria-label="Product specifications"]'); return el.scrollTop + el.clientHeight >= el.scrollHeight - 1 })
        await geometry(page, `scrolled dialog ${width}`)
      }
      const scrollEvidence = await specifications.evaluate(el => ({ scrollTop: el.scrollTop, clientHeight: el.clientHeight, scrollHeight: el.scrollHeight }))
      await page.screenshot({ path: `${output}/product-${width}.png` })
      await type(page, page.getByRole('dialog').getByLabel('Quantity'), '1')
      await page.keyboard.press('ArrowUp')
      assert.equal(await page.getByRole('dialog').getByLabel('Quantity').inputValue(), '2')
      await activate(page, page.getByRole('button', { name: 'Add to selection', exact: true }), 'Space')
      await activate(page, page.getByRole('button', { name: 'Review selection', exact: true }))
      await page.getByRole('heading', { name: 'Your selection.' }).waitFor()
      await activate(page, page.getByRole('button', { name: 'Review request', exact: true }))
      assert.equal(await page.getByLabel('Contact name', { exact: true }).evaluate(el => el === document.activeElement && el.validity.valueMissing), true)
      assert.equal(calls.filter(call => call.path.endsWith('/quotes')).length, 0)
      for (const [label, value] of [['Contact name', 'Keyboard buyer'], ['Phone number', '+44 123456'], ['Address line 1', 'LongAddress'.repeat(19).slice(0, 200)], ['City', 'London'], ['Country code (e.g. US, GB)', 'GB'], ['Your PO / reference (optional)', 'PO-KEYBOARD']]) await type(page, page.getByLabel(label, { exact: true }), value)
      quoteGate = gate()
      await activate(page, page.getByRole('button', { name: 'Review request', exact: true }))
      const reviewing = page.getByRole('button', { name: 'Reviewing availability and pricing…', exact: true })
      await reviewing.waitFor(); assert.equal(await reviewing.isDisabled(), true)
      quoteGate.release()
      await page.getByRole('alert').waitFor()
      assert.equal(await page.getByRole('alert').evaluate(el => el === document.activeElement), true)
      assert.equal(await page.getByLabel('Address line 1', { exact: true }).inputValue(), 'LongAddress'.repeat(19).slice(0, 200))
      quoteError = false; quoteGate = gate()
      await activate(page, page.getByRole('button', { name: 'Review request', exact: true }))
      await reviewing.waitFor(); quoteGate.release()
      const review = page.getByRole('complementary', { name: 'Server review' })
      await page.getByRole('button', { name: 'Submit order request' }).waitFor()
      assert.equal(await review.evaluate(el => el === document.activeElement), true)
      await geometry(page, `long quote ${width}`)
      await page.screenshot({ path: `${output}/checkout-${width}.png`, fullPage: true })
      await activate(page, page.getByRole('checkbox'), 'Space')
      submitGate = gate()
      await activate(page, page.getByRole('button', { name: 'Submit order request' }))
      await page.getByRole('heading', { name: 'Sending your request…' }).waitFor()
      assert.equal(await page.locator('.recovery-panel').getAttribute('aria-live'), 'polite')
      submitGate.release()
      await page.getByRole('heading', { name: 'Thank you. We’ll take it from here.' }).waitFor()
      await activate(page, page.getByRole('button', { name: 'View request', exact: true }))
      await page.getByRole('button', { name: 'Review and accept proposal' }).waitFor()
      const accept = page.getByRole('button', { name: 'Review and accept proposal' })
      await activate(page, accept); await page.keyboard.press('Escape')
      assert.equal(await accept.evaluate(el => el === document.activeElement), true)
      await activate(page, accept)
      await activate(page, page.getByRole('dialog').getByRole('checkbox'), 'Space')
      acceptGate = gate()
      await activate(page, page.getByRole('dialog').getByRole('button', { name: 'Accept proposal', exact: true }))
      await page.getByRole('heading', { name: 'Recording your decision…' }).waitFor()
      assert.equal(await page.locator('.order-command-notice').getAttribute('aria-live'), 'polite')
      acceptGate.release()
      await page.getByText(/Original action on REQ-KEYBOARD-001 was recorded/).waitFor()
      assert.equal(order.status, 'ready_for_review')
      // Simulated employee approval/publication, not a claim of employee keyboard coverage.
      order.status = 'invoice_created'; order.row_version = 4; order.available_actions = ['download_pi']; order.pi_amendment = { status: 'current', proposal: null }
      await activate(page, page.getByRole('button', { name: 'Refresh details', exact: true }))
      const download = page.getByRole('button', { name: 'Download confirmed PI', exact: true })
      await download.waitFor(); piGate = gate()
      const downloadEvent = page.waitForEvent('download')
      await activate(page, download)
      const preparing = page.getByRole('button', { name: 'Preparing your PDF…', exact: true })
      await preparing.waitFor(); assert.equal(await preparing.isDisabled(), true)
      piGate.release()
      const pdf = await downloadEvent
      assert.equal(pdf.suggestedFilename(), `LeShine-PI-${uuid(6)}.pdf`)
      await pdf.saveAs(`${output}/keyboard-${width}.pdf`)
      await download.waitFor()
      await geometry(page, `long order ${width}`)
      assert.equal(await download.evaluate(el => getComputedStyle(el).transitionDuration), '0s')
      await page.screenshot({ path: `${output}/order-${width}.png`, fullPage: true })
      assert.deepEqual(errors, [])
      assert.equal(calls.filter(call => call.path.endsWith('/accept')).length, 1)
      assert.equal(calls.filter(call => call.path.endsWith('/orders') && call.method === 'POST').length, 1)
      results.push({ width, fonts, scrollEvidence, longTextLengths: { model: model.length, color: color.length, customerSku: product.customer_sku.length, address: 200 }, reducedMotion: true, apiCalls: calls.length, keyboard: 'login/error recovery/select/quantity/native invalid/review/error recovery/submit/customer accept/PI download', scope: 'Built UI, intercepted API, simulated employee publication; no real credentials or SMTP' })
    } catch (error) { await page.screenshot({ path: `${output}/failure-${width}.png`, fullPage: true }); throw error }
    finally { catalogGate.release(); quoteGate?.release(); submitGate?.release(); acceptGate?.release(); piGate?.release(); await context.close() }
  }
  await writeFile(`${output}/result.json`, JSON.stringify({ status: 'pass', results }, null, 2))
  console.log(JSON.stringify({ status: 'pass', results, output }))
} finally { await browser.close() }
