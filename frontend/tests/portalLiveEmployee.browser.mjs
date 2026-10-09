import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
let input = ''; for await (const part of process.stdin) input += part
const seed = JSON.parse(input)
const { chromium, request } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = []
page.on('pageerror', error => errors.push(error.message))
const api = origin + '/api/portal/admin/v1'
const auth = origin + '/api/auth'
async function login(username) {
  const client = await request.newContext()
  try {
    const response = await client.post(auth + '/login', { data: { username, password: seed.password } })
    assert.equal(response.status(), 200)
    return (await response.json()).access_token
  } finally { await client.dispose() }
}
const bearer = token => ({ Authorization: 'Bearer ' + token })
try {
  await page.goto(origin + '/portal/orders?request=' + seed.request_id)
  await page.getByLabel('用户名', { exact: true }).fill(seed.username)
  await page.getByLabel('密码', { exact: true }).fill(seed.password)
  const loggedIn = page.waitForResponse(r => r.url() === auth + '/login' && r.request().method() === 'POST')
  await page.locator('button[type="submit"]').click()
  const response = await loggedIn
  assert.equal(response.status(), 200)
  const token = (await response.json()).access_token
  assert.ok(token.split('.').length === 3)
  await page.getByRole('button', { name: '处理请求', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '处理客户下单请求', exact: true })
  await dialog.getByText('当前版本完整条款', { exact: true }).waitFor()
  assert.match(await dialog.innerText(), /128\.00/)
  await dialog.locator('.el-radio-button').filter({ hasText: '审核并生成正式 PI' }).click()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    await dialog.locator('.el-checkbox').scrollIntoViewIfNeeded()
    assert.ok(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await dialog.screenshot({ animations: 'disabled', path: `${output}/employee-review-${width}.png` })
  }
  await dialog.locator('.el-checkbox').click()
  assert.ok(await dialog.getByRole('checkbox').isChecked())
  const approved = page.waitForResponse(r => r.url() === api + '/orders/' + seed.request_id + '/approve')
  await dialog.getByRole('button', { name: '确认操作', exact: true }).click()
  const approvedResponse = await approved
  assert.equal(approvedResponse.status(), 200)
  assert.equal((await approvedResponse.json()).data.current_state, 'invoice_created')
  await dialog.waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '处理原 PI', exact: true }).waitFor()
  await page.getByRole('button', { name: '查看操作审计', exact: true }).click()
  const audit = page.getByRole('dialog', { name: '订单操作审计', exact: true })
  await audit.getByText('生成 PI', { exact: true }).waitFor()
  await audit.getByText('提交请求', { exact: true }).waitFor()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await audit.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await audit.screenshot({ animations: 'disabled', path: `${output}/employee-audit-${width}.png` })
  }
  await audit.getByRole('button', { name: '关闭', exact: true }).click()
  await audit.waitFor({ state: 'hidden' })
  const orderUrl = api + '/orders/' + seed.request_id
  const replay = await context.request.post(orderUrl + '/approve', {
    headers: { ...bearer(token), 'If-Match': '"3"' }, data: seed.approval })
  assert.equal(replay.status(), 200); assert.equal((await replay.json()).data.replayed, true)
  const outsider = await login(seed.outsider)
  assert.equal((await context.request.get(orderUrl, { headers: bearer(outsider) })).status(), 404)
  assert.equal((await context.request.get(orderUrl + '/audit', { headers: bearer(outsider) })).status(), 404)
  const hidden = await context.request.get(api + '/orders', { headers: bearer(outsider) })
  assert.equal(hidden.status(), 200); assert.equal((await hidden.json()).data.total, 0)
  assert.equal((await context.request.get(orderUrl, { headers: bearer(token.slice(0, -8) + 'tampered') })).status(), 401)
  await page.getByRole('button', { name: '查看操作审计', exact: true }).click()
  await audit.getByText('生成 PI', { exact: true }).waitFor()
  const admin = await login(seed.admin)
  const disabled = await context.request.put(auth + '/admin/users/' + seed.actor, {
    headers: bearer(admin), data: { is_active: false } })
  assert.equal(disabled.status(), 200)
  assert.equal((await context.request.get(orderUrl, { headers: bearer(token) })).status(), 403)
  assert.equal((await context.request.post(orderUrl + '/approve', {
    headers: { ...bearer(token), 'If-Match': '"3"' }, data: seed.approval })).status(), 403)
  assert.equal((await context.request.get(orderUrl + '/audit', { headers: bearer(token) })).status(), 403)
  const deniedAudit = page.waitForResponse(r => r.url().includes('/audit') && r.status() === 403)
  await audit.getByRole('button', { name: '刷新审计', exact: true }).click()
  await deniedAudit
  assert.equal(await audit.locator('.el-table__body tbody tr').count(), 0)
  await audit.getByRole('button', { name: '关闭', exact: true }).click()
  // Keep the original signed employee token in the live page; refresh must clear
  // private list after backend current-authorization rejection.
  await page.locator('.detail-drawer .el-drawer__close-btn').click()
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await page.getByText('当前账号没有查看权限。', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '详情', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', checks: 13, apiInterceptions: 0 }))
} finally { await browser.close() }
