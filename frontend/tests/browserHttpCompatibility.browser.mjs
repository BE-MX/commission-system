import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), { chromium } = require(process.argv[2])
const base = process.argv[3], output = process.argv[4], production = process.argv[5] === '--production'
const browser = await chromium.launch({ headless: true }), results = []
await mkdir(output, { recursive: true })
try {
  if (!production) {
    const page = await browser.newPage(), errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(base + '/tests/browserHttpHarness.html')
    await page.waitForFunction(() => typeof window.newRequestKey === 'function')
    const environment = await page.evaluate(() => ({ secure: isSecureContext,
      randomUUID: typeof crypto.randomUUID, clipboard: typeof navigator.clipboard }))
    assert.deepEqual(environment, { secure: false, randomUUID: 'undefined', clipboard: 'undefined' })
    const keys = await page.evaluate(() => Array.from({ length: 1000 }, () => window.newRequestKey()))
    assert.equal(new Set(keys).size, 1000)
    for (const key of keys) assert.match(key, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    await page.locator('#original').focus()
    await page.locator('#original').evaluate(el => el.setSelectionRange(2, 6))
    await page.getByRole('button', { name: '复制', exact: true }).click()
    await page.locator('#result').filter({ hasText: 'true' }).waitFor()
    assert.deepEqual(await page.evaluate(() => [document.activeElement.id,
      document.activeElement.selectionStart, document.activeElement.selectionEnd]), ['original', 2, 6])
    await page.locator('#paste').click()
    await page.keyboard.press('Control+V')
    assert.equal(await page.locator('#paste').inputValue(), '内网复制验证 · HTTP')
    await page.evaluate(() => { document.execCommand = () => false; document.querySelector('#result').textContent = '' })
    await page.getByRole('button', { name: '复制', exact: true }).click()
    await page.locator('#result').filter({ hasText: 'false' }).waitFor()
    assert.equal(await page.locator('textarea').count(), 2)
    assert.deepEqual(errors, [])
    results.push({ scenario: 'HTTP shared UUID and actual copy/paste, denial, focus and selection', environment, errors })
    await page.close()

  }
  // API responses are synthetic and off-origin requests are blocked in every routing scenario.
  const origin = new URL(base).origin
  const syntheticUser = { id: 1, username: 'synthetic', real_name: 'Synthetic', roles: ['super_admin'], permissions: [] }
  async function routingScenario({ name, mobile, initial, authenticated = true, login = false, expected, selector }) {
    const context = await browser.newContext({
      viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 },
      ...(mobile ? { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1' } : {}),
    })
    const page = await context.newPage(), errors = [], api = [], external = []
    page.on('pageerror', error => errors.push(error.message))
    if (authenticated) await context.addInitScript(() => localStorage.setItem('ark_access_token', 'synthetic-local-test'))
    await context.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin !== origin) { external.push(url.origin); return route.abort() }
      if (!url.pathname.startsWith('/api/')) return route.continue()
      api.push(url.pathname)
      if (url.pathname === '/api/auth/refresh') return route.fulfill({ status: 401, json: { detail: 'No synthetic session' } })
      if (url.pathname === '/api/auth/login') return route.fulfill({ json: { access_token: 'synthetic-local-test', user: syntheticUser } })
      if (url.pathname === '/api/auth/me') return route.fulfill({ json: syntheticUser })
      return route.fulfill({ json: { code: 200, data: [] } })
    })
    try {
      await page.goto(base + initial)
      if (login) {
        await page.getByLabel('用户名').fill('synthetic')
        await page.getByLabel('密码', { exact: true }).fill('synthetic')
        await page.getByRole('button', { name: '登 录', exact: true }).click()
      }
      await page.waitForURL(url => url.pathname + url.search + url.hash === expected)
      await page.locator(selector).waitFor()
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).search + new URL(page.url()).hash, expected)
      assert.deepEqual(errors, [])
      results.push({ scenario: name, mode: production ? 'production bundle' : 'development', expected, api, blockedExternalOrigins: [...new Set(external)], errors })
    } finally { await context.close() }
  }
  await routingScenario({ name: 'mobile default login', mobile: true, initial: '/login', authenticated: false, login: true, expected: '/dashboard', selector: '.dashboard-page' })
  for (const initial of ['/m', '/m/', '/m/login.html', '/m/?old=1#/assets/1']) {
    await routingScenario({ name: `retired bookmark ${initial}`, mobile: true, initial, expected: '/dashboard', selector: '.dashboard-page' })
  }
  await routingScenario({ name: 'unauthenticated retired bookmark', mobile: true, initial: '/m/login.html?old=1#/assets/1', authenticated: false, login: true, expected: '/dashboard', selector: '.dashboard-page' })
  await routingScenario({ name: 'desktop retired bookmark', mobile: false, initial: '/m/assets/1?old=1#detail', expected: '/dashboard', selector: '.dashboard-page' })
  for (const mobile of [true, false]) {
    await routingScenario({ name: `${mobile ? 'mobile' : 'desktop'} asset library`, mobile, initial: '/asset/library', expected: '/asset/library', selector: '.asset-library-page' })
    await routingScenario({ name: `${mobile ? 'mobile' : 'desktop'} login restores asset deep link`, mobile, initial: '/asset/library?source=bookmark#test', authenticated: false, login: true, expected: '/asset/library?source=bookmark#test', selector: '.asset-library-page' })
  }
  await routingScenario({ name: 'mobile login restores FX deep link', mobile: true, initial: '/fx-settlement?source=bookmark', authenticated: false, login: true, expected: '/fx-settlement?source=bookmark', selector: '.fx-page' })
  await writeFile(output + '/results.json', JSON.stringify(results, null, 2))
  process.stdout.write(JSON.stringify(results, null, 2) + '\n')
} finally { await browser.close() }
