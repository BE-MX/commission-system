import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const [origin, modulePath, executablePath] = process.argv.slice(2)
const require = createRequire(import.meta.url)
const { chromium } = require(modulePath)
let input = ''
for await (const chunk of process.stdin) input += chunk
const { token } = JSON.parse(input)
const browser = await chromium.launch({ executablePath, headless: true })
try {
  const page = await browser.newPage()
  const requests = [], errors = []
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) requests.push(request.method()) })
  page.on('pageerror', error => errors.push(error.name))
  for (const suffix of [`#token=${encodeURIComponent(token)}`, `?token=${encodeURIComponent(token)}`]) {
    const response = await page.goto(`${origin}/activate${suffix}`)
    assert.equal(response.status(), 200)
    await page.getByText('YOUR INVITATION', { exact: true }).waitFor()
    await page.waitForLoadState('networkidle')
    assert.equal(page.url(), `${origin}/activate`)
    assert.equal(await page.locator('input[type="email"]').count(), 1)
    assert.equal((await page.context().cookies()).filter(cookie => cookie.name.includes('portal_session')).length, 0)
  }
  assert.deepEqual(requests, [])
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', apiInterceptions: 0, automaticApiRequests: 0, invitationUrlForms: 2 }))
} finally { await browser.close() }
