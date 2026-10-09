import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
let input = ''; for await (const part of process.stdin) input += part
const seed = JSON.parse(input)
const { chromium } = createRequire(import.meta.url)(modulePath)
const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = []
page.on('pageerror', error => errors.push(error.message))
await context.addInitScript(() => sessionStorage.setItem('leshine_welcome_shown_session', '1'))
const settings = origin + '/api/portal/admin/v1/settings'
async function save(reason) {
  await page.getByRole('textbox', { name: '站点操作原因' }).fill(reason)
  await page.locator('.el-checkbox').filter({ hasText: '我已核对启停' }).click()
  const response = page.waitForResponse(r => r.url() === settings && r.request().method() === 'PATCH')
  await page.getByRole('button', { name: '保存站点配置', exact: true }).click()
  const result = await response
  assert.equal(result.status(), 200)
  return (await result.json()).data
}
try {
  const initialSettings = page.waitForResponse(r => r.url() === settings && r.request().method() === 'GET')
  await page.goto(origin + '/portal/settings')
  await page.getByLabel('用户名', { exact: true }).fill(seed.username)
  await page.getByLabel('密码', { exact: true }).fill(seed.password)
  await page.locator('button[type="submit"]').click()
  const initialResponse = await initialSettings
  assert.equal(initialResponse.status(), 200)
  const configuration = (await initialResponse.json()).data
  const sameName = configuration.contact_employee_options.filter(employee => employee.name === seed.employeeName)
  const selectedIndex = sameName.findIndex(employee => employee.id === String(seed.actor))
  assert.ok(selectedIndex >= 0)
  await page.getByRole('button', { name: '添加业务员名片', exact: true }).click()
  await page.locator('.el-select').filter({ has: page.getByRole('combobox', { name: '名片员工 1', exact: true }) }).click()
  const choices = page.getByRole('option', { name: seed.employeeName, exact: true })
  assert.equal(await choices.count(), sameName.length)
  await choices.nth(selectedIndex).click()
  await page.getByRole('textbox', { name: '对外称呼 1', exact: true }).fill('April LeShine')
  await page.getByRole('textbox', { name: '对外邮箱 1', exact: true }).fill('april@example.com')
  await page.getByRole('textbox', { name: 'WhatsApp 1', exact: true }).fill('+8613800000000')
  await page.locator('.el-checkbox').filter({ hasText: '批准此名片' }).click()
  const saved = await save('Approve customer contact')
  assert.equal(saved.policy_version, seed.policyVersion)
  assert.deepEqual(saved.policy.sales_contacts, [{ user_id: String(seed.actor), display_name: 'April LeShine', email: 'april@example.com', whatsapp: '+8613800000000', approved: true }])
  await page.reload()
  await page.getByRole('textbox', { name: '对外称呼 1', exact: true }).waitFor()
  assert.equal(await page.getByRole('textbox', { name: '对外称呼 1', exact: true }).inputValue(), 'April LeShine')
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.ok(await page.locator('.portal-settings').evaluate(el => el.scrollWidth <= el.clientWidth + 1))
    await page.locator('.settings-card').filter({ hasText: '获准对外展示的业务员名片' }).screenshot({ path: `${output}/live-contacts-${width}.png`, animations: 'disabled' })
  }
  await page.locator('.el-checkbox').filter({ hasText: '批准此名片' }).click()
  const revoked = await save('Withdraw public contact approval')
  assert.equal(revoked.policy_version, seed.policyVersion)
  assert.equal(revoked.policy.sales_contacts[0].approved, false)
  await page.reload()
  await page.getByRole('textbox', { name: '对外称呼 1', exact: true }).waitFor()
  assert.equal(await page.locator('.el-checkbox').filter({ hasText: '批准此名片' }).getByRole('checkbox').isChecked(), false)
  assert.deepEqual(errors, [])
  const report = { status: 'pass', apiInterceptions: 0, sameNameCandidates: sameName.length, checks: ['real employee login', 'employee selection', 'approved contact save', 'persistent readback', '1440/390/320', 'withdraw and readback', 'commercial policy unchanged'] }
  await writeFile(output + '/contacts-report.json', JSON.stringify(report))
  console.log(JSON.stringify(report))
} finally { await browser.close() }
