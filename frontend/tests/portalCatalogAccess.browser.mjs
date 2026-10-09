import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
const page = await context.newPage()
const id = '11111111-1111-4111-8111-111111111111'
const old = { id: '22222222-2222-4222-8222-222222222222', model_name: 'Withdrawn Model', color_name: 'Black', length: '20', weight: '100', sale_unit: 'pack', status: 'disabled' }
const fresh = { ...old, id: '33333333-3333-4333-8333-333333333333', model_name: 'Published Model', status: 'published' }
let items = [old], version = 1, mode = 'success', permissions = ['portal_access:read', 'portal_access:admin']
const calls = [], errors = []
const access = () => ({ id, company_display_name: 'Synthetic Catalog Buyer', canonical_customer_id: '12', sales_user_id: '5', status: 'draft', row_version: version, capabilities: { can_view_price: false, can_order: false }, catalog_version: version, mapping_version: 0, catalog_item_ids: items.map(x => x.id), accounts: { items: [], total: 0 } })
page.on('pageerror', e => errors.push(e.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-test-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), path = new URL(req.url()).pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic Sales', roles: [], permissions } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-test-only' } })
  let data = {}
  if (path.startsWith('/api/portal/admin/v1/')) {
    if (req.method() !== 'GET') {
      assert.equal(req.method(), 'PATCH'); assert.ok(path.endsWith(`/customers/${id}/catalog`))
      const body = req.postDataJSON(); calls.push({ body, version: req.headers()['if-match'] })
      if (mode === 'stale') return route.fulfill({ status: 409, json: { code: 409, message: '记录已变化，请刷新确认。', data: { error_code: 'VERSION_CONFLICT' } } })
      items = [old, fresh].filter(x => body.catalog_item_ids.includes(x.id)); version++
      if (mode === 'lost') return route.abort('failed')
      data = { ...access(), items }
    } else if (path.endsWith('/onboarding/catalog')) data = { items: [fresh], total: 1 }
    else if (path.endsWith(`/customers/${id}/catalog`)) {
      if (mode === 'scope') return route.fulfill({ status: 404, json: { code: 404, message: '记录不存在或不在当前授权范围内。', data: { error_code: 'RESOURCE_NOT_FOUND' } } })
      data = { ...access(), items }
    }
    else if (path.endsWith(`/customers/${id}`)) data = access()
    else if (path.endsWith('/customers')) data = { items: [access()], total: 1 }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const dialog = () => page.locator('.portal-catalog-access:visible')
async function open() {
  await page.goto('http://127.0.0.1:3211/portal/customers')
  await page.getByRole('button', { name: '管理', exact: true }).click()
  await page.getByRole('button', { name: '管理商品授权', exact: true }).click()
  await dialog().getByText('Published Model', { exact: true }).waitFor()
}
async function confirm() {
  await dialog().getByRole('textbox', { name: '商品授权操作原因' }).fill('Reviewed customer range')
  await dialog().locator('.el-checkbox').filter({ hasText: '我已核对新增' }).click()
}
try {
  await open()
  await dialog().getByText('查看已选规格（1）', { exact: true }).click()
  await dialog().getByText(/Withdrawn Model.*已下架/).waitFor()
  await dialog().locator('.catalog-picker .el-checkbox').click()
  await confirm()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/catalog-access-${width}.png`, fullPage: true })
  }
  await dialog().getByRole('button', { name: '保存商品授权', exact: true }).click()
  await dialog().waitFor({ state: 'hidden' })
  assert.deepEqual(calls[0], { body: { catalog_item_ids: [old.id, fresh.id], reason: 'Reviewed customer range' }, version: '"1"' })
  assert.equal(access().status, 'draft')

  mode = 'lost'; await open()
  await dialog().locator('.catalog-picker .el-checkbox').click()
  await confirm(); await dialog().getByRole('button', { name: '保存商品授权', exact: true }).click()
  await dialog().getByText('保存结果未知，当前选择已冻结。请读取当前授权核对，不会自动重发写入。', { exact: true }).waitFor()
  assert.equal(await dialog().getByRole('button', { name: '关闭', exact: true }).isDisabled(), true)
  assert.equal(await dialog().getByRole('button', { name: '保存商品授权', exact: true }).isDisabled(), true)
  await dialog().getByRole('button', { name: '读取当前授权并放弃草稿', exact: true }).click()
  await dialog().getByText('已读取当前授权并放弃本地草稿，不能据此确认刚才保存成功。请核对后重新编辑；本次没有重发写入。', { exact: true }).waitFor()
  assert.equal(calls.length, 2)
  assert.equal(await dialog().getByRole('checkbox', { name: '我已核对新增、移除和保留商品，以及重新登录和报价失效的影响' }).isChecked(), false)
  await dialog().getByText('查看已选规格（1）', { exact: true }).click()
  await dialog().getByRole('button', { name: '移除授权规格 Withdrawn Model Black ' + old.id, exact: true }).click()
  await dialog().getByText('当前选择为空，保存将撤销该客户全部商品授权。', { exact: true }).waitFor()
  mode = 'stale'; await confirm()
  await dialog().getByRole('button', { name: '保存商品授权', exact: true }).click()
  await dialog().getByText('记录已变化，请刷新确认。', { exact: true }).waitFor()
  assert.deepEqual(calls[2], { body: { catalog_item_ids: [], reason: 'Reviewed customer range' }, version: '"3"' })
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  mode = 'lost'; await open(); await confirm()
  await dialog().getByRole('button', { name: '保存商品授权', exact: true }).click()
  await dialog().getByText('保存结果未知，当前选择已冻结。请读取当前授权核对，不会自动重发写入。', { exact: true }).waitFor()
  mode = 'scope'
  await dialog().getByRole('button', { name: '读取当前授权并放弃草稿', exact: true }).click()
  await dialog().getByText('记录不存在或不在当前授权范围内。', { exact: true }).waitFor()
  assert.equal(await dialog().getByRole('textbox', { name: '商品授权操作原因' }).count(), 0)
  assert.equal(await dialog().getByRole('button', { name: '关闭', exact: true }).isDisabled(), true)
  assert.equal(await page.getByText('Synthetic Catalog Buyer', { exact: true }).count(), 0)
  assert.equal(calls.length, 4)
  mode = 'success'
  await dialog().getByRole('button', { name: '读取当前授权并放弃草稿', exact: true }).click()
  await dialog().getByText('已读取当前授权并放弃本地草稿，不能据此确认刚才保存成功。请核对后重新编辑；本次没有重发写入。', { exact: true }).waitFor()
  assert.equal(calls.length, 4)
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  await dialog().waitFor({ state: 'hidden' })
  permissions = ['portal_access:read']; await page.reload()
  await page.getByRole('button', { name: '管理', exact: true }).click()
  await page.getByText('Synthetic Catalog Buyer', { exact: true }).last().waitFor()
  assert.equal(await page.getByRole('button', { name: '管理商品授权', exact: true }).isVisible(), false)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', simulatedWrites: calls.length, scenarios: ['withdrawn selection labelled', 'add published preserves previous grant', 'draft unchanged', '1440/390/320 layout', 'unknown freezes writes', 'readback resets draft without success claim', 'empty selection explicit warning', 'stale version rejected', 'scope loss clears unknown draft', 'read-only hides action'] }))
} finally { await browser.close() }
