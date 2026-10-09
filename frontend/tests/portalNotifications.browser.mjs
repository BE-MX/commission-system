import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const id = '12345678-1234-1234-1234-123456789abc', eventId = '22345678-1234-1234-1234-123456789abc'
const posts = [], errors = []
let failList = false, denyReplay = false, canWrite = true, eventStatus = 'dead'
page.on('pageerror', error => errors.push(error.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-browser-test'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), url = new URL(req.url()); let data = {}
  if (url.pathname === '/api/auth/me') return route.fulfill({ json: { id: 1, name: 'QA', username: 'portal-test', roles: [], permissions: ['portal_order:read', ...(canWrite ? ['portal_order:write'] : [])] } })
  if (url.pathname === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-browser-test' } })
  const base = '/api/portal/admin/v1/orders/' + id
  if (url.pathname === base + '/notifications/' + eventId + '/retry') {
    posts.push({ body: req.postDataJSON(), key: req.headers()['idempotency-key'] })
    if (posts.length === 1) return route.abort('failed')
    if (denyReplay) return route.fulfill({ status: 403, json: { code: 403, message: '当前员工无此操作权限。', data: { error_code: 'ACTION_FORBIDDEN' } } })
    eventStatus = 'pending'
    data = { replayed: true, original_receipt: { request_id: id, event_id: eventId, command_key: posts.at(-1).key, status: 'pending' }, current: { id: eventId, status: 'pending' } }
  } else if (url.pathname === base + '/notifications') {
    if (failList) return route.fulfill({ status: 404, json: { code: 404, message: '请求已不在当前授权范围内。', data: { error_code: 'RESOURCE_NOT_FOUND' } } })
    data = { request_id: id, items: [{ id: eventId, event_type: 'business_mail', recipient_kind: 'customer', status: eventStatus, attempt_count: eventStatus === 'dead' ? 8 : 0, error_code: eventStatus === 'dead' ? 'MAIL_TRANSPORT_FAILED' : null, fingerprint: 'a'.repeat(64), retry_eligible: eventStatus === 'dead', created_at: '2026-10-03T10:00:00', next_attempt_at: eventStatus === 'pending' ? '2026-10-03T10:01:00' : null }], total: 1, page: 1, page_size: 20 }
  } else if (url.pathname === '/api/portal/admin/v1/orders') {
    data = { items: [{ request_id: id, request_no: 'REQ-QA-001', status: 'submitted', submitted_at: '2026-10-03T10:00:00', currency: 'USD', product_amount: '100.00' }], total: 1 }
  } else if (url.pathname === base) {
    data = { request_id: id, request_no: 'REQ-QA-001', status: 'submitted', submitted_at: '2026-10-03T10:00:00', currency: 'USD', product_amount: '100.00', items: [], delivery: {}, customer_safe_timeline: [] }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const dialog = page.getByRole('dialog', { name: '通知投递记录' })
async function open() {
  await page.goto(`http://127.0.0.1:3211/portal/orders?request=${id}`)
  await page.getByRole('button', { name: '查看通知投递', exact: true }).click()
  await dialog.getByText('邮件服务暂时失败', { exact: true }).waitFor()
}
try {
  await open()
  await dialog.getByRole('button', { name: '申请重试', exact: true }).click()
  await dialog.getByRole('textbox').fill('Mail transport recovered')
  await dialog.locator('.el-checkbox').click()
  assert.ok(await dialog.getByRole('checkbox').isChecked())
  await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/notifications-1440.png`, fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/notifications-form-390.png`, fullPage: true })
  assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  assert.ok(await dialog.getByRole('button', { name: '确认重新排队', exact: true }).isEnabled())
  await page.setViewportSize({ width: 320, height: 720 })
  assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  await page.setViewportSize({ width: 1440, height: 1000 })
  await dialog.getByRole('button', { name: '确认重新排队', exact: true }).click()
  await dialog.getByText('重试结果待核对。请勿关闭或刷新浏览器，只重放原命令获取回执。', { exact: true }).waitFor()
  assert.ok(await dialog.getByRole('textbox').isDisabled())
  assert.ok(await dialog.getByRole('checkbox').isDisabled())
  assert.ok(await dialog.getByRole('button', { name: '刷新投递记录', exact: true }).isDisabled())
  const beforeUnload = page.waitForEvent('dialog')
  const reload = page.reload().catch(() => null)
  const leavePrompt = await beforeUnload
  assert.equal(leavePrompt.type(), 'beforeunload'); await leavePrompt.dismiss(); await reload
  denyReplay = true
  await dialog.getByRole('button', { name: '重放原重试命令', exact: true }).click()
  await dialog.getByText('当前员工无此操作权限。', { exact: true }).waitFor()
  assert.equal(await dialog.getByRole('textbox').count(), 0)
  assert.equal(await dialog.getByText('邮件服务暂时失败', { exact: true }).count(), 0)
  denyReplay = false
  await dialog.getByRole('button', { name: '重放原重试命令', exact: true }).click()
  await dialog.getByText('等待投递', { exact: true }).waitFor()
  assert.equal(posts.length, 3); assert.deepEqual(posts[0], posts[1]); assert.deepEqual(posts[1], posts[2])
  failList = true
  await dialog.getByRole('button', { name: '刷新投递记录', exact: true }).click()
  await dialog.getByText('请求已不在当前授权范围内。', { exact: true }).waitFor()
  assert.equal(await dialog.getByText('等待投递', { exact: true }).count(), 0)
  failList = false; canWrite = false; eventStatus = 'dead'
  await open()
  assert.equal(await dialog.getByRole('button', { name: '申请重试', exact: true }).count(), 0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/notifications-390.png`, fullPage: true })
  assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  await page.setViewportSize({ width: 320, height: 720 })
  assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', scenarios: 10, simulatedWrites: posts.length }))
} catch (error) { console.error(JSON.stringify({ url: page.url(), errors, body: (await page.locator('body').innerText()).slice(0, 2500) })); throw error } finally { await browser.close() }
