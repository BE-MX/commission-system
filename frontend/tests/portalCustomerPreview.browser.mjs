import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = [], requests = []
const id = '11111111-1111-4111-8111-111111111111'
let denied = false
page.on('pageerror', e => errors.push(e.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-read-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), path = new URL(req.url()).pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Read only', roles: [], permissions: ['portal_mapping:read'] } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-read-only' } })
  requests.push(path)
  assert.equal(path, `/api/portal/admin/v1/customers/${id}/preview`)
  assert.equal(req.method(), 'POST'); assert.deepEqual(req.postDataJSON(), {})
  if (denied) return route.fulfill({ status: 404, json: { code: 404, message: '客户范围已撤销', data: { error_code: 'RESOURCE_NOT_FOUND' } } })
  return route.fulfill({ json: { code: 200, message: 'ok', data: { preview: true, access_id: id, mapping_version: 2, catalog_version: 3, access_status: 'enabled', items: Array.from({ length: 21 }, (_, i) => ({ item_id: String(i), model_name: `Silk ${i + 1}`, color_name: 'Midnight', customer_sku: `CLIENT-${i + 1}`, length: '20', weight: '20g', unit: 'pack' })) } } })
})
try {
  await page.goto(`${origin}/portal/customers/${id}/preview`)
  await page.getByRole('heading', { name: 'Preview · 客户目录预览' }).waitFor()
  await page.getByRole('cell', { name: 'Silk 1', exact: true }).waitFor()
  assert.equal(await page.getByRole('cell', { name: 'Silk 21', exact: true }).count(), 0)
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await page.getByRole('cell', { name: 'Silk 21', exact: true }).waitFor()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await page.locator('.customer-preview').evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await page.locator('.customer-preview').screenshot({ path: `${output}/readonly-preview-${width}.png`, animations: 'disabled' })
  }
  assert.equal(await page.getByRole('button', { name: /发布映射|下单|下载 PI/ }).count(), 0)
  assert.equal((await context.cookies()).some(c => c.name.includes('portal_session')), false)
  denied = true; await page.getByRole('button', { name: '重新读取预览', exact: true }).click()
  await page.getByText('客户范围已撤销', { exact: true }).waitFor()
  assert.equal(await page.getByRole('cell', { name: 'Silk 21', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', checks: ['mapping read without access/read or write', 'published rows', 'pagination', '1440/390/320', 'no customer cookie or actions', 'scope refusal clears rows'], requests: requests.length }))
} finally { await browser.close() }
