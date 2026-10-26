import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_ADMIN_ORIGIN || 'http://127.0.0.1:3026'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || '../tmp/portal-customer-experience/admin'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = [], writes = []
const sourceId = '11111111-1111-4111-8111-111111111111', targetId = '22222222-2222-4222-8222-222222222222'
const source = { id: sourceId, company_display_name: 'Synthetic Source', canonical_customer_id: '1', sales_user_id: '5', row_version: 3, status: 'enabled', capabilities: { can_view_price: true, can_order: true }, catalog_version: 7, mapping_version: 1, catalog_item_ids: ['33333333-3333-4333-8333-333333333333'], accounts: { items: [], total: 0 } }
const target = { ...source, id: targetId, company_display_name: 'Synthetic Target', canonical_customer_id: '2' }
const ready = { canonical_customer_id: '2', company_display_name: 'Synthetic Target', customer_code: 'TEST-2', assignment_id: '17', sales_user_id: '5', sales_display_name: 'Synthetic Sales', okki_identity_id: '27', okki_company_id: 'OKKI-2', binding_fingerprint: 'a'.repeat(64), ready: true, blocked_reasons: [], existing_access: null }
let lose = false, created = false
page.on('pageerror', e => errors.push(e.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-test-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname
  const send = (data, status = 200) => route.fulfill({ status, json: { code: status, message: 'ok', data } })
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic Sales', roles: [], permissions: ['portal_access:read', 'portal_access:admin'] } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-test-only' } })
  if (path.startsWith('/api/portal/admin/v1/')) {
    if (request.method() === 'POST') {
      assert.equal(path, `/api/portal/admin/v1/customers/${sourceId}/copy`)
      writes.push({ path, key: request.headers()['idempotency-key'], body: request.postDataJSON() })
      if (lose) { lose = false; return route.abort('failed') }
      created = true
      return send({ ...target, account_id: '44444444-4444-4444-8444-444444444444', replayed: false }, 201)
    }
    if (path.endsWith('/onboarding/customers')) return send({ items: [ready], total: 1 })
    if (path.includes('/onboarding/customers/')) return send({ ...ready, existing_access: created ? { id: targetId, status: 'enabled' } : null })
    if (path.endsWith(`/customers/${sourceId}`)) return send(source)
    if (path.endsWith(`/customers/${targetId}`)) return send(target)
    if (path.endsWith('/customers')) return send({ items: [source], total: 1 })
  }
  return send({})
})
const dialog = () => page.locator('.portal-onboarding-dialog:visible')
async function open() {
  await page.goto(origin + '/portal/customers')
  await page.getByRole('button', { name: '复制', exact: true }).click()
  await dialog().getByRole('button', { name: '选择此客户', exact: true }).click()
  assert.equal(await dialog().locator('.catalog-picker').count(), 0)
  await dialog().getByLabel('访问邮箱', { exact: true }).fill('new@example.com')
  await dialog().getByLabel('登录密码', { exact: true }).fill('Synthetic-pass-2026')
  await dialog().locator('.el-checkbox').filter({ hasText: '我已核对新客户身份' }).click()
}
try {
  await open()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    assert.ok(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await page.screenshot({ path: `${output}/access-copy-${width}.png`, fullPage: true })
  }
  await dialog().getByRole('button', { name: '复制并创建账号', exact: true }).click()
  await dialog().waitFor({ state: 'hidden' })
  await page.getByText('客户访问已复制，新采购账号可使用邮箱和密码登录。', { exact: true }).waitFor()
  assert.deepEqual(writes[0].body, { binding_fingerprint: ready.binding_fingerprint, canonical_customer_id: '2', assignment_id: '17', okki_identity_id: '27', email: 'new@example.com', password: 'Synthetic-pass-2026', source_version: 3, source_catalog_version: 7 })
  created = false; lose = true
  await open()
  await dialog().getByRole('button', { name: '复制并创建账号', exact: true }).click()
  await dialog().getByRole('button', { name: '重试原内容', exact: true }).waitFor()
  assert.equal(await dialog().getByLabel('访问邮箱', { exact: true }).isDisabled(), true)
  await dialog().getByRole('button', { name: '查询已有授权', exact: true }).click()
  await dialog().getByText(/尚未查到已有授权/).waitFor()
  await dialog().getByRole('button', { name: '重试原内容', exact: true }).click()
  await dialog().waitFor({ state: 'hidden' })
  assert.deepEqual(writes[1], writes[2])
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', simulatedWrites: writes.length, checks: ['independent target identity', 'template versions', 'email/password only after customer selection', '320/390/1440 dialog', 'unknown locks form', 'read before exact retry'] }))
} catch (problem) { console.log(JSON.stringify({ url: page.url(), errors, text: (await page.locator('body').innerText()).slice(0,2500) })); await page.screenshot({ path: `${output}/copy-failure.png` }); throw problem } finally { await browser.close() }
