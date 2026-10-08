import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const evidenceFiles = JSON.parse(process.env.PORTAL_TIME_EVIDENCE_FILES || '[]')
assert.equal(evidenceFiles.length, 2, 'Supply two actual MySQL/HTTP time evidence files')
const evidence = await Promise.all(evidenceFiles.map(async path => JSON.parse(await readFile(path, 'utf8'))))
assert.deepEqual(evidence.map(row => row.server_default_zone), ['UTC', 'America/Los_Angeles'])
const output = process.env.PORTAL_QA_OUTPUT || 'tmp/beijing-midnight-qa'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.PORTAL_CHROMIUM ? { executablePath: process.env.PORTAL_CHROMIUM } : {}) })
const before = '05 Oct 2026, 23:59 (Beijing)', after = '06 Oct 2026, 00:00 (Beijing)'
const results = []
function encodeTimes(data, encoding) {
  if (encoding === 'naive') return structuredClone(data)
  return JSON.parse(JSON.stringify(data, (key, value) => {
    if (!['submitted_at', 'at', 'expires_at'].includes(key) || typeof value !== 'string') return value
    if (encoding === 'utc') return new Date(value + '+08:00').toISOString()
    return value + '+08:00'
  }))
}
try {
  for (const source of evidence) {
    assert.equal(source.invoice_date, '2026-10-06')
    assert.deepEqual(source.details.map(row => row.submitted_at), ['2026-10-05T23:59:59', '2026-10-06T00:00:01'])
    for (const timezoneId of ['UTC', 'America/Los_Angeles']) for (const encoding of ['naive', 'utc', 'offset']) {
      const context = await browser.newContext({ timezoneId, viewport: { width: 1440, height: 1100 } })
      const details = encodeTimes(source.details, encoding), listing = encodeTimes(source.listing, encoding)
      const calls = [], errors = []
      try {
        await context.route('https://fonts.googleapis.com/**', route => route.abort())
        await context.route('https://fonts.gstatic.com/**', route => route.abort())
        await context.route('**/api/portal/v1/**', async route => {
          const request = route.request(), path = new URL(request.url()).pathname
          assert.equal(request.method(), 'GET', 'Timezone proof never makes a business write')
          calls.push(path)
          const send = data => route.fulfill({ status: 200, contentType: 'application/json', headers: { 'Cache-Control': 'no-store' }, body: JSON.stringify({ code: 200, message: 'OK', data }) })
          if (path.endsWith('/session')) return send({ me: { account_public_id: '91111111-1111-4111-8111-111111111111', company_display_name: 'Isolated time evidence buyer' }, capabilities: { view_catalog: true, view_price: true, place_order: true }, csrf_token: 'synthetic-time-csrf' })
          if (path.endsWith('/catalog')) return send({ items: [], total: 0 })
          if (path.endsWith('/orders')) return send(listing)
          const order = details.find(row => path.endsWith('/orders/' + row.request_id))
          assert.ok(order, `Unexpected time QA endpoint ${path}`)
          return send(order)
        })
        const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message))
        await page.goto(origin + '/orders')
        await page.getByRole('heading', { name: 'Your requests.' }).waitFor()
        await page.locator('.order-list-item').first().waitFor()
        assert.equal(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone), timezoneId)
        assert.equal(await page.evaluate(() => new Date('2026-10-05T16:00:01Z').getDate()), 5, 'Local date must differ from Beijing at midnight')
        assert.equal(await page.locator('.order-list-item').count(), 2)
        for (const [index, expected] of [before, after].entries()) {
          const row = page.locator('.order-list-item').filter({ has: page.locator(`a[href="/orders/${details[index].request_id}"]`) })
          assert.ok((await row.innerText()).includes(expected))
        }
        await page.locator(`a[href="/orders/${details[0].request_id}"]`).click()
        await page.locator('.order-timeline time').first().waitFor()
        assert.ok((await page.locator('.order-summary-bar').innerText()).includes(before))
        assert.deepEqual(await page.locator('.order-timeline time').allTextContents(), [before, after, after, after])
        if (encoding === 'naive') await page.screenshot({ path: join(output, `${source.server_default_zone.replaceAll('/', '-')}-${timezoneId.replaceAll('/', '-')}.png`), fullPage: true })
        await page.getByRole('button', { name: 'All requests', exact: false }).click()
        await page.locator(`a[href="/orders/${details[1].request_id}"]`).click()
        await page.locator('.order-timeline time').first().waitFor()
        assert.ok((await page.locator('.order-summary-bar').innerText()).includes(after))
        assert.deepEqual(await page.locator('.order-timeline time').allTextContents(), [after])
        assert.deepEqual(errors, [])
        results.push({ sourceServerZone: source.server_default_zone, databaseZone: source.mysql_session_zone, browserZone: timezoneId, encoding, listTimes: [before, after], firstTimeline: [before, after, after, after], secondTimeline: [after], apiCalls: calls.length, pageErrors: errors.length })
      } finally { await context.close() }
    }
  }
  const result = { status: 'pass', scope: 'Real built customer UI replaying actual isolated MySQL ASGI HTTP projections; session mocked. UTC/offset variants are equivalent-instant transforms. No live backend or production proof.', evidenceFiles, cases: results }
  await writeFile(join(output, 'result.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify({ status: result.status, cases: results.length, output, scope: result.scope }))
} finally { await browser.close() }
