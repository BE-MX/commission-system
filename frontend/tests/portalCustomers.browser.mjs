import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
const page = await context.newPage()
const accessId = '11111111-1111-4111-8111-111111111111', accountId = '22222222-2222-4222-8222-222222222222', invitationId = '33333333-3333-4333-8333-333333333333'
let permissions = ['portal_access:read', 'portal_access:admin'], denied = false, failList = false, inviteLost = true, accountLost = true
let access = { id: accessId, company_display_name: 'Synthetic Buyer Company', status: 'enabled', row_version: 1, canonical_customer_id: '9007199254740993', sales_user_id: '5', capabilities: { can_view_price: true, can_order: true }, catalog_version: 1, mapping_version: 1, catalog_item_ids: ['withdrawn-product'] }
let account = { id: accountId, email: 'buyer@example.com', contact_name: 'Synthetic Buyer', status: 'active', row_version: 1, email_verified: true, membership_status: 'active', invitation: { id: invitationId, status: 'pending', row_version: 1 } }
const calls = [], errors = []
page.on('pageerror', error => errors.push(error.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-test-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const req = route.request(), url = new URL(req.url()), path = url.pathname
  if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic reviewer', roles: [], permissions } })
  if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-test-only' } })
  let data = {}
  const result = (status, message) => route.fulfill({ status, json: { code: status, message, data: { error_code: status === 404 ? 'RESOURCE_NOT_FOUND' : 'SERVICE_UNAVAILABLE' } } })
  if (path.startsWith('/api/portal/admin/v1/')) {
    if (req.method() !== 'GET') calls.push({ path, body: req.postDataJSON(), headers: { version: req.headers()['if-match'], key: req.headers()['idempotency-key'] } })
    if (path.endsWith('/customers') && req.method() === 'GET') {
      if (failList) return result(503, '列表暂不可用')
      data = { items: [access], total: 1 }
    } else if (path.endsWith(`/customers/${accessId}`)) {
      if (denied) return result(404, '记录不存在或不在当前授权范围内。')
      if (req.method() === 'PATCH') {
        const body = req.postDataJSON(); assert.equal('catalog_item_ids' in body, false)
        access = { ...access, ...body, row_version: access.row_version + 1 }; data = access
      } else data = { ...access, accounts: { items: [account], total: 1, page: 1, page_size: 20 } }
    } else if (path.endsWith(`/customers/${accessId}/invitations`)) {
      if (inviteLost) { inviteLost = false; return route.abort('failed') }
      data = { invitation_id: invitationId, event_id: '44444444-4444-4444-8444-444444444444', row_version: 1, replayed: true }
    } else if (path.endsWith(`/accounts/${accountId}`)) {
      account = { ...account, status: req.postDataJSON().status, row_version: account.row_version + 1 }
      if (accountLost) { accountLost = false; return route.abort('failed') }
      data = account
    } else if (path.endsWith(`/invitations/${invitationId}/revoke`)) {
      account.invitation = { ...account.invitation, status: 'revoked', row_version: 2 }
      data = { id: invitationId, row_version: 2, revoked: true }
    }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
const dialog = page.getByRole('dialog').filter({ has: page.getByRole('button', { name: '确认操作', exact: true }) })
const actionDialog = () => page.locator('.portal-access-action:visible')
async function checkConfirm() { await actionDialog().locator('.el-checkbox').filter({ hasText: '我已核对客户与影响' }).click() }
async function open() {
  await page.goto('http://127.0.0.1:3211/portal/customers')
  await page.getByRole('cell', { name: 'Synthetic Buyer Company', exact: true }).waitFor()
  await page.getByRole('button', { name: '管理', exact: true }).click()
  await page.getByText('buyer@example.com', { exact: true }).waitFor()
}
try {
  await open()
  await page.getByRole('button', { name: '邀请采购账号', exact: true }).click()
  await actionDialog().getByRole('textbox', { name: '采购邮箱', exact: true }).fill('new@example.com')
  await actionDialog().getByRole('textbox', { name: '采购联系人', exact: true }).fill('New Buyer')
  await checkConfirm(); await actionDialog().getByRole('button', { name: '确认操作', exact: true }).click()
  await actionDialog().getByRole('button', { name: '重试原邀请', exact: true }).waitFor()
  assert.equal(await actionDialog().getByRole('textbox', { name: '采购邮箱', exact: true }).isDisabled(), true)
  assert.equal(await actionDialog().getByRole('button', { name: '读取当前状态', exact: true }).count(), 0)
  await actionDialog().getByRole('button', { name: '重试原邀请', exact: true }).click()
  await page.getByText('邀请创建回执已确认，邮件已进入发送队列；不代表送达或账号已激活。请查看最新账号与邀请状态。', { exact: true }).waitFor()
  const invites = calls.filter(x => x.path.endsWith('/invitations'))
  assert.equal(invites.length, 2); assert.deepEqual(invites[0], invites[1]); assert.match(invites[0].headers.key, /^[0-9a-f-]{36}$/)

  await page.getByRole('button', { name: '停用账号', exact: true }).click()
  await actionDialog().getByRole('textbox', { name: '操作原因', exact: true }).fill('Account no longer used')
  await checkConfirm(); await actionDialog().getByRole('button', { name: '确认操作', exact: true }).click()
  await actionDialog().getByRole('button', { name: '读取当前状态', exact: true }).waitFor()
  assert.equal(await actionDialog().getByRole('button', { name: '重试原邀请', exact: true }).count(), 0)
  await actionDialog().getByRole('button', { name: '读取当前状态', exact: true }).click()
  await page.getByRole('button', { name: '恢复账号', exact: true }).waitFor()
  await page.getByText('已重新读取当前状态，但无法确认刚才操作是否成功。请核对账号和访问状态后再处理；本次没有重发写入。', { exact: true }).waitFor()
  assert.equal(calls.filter(x => x.path.endsWith(`/accounts/${accountId}`)).length, 1)

  await page.getByRole('button', { name: '恢复账号', exact: true }).click()
  await actionDialog().getByRole('textbox', { name: '操作原因', exact: true }).fill('Reviewed verified account')
  await checkConfirm(); await actionDialog().getByRole('button', { name: '确认操作', exact: true }).click()
  await page.getByRole('button', { name: '停用账号', exact: true }).waitFor()
  const accountCalls = calls.filter(x => x.path.endsWith(`/accounts/${accountId}`))
  assert.equal(accountCalls[1].body.status, 'active'); assert.equal(accountCalls[1].headers.version, '"2"')

  await page.getByRole('button', { name: '设置客户访问', exact: true }).click()
  await actionDialog().locator('.el-radio-button').filter({ hasText: '暂停' }).click()
  await actionDialog().locator('.el-checkbox').filter({ hasText: '允许查看价格' }).click()
  assert.equal(await actionDialog().getByRole('checkbox', { name: '允许下单及确认交易条件' }).isChecked(), false)
  await actionDialog().getByRole('textbox', { name: '操作原因', exact: true }).fill('Suspend customer access')
  await checkConfirm()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/access-settings-390.png`, fullPage: true })
  assert.ok(await actionDialog().evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  await actionDialog().getByRole('button', { name: '确认操作', exact: true }).click()
  await page.getByText('方舟客户 9007199254740993 · 负责人 5 · 已暂停', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '邀请采购账号', exact: true }).isDisabled(), true)
  assert.deepEqual(access.catalog_item_ids, ['withdrawn-product'])

  await page.getByRole('button', { name: '撤销邀请', exact: true }).click()
  await actionDialog().getByRole('textbox', { name: '操作原因', exact: true }).fill('Link no longer required')
  await checkConfirm(); await actionDialog().getByRole('button', { name: '确认操作', exact: true }).click()
  await page.getByText('最近邀请：已撤销', { exact: true }).waitFor()
  await page.setViewportSize({ width: 1440, height: 1050 })
  await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT}/customer-accounts-1440.png`, fullPage: true })

  denied = true
  await page.getByRole('button', { name: '刷新详情', exact: true }).click()
  await page.getByText('记录不存在或不在当前授权范围内。', { exact: true }).waitFor()
  assert.equal(await page.getByText('buyer@example.com', { exact: true }).count(), 0)
  denied = false; permissions = ['portal_access:read']
  await open()
  assert.equal(await page.getByRole('button', { name: '设置客户访问', exact: true }).isVisible(), false)
  assert.equal(await page.getByRole('button', { name: '停用账号', exact: true }).isVisible(), false)
  await page.keyboard.press('Escape'); await page.locator('.detail-drawer').waitFor({ state: 'hidden' })
  failList = true; await page.getByRole('button', { name: '刷新', exact: true }).click()
  await page.getByText('列表暂不可用', { exact: true }).waitFor()
  assert.equal(await page.getByRole('cell', { name: 'Synthetic Buyer Company', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ status: 'pass', writeCalls: calls.length, scenarios: ['invite exact replay', 'account uncertain readback only', 'verified restore', 'access suspension preserves grants', 'price revocation clears order capability', 'invitation revoke', '390px settings', 'scope denial clears detail', 'read-only controls', 'list failure clears records'] }))
} finally { await browser.close() }
