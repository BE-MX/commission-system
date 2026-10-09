import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
const [origin, modulePath, executablePath, fixture, output] = process.argv.slice(2)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = [], writes = []
page.on('pageerror', e => errors.push(e.message))
const id = '22222222-2222-4222-8222-222222222222', reference = '7:' + 'a'.repeat(43)
let version = 1, imageId = null, loseWrite = false, slow = false, releasePreview, denied = false
let permissions = ['portal_site:admin', 'asset:admin']
await context.addInitScript(() => {
  localStorage.setItem('ark_access_token', 'synthetic-image-test')
  sessionStorage.setItem('leshine_welcome_shown_session', '1')
  window.imageUrls = { created: [], revoked: [] }
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL)
  URL.createObjectURL = blob => { const url = create(blob); window.imageUrls.created.push(url); return url }
  URL.revokeObjectURL = url => { window.imageUrls.revoked.push(url); revoke(url) }
})
await context.route('**/api/**', async route => {
  const req = route.request(), path = new URL(req.url()).pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Image QA', roles: [], permissions } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-image-test' } })
  const item = { id, display_name: 'Image QA Weft', color_name: 'Brown', row_version: version, image_asset_id: imageId, product_id: '1', sku_id: '2', sale_unit: 'pack', inventory_unit: 'pack', conversion_factor: '1', status: 'published' }
  let data
  if (path.endsWith('/preview')) {
    if (slow) await new Promise(resolve => { releasePreview = resolve })
    if (denied) return route.fulfill({ status: 403, json: { code: 403, message: '图片权限已撤销', data: { error_code: 'ACTION_FORBIDDEN' } } })
    return route.fulfill({ contentType: 'image/jpeg', headers: { 'X-Portal-Image-Reference': reference }, body: readFileSync(fixture) }).catch(() => {})
  }
  if (path.endsWith('/image-assets')) data = { items: [{ id: '7', name: 'Approved Weft.jpg', format: 'jpg' }], total: 1 }
  else if (path.endsWith('/catalog')) data = { items: [item], total: 1 }
  else if (path.endsWith('/catalog/' + id)) data = item
  else if (path.endsWith('/image') && req.method() === 'PATCH') {
    const body = req.postDataJSON(); writes.push(body)
    assert.equal(req.headers()['if-match'], `"${version}"`)
    assert.equal(body.asset_reference, body.asset_id === null ? null : reference)
    imageId = body.asset_id; version++; data = { ...item, image_asset_id: imageId, row_version: version }
    if (loseWrite) { loseWrite = false; return route.abort('failed') }
  } else throw new Error('Unexpected API ' + path)
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const dialog = () => page.locator('.portal-image-binding:visible')
const save = () => dialog().getByRole('button', { name: '确认图片设置', exact: true })
async function open() {
  await page.goto(origin + '/portal/catalog')
  await page.getByRole('button', { name: '展示图片', exact: true }).click()
  await dialog().getByRole('button', { name: '选择并预览', exact: true }).waitFor()
}
async function confirm() {
  await dialog().getByRole('textbox', { name: '图片操作原因' }).fill('Approved for customer catalog')
  await dialog().locator('.el-checkbox').click()
}
try {
  await open()
  assert.equal(await save().isDisabled(), true)
  await dialog().getByRole('button', { name: '选择并预览', exact: true }).click()
  await dialog().getByRole('img', { name: '待批准的商品图片', exact: true }).waitFor()
  await page.waitForFunction(() => document.querySelector('.image-preview img')?.naturalWidth > 0)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await dialog().evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await dialog().screenshot({ animations: 'disabled', path: `${output}/image-admin-${width}.png` })
  }
  await confirm(); await save().click(); await dialog().waitFor({ state: 'hidden' })
  assert.equal(imageId, '7')
  assert.equal(await page.evaluate(() => window.imageUrls.created.every(url => window.imageUrls.revoked.includes(url))), true)
  await open(); slow = true
  await dialog().getByRole('button', { name: '选择并预览', exact: true }).click()
  await page.waitForTimeout(150)
  assert.ok(releasePreview)
  await dialog().getByRole('button', { name: '移除当前图片', exact: true }).click()
  await confirm(); assert.equal(await save().isEnabled(), true)
  releasePreview(); slow = false
  await page.waitForTimeout(100)
  assert.equal(await dialog().getByRole('img', { name: '待批准的商品图片', exact: true }).count(), 0)
  loseWrite = true; await save().click()
  await dialog().getByText('保存结果未知，不能重发。请读取商品当前记录后重新核对。', { exact: true }).waitFor()
  assert.equal(await save().isDisabled(), true)
  assert.equal(await dialog().getByRole('button', { name: '关闭', exact: true }).isDisabled(), true)
  const count = writes.length
  await dialog().getByRole('button', { name: '读取当前商品并放弃草稿', exact: true }).click()
  await dialog().getByText('Image QA Weft / Brown · 当前图片 未绑定', { exact: true }).waitFor()
  assert.equal(writes.length, count); assert.equal(await save().isDisabled(), true)
  denied = true
  await dialog().getByRole('button', { name: '选择并预览', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.portal-image-binding input[aria-label="图片操作原因"]')?.value)
  assert.equal(await save().isDisabled(), true)
  assert.equal(await dialog().getByRole('img', { name: '待批准的商品图片', exact: true }).count(), 0)
  permissions = ['portal_site:admin']; await page.goto(origin + '/portal/catalog')
  await page.getByRole('cell', { name: 'Image QA Weft', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '展示图片', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', scope: 'Real built admin UI with mocked APIs', checks: ['preview bytes', '1440/390/320', 'version approval', 'object URL cleanup', 'slow preview cancellation', 'unknown save read recovery without replay', 'denied preview clears data', 'asset permission button'] }))
} finally { releasePreview?.(); await browser.close() }
