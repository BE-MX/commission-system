import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const accessId = '11111111-1111-4111-8111-111111111111', first = '22222222-2222-4222-8222-222222222222', second = '33333333-3333-4333-8333-333333333333'
let permissions = ['portal_access:read', 'portal_mapping:read', 'portal_mapping:write'], conflicts = true, versionConflict = false, losePublish = false, denied = false, denyPreview = false, denyPublish = false
let mappingVersion = 1, rowVersion = 3, entries = [{ kind: 'model', source_key: 'MODEL', display_value: 'Old Collection' }, { kind: 'sku', source_key: '44444444-4444-4444-8444-444444444444', item_id: '44444444-4444-4444-8444-444444444444', display_value: 'Withdrawn product' }]
const sources = [{ item_id: first, model_key: 'MODEL', color_key: 'BLACK', model_name: 'Standard Weft', color_name: 'Black', length: '20in', weight: '20g', unit: 'pack', product_kind: 'hair' }, { item_id: second, model_key: 'MODEL', color_key: 'BROWN', model_name: 'Standard Weft', color_name: 'Brown', length: '22in', weight: '25g', unit: 'pack', product_kind: 'hair' }]
const calls = [], errors = []
page.on('pageerror', error => errors.push(error.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-mapping-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), path = new URL(req.url()).pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic mapping reviewer', roles: [], permissions } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-mapping-only' } })
  let data = {}
  const access = { id: accessId, company_display_name: 'Mapping QA Company', status: 'enabled', row_version: rowVersion, canonical_customer_id: '55', sales_user_id: '5', capabilities: { can_view_price: true, can_order: true }, catalog_item_ids: [first, second], accounts: { items: [], total: 0 } }
  if (path.endsWith('/customers')) data = { items: [access], total: 1 }
  else if (path.endsWith(`/customers/${accessId}`)) data = access
  else if (path.endsWith('/mapping')) {
    if (denied) return route.fulfill({ status: 404, json: { code: 404, message: '映射不在当前授权范围。', data: { error_code: 'RESOURCE_NOT_FOUND' } } })
    data = { access_id: accessId, row_version: rowVersion, mapping_version: mappingVersion, sources, entries, draft: null }
  } else if (path.endsWith('/mapping/preview')) {
    if (denyPreview) return route.fulfill({ status: 404, json: { code: 404, message: '预览范围已撤销', data: { error_code: 'RESOURCE_NOT_FOUND' } } })
    const body = req.postDataJSON(); calls.push({ path, body })
    assert.equal(body.base_version, mappingVersion)
    const changes = []
    const old = new Map(entries.map(e => [e.kind + ':' + e.source_key, e]))
    const next = new Map(body.entries.map(e => [e.kind + ':' + e.source_key, e]))
    for (const key of new Set([...old.keys(), ...next.keys()])) {
      const before = old.get(key), after = next.get(key)
      if (before?.display_value !== after?.display_value || before?.customer_sku !== after?.customer_sku) {
        const entry = after || before
        changes.push({ kind: entry.kind, source_key: entry.source_key, before: before || null, after: after || null, change: !before ? 'added' : !after ? 'removed' : 'modified' })
      }
    }
    data = { access_id: accessId, base_version: mappingVersion, row_version: rowVersion, affected_sku_count: 2, valid: !conflicts, changes, change_counts: Object.fromEntries(['added', 'modified', 'removed'].map(kind => [kind, changes.filter(c => c.change === kind).length])),
      conflicts: conflicts ? ['COLOR_AMBIGUOUS', 'CUSTOMER_SKU_DUPLICATE'].map(code => ({ code, item_ids: [first, second] })) : [],
      items: sources.map(s => ({ item_id: s.item_id, model_name: body.entries.find(e => e.kind === 'sku' && e.source_key === s.item_id)?.display_value || body.entries.find(e => e.kind === 'model')?.display_value || s.model_name,
        color_name: body.entries.find(e => e.kind === 'color' && e.source_key === s.color_key)?.display_value || s.color_name, customer_sku: body.entries.find(e => e.kind === 'sku' && e.source_key === s.item_id)?.customer_sku || null, length: s.length, weight: s.weight, unit: s.unit })) }
  } else if (path.endsWith('/mapping/publish')) {
    if (denyPublish) return route.fulfill({ status: 403, json: { code: 403, message: '发布权限已撤销', data: { error_code: 'ACTION_FORBIDDEN' } } })
    const body = req.postDataJSON(); calls.push({ path, body, version: req.headers()['if-match'] })
    if (versionConflict) { versionConflict = false; rowVersion++; mappingVersion++; entries = [{ kind: 'model', source_key: 'MODEL', display_value: 'Changed by colleague' }]; return route.fulfill({ status: 409, json: { code: 409, message: '记录已变化，请刷新确认。', data: { error_code: 'VERSION_CONFLICT' } } }) }
    assert.equal(req.headers()['if-match'], `"${rowVersion}"`); assert.equal(body.base_version, mappingVersion)
    entries = body.entries; rowVersion++; mappingVersion++
    if (losePublish) { losePublish = false; return route.abort('failed') }
    data = { id: '55555555-5555-4555-8555-555555555555', row_version: rowVersion, mapping_version: mappingVersion, affected_sku_count: 2, expired_quotes: 1 }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const modal = () => page.locator('.portal-mapping-dialog:visible')
const previewButton = () => modal().getByRole('button', { name: '校验并预览', exact: true })
const publishButton = () => modal().getByRole('button', { name: '发布映射', exact: true })
async function open() {
  await page.goto('http://127.0.0.1:3211/portal/customers')
  await page.getByRole('cell', { name: 'Mapping QA Company', exact: true }).waitFor()
  await page.getByRole('button', { name: '管理', exact: true }).click()
  await page.getByRole('button', { name: '型号颜色映射', exact: true }).click()
  await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).waitFor()
}
async function confirm() { await modal().locator('.el-checkbox').filter({ hasText: '我已核对完整展示效果' }).click() }
try {
  await open()
  assert.equal(await previewButton().isDisabled(), true)
  await modal().getByRole('button', { name: '从草稿移除失效项', exact: true }).click()
  assert.equal(await modal().getByText('来源已失效', { exact: true }).count(), 0)
  await previewButton().click()
  await modal().getByText('不同标准颜色映射为同一颜色名', { exact: true }).waitFor()
  await modal().getByText('客户货号重复', { exact: true }).waitFor()
  assert.equal(await publishButton().isDisabled(), true)
  conflicts = false
  await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).fill('Silk Collection')
  assert.equal(await modal().getByText('客户展示预览', { exact: false }).count(), 0)
  await previewButton().click(); await confirm()
  await modal().getByRole('heading', { name: '版本差异 · 已发布 v1 → 待发布 v2', exact: true }).waitFor()
  await modal().getByRole('cell', { name: 'Old Collection', exact: true }).waitFor()
  await modal().getByRole('cell', { name: 'Withdrawn product', exact: true }).waitFor()
  assert.match(await modal().innerText(), /新增 0 · 修改 1 · 删除 1/)
  assert.equal(await publishButton().isEnabled(), true)
  await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).fill('Silk Collection Updated')
  assert.equal(await publishButton().isDisabled(), true)
  await previewButton().click(); await confirm()
  versionConflict = true; await publishButton().click()
  await modal().getByText('记录已变化，请刷新确认。', { exact: true }).waitFor()
  assert.equal(await publishButton().isDisabled(), true)
  await modal().getByRole('button', { name: '重新读取当前版本（舍弃草稿）', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('input[aria-label="客户展示名 1"]')?.value === 'Changed by colleague')
  await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).fill('My Revised Collection')
  await previewButton().click(); await confirm()
  losePublish = true; await publishButton().click()
  await modal().getByText('发布结果未知。不会自动重发；请读取当前已发布版本并核对，再决定后续修改。', { exact: true }).waitFor()
  assert.equal(await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).isDisabled(), true)
  const writes = calls.filter(c => c.path.endsWith('/publish')).length
  await modal().getByRole('button', { name: '重新读取当前版本（舍弃草稿）', exact: true }).click()
  await modal().getByText('已读取当前已发布版本并替换草稿；这不能证明上次发布命令成功。请核对当前内容，后续修改必须重新预览。', { exact: true }).waitFor()
  assert.equal(calls.filter(c => c.path.endsWith('/publish')).length, writes)
  assert.equal(await publishButton().isDisabled(), true)

  await modal().locator('.mapping-add .el-form-item').filter({ hasText: '映射类型' }).locator('.el-select').click()
  await page.getByRole('option', { name: '单规格型号名 / 客户货号', exact: true }).click()
  await modal().locator('.mapping-add .el-form-item').filter({ hasText: '标准来源' }).locator('.el-select').click()
  await page.getByRole('option').filter({ hasText: 'Black' }).click()
  await modal().getByRole('button', { name: '添加映射', exact: true }).click()
  await modal().getByRole('textbox', { name: '客户展示名 2', exact: true }).fill('Single SKU Collection')
  await modal().getByRole('textbox', { name: '客户货号 2', exact: true }).fill('CLIENT-001')
  await previewButton().click(); await confirm()
  await modal().getByRole('cell', { name: 'CLIENT-001', exact: true }).waitFor()
  assert.match(await modal().innerText(), /新增 1 · 修改 0 · 删除 0/)
  await modal().getByRole('cell', { name: 'Single SKU Collection · 货号 CLIENT-001', exact: true }).waitFor()
  await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/mapping-preview-1440.png`, fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  assert.ok(await modal().evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/mapping-editor-390.png`, fullPage: true })
  await page.setViewportSize({ width: 320, height: 740 })
  assert.ok(await modal().evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  await publishButton().click(); await modal().waitFor({ state: 'hidden' })
  const lastPublish = calls.filter(c => c.path.endsWith('/publish')).at(-1)
  assert.equal(lastPublish.body.entries[1].item_id, first)
  assert.equal(lastPublish.body.entries[1].customer_sku, 'CLIENT-001')
  assert.equal(lastPublish.version, '"5"')
  assert.equal(calls[0].body.entries.length, 1)
  await open()
  denyPreview = true
  await previewButton().click()
  await modal().getByText('预览范围已撤销', { exact: true }).waitFor()
  assert.equal(await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).count(), 0)
  assert.equal(await modal().getByText('My Revised Collection', { exact: true }).count(), 0)
  denyPreview = false
  await open()
  await previewButton().click(); await confirm()
  denyPublish = true
  await publishButton().click()
  await modal().getByText('发布权限已撤销', { exact: true }).waitFor()
  assert.equal(await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).count(), 0)
  assert.equal(await modal().getByRole('heading', { name: /版本差异/ }).count(), 0)
  denyPublish = false
  permissions = ['portal_access:read', 'portal_mapping:read']
  await open()
  assert.equal(await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).isDisabled(), true)
  assert.equal(await publishButton().isVisible(), false)
  denied = true
  await modal().getByRole('button', { name: '重新读取当前版本（舍弃草稿）', exact: true }).click()
  await modal().getByText('映射不在当前授权范围。', { exact: true }).waitFor()
  assert.equal(await modal().getByRole('textbox', { name: '客户展示名 1', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', calls: calls.length, scenarios: ['published versus draft additions modifications removals', 'preview and publish denial clear private state', 'withdrawn entry removal', 'all conflict messages', 'draft edits invalidate preview/confirmation', 'version conflict reload', 'uncertain publish readback only', 'SKU source and customer code', '1440/390/320 layout', 'versioned publish', 'read-only mapping', 'scope denial clears projection'] }))
} finally { await browser.close() }
