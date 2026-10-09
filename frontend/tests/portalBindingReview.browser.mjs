import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url), { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } }), page = await context.newPage()
const id = '11111111-1111-4111-8111-111111111111', fingerprint = 'a'.repeat(64)
let access = { id, company_display_name: 'Synthetic Binding Buyer', row_version: 1, status: 'review_required', canonical_customer_id: '101', sales_user_id: '1', capabilities: { can_view_price: true, can_order: true }, catalog_item_ids: [] }
let permissions = ['portal_access:read', 'portal_access:admin'], mode = 'success', denied = false
const calls = [], errors = []
page.on('pageerror', error => errors.push(error.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-test-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), path = new URL(req.url()).pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic reviewer', roles: [], permissions } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-test-only' } })
  let data = {}
  if (path.endsWith('/customers')) data = { items: [access], total: 1 }
  else if (path.endsWith(`/customers/${id}`)) data = { ...access, accounts: { items: [], total: 0 } }
  else if (path.endsWith('/binding-review')) {
    if (denied) return route.fulfill({ status: 403, json: { code: 403, message: '当前权限已撤销', data: {} } })
    data = { access_id: id, row_version: access.row_version, current_sales_user_id: access.sales_user_id, current_company_id: '501', assignments: [{ id: '22', sales_user_id: '2', sales_name: 'New Sales' }], identities: [{ id: '91', company_id: '502', namespace: 'okki:test' }], review_fingerprint: fingerprint, requires_assignment_review: access.status === 'review_required', customer_requires_review: false, pending_requests: [{ id: 'order-1', public_no: 'REQ-001', status: 'submitted', servicing_user_id: '1' }, { id: 'order-2', public_no: 'REQ-002', status: 'ready_for_review', servicing_user_id: '1' }], pending_total: 1002, pending_truncated: true, order_total: 1003, invoice_order_total: 1 }
  } else if (path.endsWith('/transfer') || path.endsWith('/rebind')) {
    calls.push({ path, body: req.postDataJSON(), version: req.headers()['if-match'] })
    if (mode === 'stale') return route.fulfill({ status: 409, json: { code: 409, message: '复核范围已变化，请重新读取。', data: {} } })
    access = { ...access, row_version: access.row_version + 1, sales_user_id: '2', status: 'suspended' }
    if (mode === 'lost') return route.abort('failed')
    data = { ...access, requires_enable: true, reassigned_request_ids: ['order-1'], unassigned_pending_request_ids: ['order-2'], history_grants: 1002, expired_quotes: 2 }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const dialog = () => page.locator('.portal-binding-review:visible')
async function open() {
  await page.goto('http://127.0.0.1:3211/portal/customers')
  await page.getByRole('button', { name: '管理', exact: true }).click()
  await page.getByRole('button', { name: '归属与身份复核', exact: true }).click()
  await dialog().getByText('选择交接的未建票请求', { exact: true }).waitFor()
}
async function select(label, option) {
  await dialog().locator('.el-select').filter({ has: page.getByRole('combobox', { name: label, exact: true }) }).click()
  await page.getByRole('option', { name: option, exact: true }).click()
}
async function confirm() { await dialog().locator('.el-checkbox').filter({ hasText: '我已核对旧绑定' }).click() }
async function reason() { await dialog().getByRole('textbox', { name: '复核原因', exact: true }).fill('Verified customer handoff') }
try {
  await open()
  await dialog().getByText('共有 1002 个待处理请求，此处仅列前 1000 个。未列出及未勾选请求均不会交接。', { exact: true }).waitFor()
  await select('新主负责人', 'New Sales · 归属 22')
  await dialog().locator('.el-checkbox').filter({ has: page.getByRole('checkbox', { name: '交接 REQ-001', exact: true }) }).click()
  await dialog().locator('.el-radio-button').filter({ hasText: '向新负责人限时授权' }).click()
  await dialog().getByRole('spinbutton', { name: '历史读取有效天数', exact: true }).fill('30')
  await reason(); await confirm()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth + 1), `dialog overflow at ${width}`)
    await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/binding-review-${width}.png`, fullPage: true })
  }
  await dialog().getByRole('button', { name: '确认本次复核', exact: true }).click(); await dialog().waitFor({ state: 'hidden' })
  assert.deepEqual(calls[0].body, { review_fingerprint: fingerprint, reason: 'Verified customer handoff', assignment_id: '22', pending_request_ids: ['order-1'], history_policy: 'explicit_grant', history_days: 30 })
  assert.equal(calls[0].version, '"1"')
  await open(); await dialog().locator('.el-radio-button').filter({ hasText: '重绑外部公司身份' }).click()
  await select('已验证外部公司身份', '502 · okki:test'); await reason(); await confirm()
  mode = 'lost'; await dialog().getByRole('button', { name: '确认本次复核', exact: true }).click()
  await dialog().getByText('操作结果未知，当前复核已冻结。仅重新读取当前状态核对，不重发转交或重绑。', { exact: true }).waitFor()
  assert.equal(await dialog().getByRole('textbox', { name: '复核原因', exact: true }).isDisabled(), true)
  assert.equal(await dialog().getByRole('radio', { name: '复核负责人转交', exact: true }).isDisabled(), true)
  assert.equal(await dialog().getByRole('button', { name: '关闭', exact: true }).isDisabled(), true)
  await dialog().getByRole('button', { name: '读取当前复核并放弃草稿', exact: true }).click()
  await dialog().getByText('已读取当前绑定与影响范围并放弃草稿，不能据此确认原操作成功；本次未重发写入。', { exact: true }).waitFor()
  assert.equal(calls.length, 2); assert.equal(await dialog().getByRole('button', { name: '确认本次复核', exact: true }).isDisabled(), true)
  assert.equal(calls[1].version, '"2"'); assert.equal(calls[1].body.identity_id, '91'); assert.equal('assignment_id' in calls[1].body, false)
  await select('已验证外部公司身份', '502 · okki:test'); await reason(); await confirm()
  mode = 'stale'; await dialog().getByRole('button', { name: '确认本次复核', exact: true }).click()
  await dialog().getByText('复核范围已变化，请重新读取。', { exact: true }).waitFor()
  denied = true; await dialog().getByRole('button', { name: '读取当前复核并放弃草稿', exact: true }).click()
  await dialog().getByText('当前权限已撤销', { exact: true }).waitFor()
  assert.equal(await dialog().getByRole('textbox', { name: '复核原因' }).count(), 0)
  assert.equal(await page.getByText('Synthetic Binding Buyer', { exact: true }).count(), 0)
  denied = false; await dialog().getByRole('button', { name: '读取当前复核并放弃草稿', exact: true }).click()
  await dialog().getByText('已读取当前绑定与影响范围并放弃草稿，不能据此确认原操作成功；本次未重发写入。', { exact: true }).waitFor()
  await dialog().getByRole('button', { name: '关闭', exact: true }).click(); await dialog().waitFor({ state: 'hidden' })
  assert.equal(calls.length, 3)
  permissions = ['portal_access:read']; await page.reload(); await page.getByRole('button', { name: '管理', exact: true }).click()
  assert.equal(await page.getByRole('button', { name: '归属与身份复核', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', simulatedWrites: calls.length, scenarios: ['review_required entry', 'truncated scope disclosed', 'explicit selected transfer only', 'version and fingerprint', 'new owner historical duration', 'rebind payload isolation', 'unknown fields frozen', 'readback not receipt or resend', 'stale review rejection', 'permission loss clears draft', 'read-only entry hidden', '1440/390/320 layout'] }))
} finally { await browser.close() }
