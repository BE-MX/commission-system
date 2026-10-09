import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
const page = await context.newPage()
const accessId = '11111111-1111-4111-8111-111111111111'
const productId = '22222222-2222-4222-8222-222222222222'
const ready = { canonical_customer_id: '9007199254740993', company_display_name: 'Synthetic New Buyer', customer_code: 'C-NEW', assignment_id: '17', sales_user_id: '5', sales_display_name: 'Synthetic Sales', okki_identity_id: '27', okki_company_id: 'OKKI-NEW', binding_fingerprint: 'a'.repeat(64), ready: true, blocked_reasons: [], existing_access: null }
const blocked = { ...ready, canonical_customer_id: '19', company_display_name: 'Missing Identity Buyer', ready: false, blocked_reasons: ['VERIFIED_IDENTITY_MISSING'], okki_identity_id: null }
const product = { id: productId, model_name: 'Standard Model', color_name: 'Natural Brown', length: '20', weight: '100', sale_unit: 'piece' }
let mode = 'success', exists = false, writes = [], permissions = ['portal_access:read', 'portal_access:admin']
const errors = []
page.on('pageerror', e => errors.push(e.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-test-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), url = new URL(req.url()), path = url.pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic Sales', roles: [], permissions } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-test-only' } })
  let data = {}
  const access = { id: accessId, company_display_name: ready.company_display_name, canonical_customer_id: ready.canonical_customer_id, sales_user_id: '5', row_version: 1, status: 'draft', capabilities: { can_view_price: true, can_order: true }, catalog_version: 1, mapping_version: 1, catalog_item_ids: [productId], accounts: { items: [], total: 0, page: 1, page_size: 20 } }
  if (path.startsWith('/api/portal/admin/v1/')) {
    if (req.method() !== 'GET') {
      writes.push({ path, body: req.postDataJSON() })
      assert.equal(path, '/api/portal/admin/v1/customers')
      assert.equal(req.method(), 'POST')
      if (mode === 'lost') return route.abort('failed')
      if (mode === 'stale') return route.fulfill({ status: 409, json: { code: 409, message: '客户归属或唯一外部身份已变化，请重新选择。', data: { error_code: 'IDENTITY_REVIEW_REQUIRED' } } })
      exists = true; data = access
    } else if (path.endsWith('/onboarding/customers')) data = { items: [ready, blocked], total: 2 }
    else if (path.includes('/onboarding/customers/')) data = { ...ready, existing_access: exists ? { id: accessId, status: 'draft' } : null }
    else if (path.endsWith('/onboarding/catalog')) data = { items: url.searchParams.get('keyword') ? [] : [product], total: url.searchParams.get('keyword') ? 0 : 1 }
    else if (path.endsWith(`/customers/${accessId}`)) data = access
    else if (path.endsWith('/customers')) data = { items: exists ? [access] : [], total: exists ? 1 : 0 }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const dialog = () => page.locator('.portal-onboarding-dialog:visible')
async function open() {
  await page.goto('http://127.0.0.1:3211/portal/customers')
  await page.getByRole('button', { name: '开通客户门户', exact: true }).click()
  await dialog().getByText('Missing Identity Buyer', { exact: true }).waitFor()
  const unavailable = dialog().getByRole('row').filter({ hasText: 'Missing Identity Buyer' })
  assert.equal(await unavailable.getByRole('button', { name: '选择此客户' }).isDisabled(), true)
  await dialog().getByRole('row').filter({ hasText: 'Synthetic New Buyer' }).getByRole('button', { name: '选择此客户' }).click()
  await dialog().getByText('Standard Model', { exact: true }).waitFor()
}
async function confirm() { await dialog().locator('.el-checkbox').filter({ hasText: '我已核对公司身份' }).click() }
try {
  await open()
  await dialog().locator('.catalog-picker .el-checkbox').click()
  await dialog().getByRole('textbox', { name: '搜索可授权商品' }).fill('no match')
  await dialog().getByRole('button', { name: '搜索商品', exact: true }).click()
  await dialog().getByText('初始商品授权 · 已选 1 项', { exact: true }).waitFor()
  await dialog().locator('.el-checkbox').filter({ hasText: '允许查看价格' }).click()
  assert.equal(await dialog().getByRole('checkbox', { name: '允许下单及确认交易条件' }).isChecked(), false)
  await confirm()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/onboarding-${width}.png`, fullPage: true })
  }
  await dialog().getByRole('button', { name: '创建授权草稿', exact: true }).click()
  await dialog().waitFor({ state: 'hidden' })
  assert.deepEqual(writes[0].body, { binding_fingerprint: ready.binding_fingerprint, canonical_customer_id: ready.canonical_customer_id, assignment_id: '17', okki_identity_id: '27', catalog_item_ids: [productId], capabilities: { can_view_price: false, can_order: false } })
  assert.equal(writes.length, 1)

  exists = false; mode = 'lost'
  await open(); await confirm()
  await dialog().getByRole('button', { name: '创建授权草稿', exact: true }).click()
  await dialog().getByRole('button', { name: '重试原内容', exact: true }).waitFor()
  assert.equal(await dialog().getByRole('button', { name: '关闭', exact: true }).isDisabled(), true)
  assert.equal(await dialog().getByRole('textbox', { name: '搜索可授权商品' }).isDisabled(), true)
  assert.equal(await dialog().getByRole('checkbox', { name: '允许下单及确认交易条件' }).isDisabled(), true)
  await dialog().getByRole('button', { name: '查询已有授权', exact: true }).click()
  await dialog().getByText('尚未查到已有授权，不能据此判断先前请求未执行。结果未知时请仅重试原内容。', { exact: true }).waitFor()
  mode = 'success'
  await dialog().getByRole('button', { name: '重试原内容', exact: true }).click()
  await dialog().waitFor({ state: 'hidden' })
  assert.deepEqual(writes[1], writes[2])

  mode = 'lost'; exists = false
  await open(); await confirm()
  await dialog().getByRole('button', { name: '创建授权草稿', exact: true }).click()
  await dialog().getByRole('button', { name: '重试原内容', exact: true }).waitFor()
  exists = true
  await dialog().getByRole('button', { name: '查询已有授权', exact: true }).click()
  await dialog().waitFor({ state: 'hidden' })
  assert.equal(writes.length, 4)
  await page.getByText('已找到现有客户授权，请核对当前设置；此查询不证明先前命令执行结果。', { exact: true }).waitFor()

  mode = 'stale'; exists = false
  await open(); await confirm()
  await dialog().getByRole('button', { name: '创建授权草稿', exact: true }).click()
  await dialog().getByText('客户归属或唯一外部身份已变化，请重新选择。', { exact: true }).waitFor()
  assert.equal(await dialog().getByRole('button', { name: '重试原内容', exact: true }).count(), 0)
  await dialog().getByRole('button', { name: '返回选择客户', exact: true }).click()
  await dialog().getByText('Missing Identity Buyer', { exact: true }).waitFor()
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  permissions = ['portal_access:read']
  await page.reload()
  await page.getByRole('button', { name: '刷新', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '开通客户门户', exact: true }).isVisible(), false)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', simulatedWrites: writes.length, scenarios: ['blocked identity', 'selected catalog survives search', 'price/order capability dependency', 'draft only and exact fingerprint', '1440/390/320 layout', 'unknown freezes selection', 'absence is not failure evidence', 'exact original retry', 'existing access recovery without success claim', 'stale identity rejected', 'read-only entry hidden'] }))
} finally { await browser.close() }
