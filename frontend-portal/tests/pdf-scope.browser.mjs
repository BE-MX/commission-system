import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210', output = process.env.PORTAL_QA_OUTPUT
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/); assert.ok(output); await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true }), results = []
const uuid = n => `${n}1111111-1111-4111-8111-111111111111`
const identity = { me: { account_public_id: uuid(9), company_display_name: 'Synthetic Company A' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'synthetic-csrf' }
const order = { request_id: uuid(1), request_no: 'REQ-SYNTHETIC-A', status: 'invoice_created', row_version: 3, available_actions: ['download_pi'], pi_amendment: { status: 'current', proposal: null }, items: [], currency: 'USD', product_amount: '0.00', total_amount: '0.00', delivery: { contact_name: 'Synthetic buyer', country_code: 'GB', address_line1: 'Synthetic address' }, fees: { status: 'confirmed', shipping_amount: '0.00', packaging_amount: '0.00', surcharge_amount: '0.00' }, customer_safe_timeline: [] }
try {
  for (const mode of (process.env.PORTAL_PDF_CASE ? [process.env.PORTAL_PDF_CASE] : ['continuation-race', 'held-body', 'navigation', 'normal'])) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true }), errors = [], calls = []
    await context.addInitScript(({ mode }) => {
      const audit = window.__pdfAudit = { mode, marks: [], created: [], revoked: [], clicks: [] }, channels = []
      // The app/client remain real; only cross-tab delivery is controlled to select a microtask boundary.
      window.BroadcastChannel = class {
        listeners = new Set()
        constructor() { channels.push(this) }
        addEventListener(type, listener) { if (type === 'message') this.listeners.add(listener) }
        removeEventListener(type, listener) { if (type === 'message') this.listeners.delete(listener) }
        postMessage() {}
        close() { this.listeners.clear() }
        fire() { for (const listener of this.listeners) listener({ data: { type: 'portal-session-changed' } }) }
      }
      window.__invalidatePdfScope = () => { audit.marks.push('scope-clear'); for (const channel of channels) channel.fire() }
      const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL), click = HTMLAnchorElement.prototype.click
      URL.createObjectURL = blob => { const url = create(blob); audit.marks.push('blob-url'); audit.created.push(url); return url }
      URL.revokeObjectURL = url => { audit.revoked.push(url); return revoke(url) }
      HTMLAnchorElement.prototype.click = function () { if (this.href.startsWith('blob:')) { audit.marks.push('download-click'); audit.clicks.push(this.download) }; return click.call(this) }
      const nativeBlob = Response.prototype.blob
      Response.prototype.blob = async function () {
        const blob = await nativeBlob.call(this)
        if (this.headers.get('content-type')?.split(';')[0] === 'application/pdf') {
          audit.marks.push('body-ready')
          if (mode === 'held-body' || mode === 'navigation') await new Promise(resolve => { window.__releasePdfBody = resolve })
          if (mode === 'continuation-race') queueMicrotask(() => queueMicrotask(window.__invalidatePdfScope))
        }
        audit.marks.push('body-return'); return blob
      }
    }, { mode })
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
    const send = (route, data, status = 200) => route.fulfill({ status, headers: { 'Cache-Control': 'no-store' }, contentType: 'application/json', body: JSON.stringify({ code: status, message: 'OK', data }) })
    await context.route('**/api/portal/v1/**', route => {
      const request = route.request(), path = new URL(request.url()).pathname
      calls.push({ path, method: request.method(), cacheControl: request.headers()['cache-control'] || null })
      if (path.endsWith('/session')) return send(route, identity)
      if (path.endsWith('/catalog')) return send(route, { items: [], total: 0 })
      if (path.endsWith('/orders/' + uuid(1))) return send(route, order)
      if (path.endsWith('/orders/' + uuid(1) + '/pi')) return route.fulfill({ status: 200, contentType: 'application/pdf', headers: { 'Cache-Control': 'no-store' }, body: '%PDF-1.4\n% synthetic test PDF\n%%EOF' })
      throw new Error('Unexpected ' + request.method() + ' ' + path)
    })
    const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message))
    try {
      await page.goto(origin + '/orders/' + uuid(1)); const button = page.getByRole('button', { name: 'Download confirmed PI', exact: true }); await button.waitFor()
      const download = mode === 'normal' ? page.waitForEvent('download') : null
      await button.click()
      if (mode === 'held-body') {
        await page.waitForFunction(() => Boolean(window.__releasePdfBody)); await page.evaluate(() => window.__invalidatePdfScope())
        await page.getByText('Your session changed in another tab. Sign in again to continue.', { exact: true }).waitFor(); await page.evaluate(() => window.__releasePdfBody())
      } else if (mode === 'navigation') {
        await page.waitForFunction(() => Boolean(window.__releasePdfBody)); await page.getByRole('link', { name: 'Collection', exact: true }).click(); await page.getByRole('heading', { name: 'Your next signature.' }).waitFor(); await page.evaluate(() => window.__releasePdfBody())
      } else if (mode === 'normal') {
        const file = await download; assert.equal(file.suggestedFilename(), 'LeShine-PI-' + uuid(1) + '.pdf'); await file.saveAs(output + '/synthetic.pdf')
        await page.getByRole('link', { name: 'Collection', exact: true }).click()
        await page.waitForFunction(() => window.__pdfAudit.revoked.length === 1)
      } else await page.getByText('Your session changed in another tab. Sign in again to continue.', { exact: true }).waitFor()
      // Wait for the actual continuation rather than treating a pending body as evidence of cancellation.
      const audit = await page.evaluate(async () => { await new Promise(resolve => setTimeout(resolve, 0)); return window.__pdfAudit })
      assert.ok(audit.marks.includes('body-return'), 'The PDF body continuation must have actually run')
      if (mode === 'continuation-race') assert.ok(audit.marks.indexOf('body-return') < audit.marks.indexOf('scope-clear'), 'Clear identity after body return to exercise the consumer continuation')
      assert.deepEqual(errors, []); assert.equal(calls.filter(c => c.path.endsWith('/pi')).length, 1)
      if (mode === 'normal') { assert.equal(audit.created.length, 1); assert.equal(audit.clicks.length, 1); assert.deepEqual(audit.revoked, audit.created) }
      else { assert.equal(audit.created.length, 0, mode + ': revoked scope/navigation must never create a blob URL'); assert.equal(audit.clicks.length, 0); assert.equal(audit.revoked.length, 0) }
      if (mode.includes('race') || mode === 'held-body') { assert.equal(await page.locator('.portal-shell').count(), 0); assert.equal(await page.getByText('Synthetic Company A', { exact: true }).count(), 0) }
      await page.screenshot({ path: output + '/' + mode + '.png', fullPage: true })
      results.push({ mode, ...audit, requestCount: calls.length, pageErrors: errors.length })
    } catch (error) { await page.screenshot({ path: output + '/failure-' + mode + '.png', fullPage: true }); await writeFile(output + '/failure-' + mode + '.json', JSON.stringify({ audit: await page.evaluate(() => window.__pdfAudit), calls, errors }, null, 2)); throw error }
    finally { await context.close() }
  }
  await writeFile(output + '/result.json', JSON.stringify({ status: 'pass', scope: 'Built customer App/client; intercepted API and synthetic PDF. Cross-tab transport/body timing controlled; no actual backend/cookies or server cache proof.', results }, null, 2)); console.log(JSON.stringify({ status: 'pass', cases: results.length, output }))
} finally { await browser.close() }