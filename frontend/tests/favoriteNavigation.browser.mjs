import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'

const { chromium } = createRequire(import.meta.url)(process.env.NAV_PLAYWRIGHT_MODULE || 'playwright')
const output = process.env.NAV_QA_OUTPUT
assert.ok(output)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
const errors = [], writes = [], requests = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => { requests.push(request.url()); if (request.method() === 'PUT') writes.push(request.postDataJSON()) })
const fixture = 'http://127.0.0.1:3347/tests/fixtures/favorite-navigation/index.html#/dashboard'
const sidebar = page.locator('.aside'), section = sidebar.getByRole('region', { name: '常用导航' })
const dialog = page.getByRole('dialog', { name: '管理常用导航' })
const rows = section.locator('.favorite-row')
const order = () => rows.evaluateAll(elements => elements.map(element => element.dataset.favoriteKey))
async function settled() { await page.waitForFunction(() => document.querySelector('.favorite-navigation')?.getAttribute('aria-busy') === 'false') }
async function manage() { await sidebar.getByRole('button', { name: '管理常用导航', exact: true }).click(); await dialog.waitFor() }
async function choose(title) { await dialog.getByRole('checkbox', { name: title, exact: true }).click(); await settled() }
async function done() { await dialog.getByRole('button', { name: '完成', exact: true }).click(); await dialog.waitFor({ state: 'hidden' }) }
try {
  for (const name of ['alice', 'bob']) {
    const identity = await (await page.request.get(`http://127.0.0.1:8347/fixture/users/${name}`)).json()
    await page.request.put('http://127.0.0.1:8347/api/system/navigation-preferences', { headers: { Authorization: `Bearer ${identity.access_token}` }, data: { items: [] } })
    for (const key of ['Announcements', 'WaybillUpload', 'NotRegistered']) {
      const denied = await page.request.put('http://127.0.0.1:8347/api/system/navigation-preferences', { headers: { Authorization: `Bearer ${identity.access_token}` }, data: { items: [key] } })
      assert.equal(denied.status(), 403)
    }
  }
  await page.goto(fixture)
  await page.locator('[data-user]').filter({ hasText: 'alice' }).waitFor()
  await settled()
  assert.equal(await rows.count(), 0)
  await manage()
  assert.equal(await dialog.getByRole('checkbox', { name: '角色管理', exact: true }).count(), 0)
  assert.equal(await dialog.getByRole('checkbox', { name: '公告管理', exact: true }).count(), 0)
  assert.equal(await dialog.getByRole('checkbox', { name: '运单上传', exact: true }).count(), 0)
  await choose('工作台'); await choose('订单发票管理'); await choose('物流跟踪')
  await done()
  const original = await order()
  assert.equal(original.length, 3)
  await rows.nth(2).locator('.favorite-drag').dragTo(rows.nth(0).locator('.favorite-drag'))
  await settled()
  assert.deepEqual(await order(), [original[2], original[0], original[1]])
  await page.reload(); await settled()
  assert.deepEqual(await order(), [original[2], original[0], original[1]])
  await section.getByRole('link', { name: '订单发票管理', exact: true }).click()
  await page.getByRole('heading', { name: '订单发票管理', exact: true }).waitFor()
  assert.equal(await section.getByRole('link', { name: '订单发票管理', exact: true }).getAttribute('aria-current'), 'page')
  await page.screenshot({ path: `${output}/desktop.png` })
  await page.getByRole('button', { name: 'Bob', exact: true }).click()
  await page.locator('[data-user]').filter({ hasText: 'bob' }).waitFor()
  await settled()
  assert.equal(await rows.count(), 0)
  await manage(); await choose('工作台'); await done()
  await page.getByRole('button', { name: 'Alice', exact: true }).click()
  await page.locator('[data-user]').filter({ hasText: 'alice' }).waitFor(); await settled()
  assert.deepEqual(await order(), [original[2], original[0], original[1]])
  await manage(); await choose('订单发票管理'); await choose('采购节看板'); await done()
  assert.equal(await section.getByRole('link', { name: '订单发票管理', exact: true }).count(), 0)
  const external = section.getByRole('link', { name: '采购节看板', exact: true })
  assert.equal(await external.getAttribute('href'), '/festival/')
  assert.equal(await external.getAttribute('target'), '_blank')
  // Keyboard alternative adjusts the same persisted order.
  const beforeKeyboard = await order()
  await rows.nth(0).locator('.favorite-drag').focus()
  await page.keyboard.press('Alt+ArrowDown'); await settled()
  const afterKeyboard = await order()
  assert.equal(afterKeyboard[1], beforeKeyboard[0])
  await page.getByRole('button', { name: '折叠', exact: true }).click()
  assert.equal(await section.getByRole('link', { name: '工作台', exact: true }).isVisible(), true)
  await section.getByRole('link', { name: '工作台', exact: true }).click()
  await page.getByRole('heading', { name: '工作台', exact: true }).waitFor()
  await page.getByRole('button', { name: '折叠', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await manage()
  const box = await dialog.boundingBox()
  assert.ok(box.x >= 0 && box.x + box.width <= 390)
  await dialog.getByRole('textbox', { name: '搜索常用导航候选' }).fill('物流')
  assert.equal(await dialog.getByRole('checkbox', { name: '物流跟踪', exact: true }).count(), 1)
  await page.screenshot({ path: `${output}/mobile-manager.png` })
  await done()
  await page.getByRole('button', { name: '撤销权限', exact: true }).click()
  assert.deepEqual(await order(), [original[0]])
  await page.reload(); await settled()
  assert.deepEqual(await order(), afterKeyboard)
  assert.deepEqual(errors, [])
  assert.ok(requests.every(url => /^http:\/\/127\.0\.0\.1:(3347|8347)\//.test(url)))
  await writeFile(`${output}/result.json`, JSON.stringify({ status: 'passed', original, afterKeyboard, writes: writes.length, errors, checks: ['add', 'remove', 'drag', 'refresh', 'route', 'active', 'user-isolation', 'external', 'keyboard', 'collapsed', 'mobile-dialog', 'permission-restoration', 'route-permission-candidates', 'server-rejects-unauthorized-and-unknown-keys'] }, null, 2))
  console.log('Favorite navigation browser acceptance passed')
} finally { await browser.close() }
