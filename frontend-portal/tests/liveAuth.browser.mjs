import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { setTimeout as delay } from 'node:timers/promises'
const [origin, backend, modulePath, executablePath] = process.argv.slice(2)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ ignoreHTTPSErrors: true })
const page = await context.newPage(), errors = []
page.on('pageerror', error => errors.push(error.message))
const api = origin + '/api/portal/v1'
let lastChallengeAt = 0
async function login() {
  // Preserve the real 60-second resend limit across independent preauth sessions.
  await delay(Math.max(0, lastChallengeAt + 61000 - Date.now()))
  await page.getByLabel('Email address').fill('buyer@example.com')
  const sent = page.waitForResponse(response => response.url() === api + '/auth/challenges' && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Continue with email' }).click()
  const challenge = await sent
  assert.equal(challenge.status(), 202, 'Real challenge endpoint must accept the login request')
  lastChallengeAt = Date.now()
  await page.getByLabel('Verification code').waitFor()
  const preauth = (await context.cookies()).find(c => c.name === '__Host-portal_preauth')
  assert.ok(preauth?.secure && preauth.httpOnly && preauth.path === '/' && preauth.sameSite === 'Lax')
  assert.ok(!(await page.evaluate(() => document.cookie)).includes('portal_preauth'))
  const mailbox = await (await context.request.get(backend + '/__qa/mailbox')).json()
  await page.getByLabel('Verification code').fill(mailbox.code)
  await page.getByRole('button', { name: 'Enter your collection' }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
}
try {
  // No route interception: all customer requests reach the live Python router.
  await page.goto(origin + '/login')
  await page.getByLabel('Email address').waitFor()
  assert.equal((await context.request.get(api + '/session')).status(), 401)
  assert.equal((await context.request.get(backend + '/api/portal/v1/auth/bootstrap', { headers: { 'X-Real-IP': '127.0.0.2', 'X-Forwarded-For': '127.0.0.2' } })).status(), 403)
  assert.equal((await context.request.post(api + '/auth/challenges', { headers: { Origin: 'https://untrusted.invalid' }, data: { email: 'buyer@example.com', purpose: 'login' } })).status(), 403)
  await login()
  const cookies = await context.cookies(), session = cookies.find(c => c.name === '__Host-portal_session')
  assert.ok(session?.secure && session.httpOnly && session.path === '/' && session.sameSite === 'Lax')
  assert.ok(!cookies.some(c => c.name === '__Host-portal_preauth'))
  assert.ok(!(await page.evaluate(() => document.cookie)).includes('portal_session'))
  assert.ok(!(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).includes(session.value))
  const response = await context.request.get(api + '/session'), current = (await response.json()).data
  assert.equal(response.status(), 200); assert.equal(response.headers()['cache-control'], 'no-store')
  assert.equal((await context.request.post(api + '/auth/logout', { headers: { Origin: origin }, data: {} })).status(), 403)
  assert.equal((await context.request.post(api + '/auth/logout', { headers: { Origin: 'https://untrusted.invalid', 'X-Portal-CSRF': current.csrf_token }, data: {} })).status(), 403)
  assert.equal((await context.request.get(api + '/session')).status(), 200)
  const other = await context.newPage(); await other.goto(origin + '/collection')
  await other.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.getByLabel('Email address').waitFor(); await other.getByLabel('Email address').waitFor()
  assert.ok(!(await context.cookies()).some(c => c.name === '__Host-portal_session'))
  await context.addCookies([session])
  assert.equal((await context.request.get(api + '/session')).status(), 401)
  await other.close()
  await login()
  assert.equal((await context.request.post(backend + '/__qa/disable')).status(), 200)
  assert.equal((await context.request.get(api + '/session')).status(), 401)
  await page.reload(); await page.getByLabel('Email address').waitFor()
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', network: 'real-local-https', scenarios: 10, apiInterceptions: 0 }))
} finally { await browser.close() }
