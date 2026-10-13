// Run against a task-local Vite preview. All APIs are synthetic and intercepted.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(require.resolve('playwright', { paths: [process.env.ARK_PLAYWRIGHT_MODULE_DIR || process.cwd()] }))
const base = process.env.ARK_UI_TEST_URL || 'http://127.0.0.1:4317'
const evidence = path.resolve(process.env.ARK_UI_EVIDENCE_DIR || 'tmp/whatsapp-baileys')
fs.mkdirSync(evidence, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = [], requests = []
page.on('pageerror', error => errors.push(error.message))
await page.addInitScript(() => localStorage.setItem('ark_access_token', 'synthetic-ui-test'))
const user = { id: 1, real_name: 'Synthetic Owner', username: 'synthetic', roles: ['super_admin'], permissions: ['whatsapp:read', 'whatsapp:write', 'whatsapp:admin'] }
const accounts = [{ id: 1, account_uid: 'wa_ui', ark_user_id: 1, ark_user_name: 'Synthetic Owner',
  display_name: 'Synthetic Business', provider: 'baileys', status: 'active', consent_state: 'active',
  can_read_body: true, crm_shared: false, connector_status: 'connected', connection_state: 'online',
  sync_state: 'synced_available', history_state: 'partial', consent_version: 1, reader_user_ids: [] },
{ id: 2, account_uid: 'wa_other', ark_user_id: 2, display_name: 'Metadata Only', provider: 'baileys', status: 'active', consent_state: 'active', can_read_body: false }]
let bindGets = 0
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), pathname = url.pathname
  requests.push({ path: pathname, method: request.method(), query: url.searchParams.toString() })
  let data = [], raw = false
  if (pathname === '/api/auth/me') { data = user; raw = true }
  else if (pathname === '/api/whatsapp/accounts') data = accounts
  else if (pathname === '/api/whatsapp/conversations') {
    const offset = (Number(url.searchParams.get('page') || 1) - 1) * Number(url.searchParams.get('page_size') || 20)
    data = { total: 70, items: Array.from({ length: 20 }, (_, n) => ({ conversation_uid: `conv_${offset + n}`, chat_id: `synthetic_${offset + n}@c.us`,
      contact_name: `Synthetic Chat ${offset + n}`, history_state: 'partial', last_message_preview: 'synthetic preview' })) }
  } else if (pathname === '/api/whatsapp/messages') data = { total: 70, items: [
    { message_uid: 'ui_outbound', direction: 'outbound', content_text: '示例回复：收到，我核对后回复。', sent_at: '2026-10-13T09:32:00+08:00' },
    { message_uid: 'ui_inbound', direction: 'inbound', sender_name: '示例客户', content_text: '示例客户：请确认这款产品的交期。', sent_at: '2026-10-13T09:31:00+08:00' },
    { message_uid: 'ui_message', direction: 'inbound', content_text: 'obsolete synthetic content', deleted_at: '2026-10-13T09:30:00+08:00', sent_at: '2026-10-13T09:30:00+08:00' },
  ] }
  else if (pathname === '/api/whatsapp/bind-sessions' && request.method() === 'POST') {
    const body = request.postDataJSON(); assert.equal(body.company_account, true)
    data = { bind_session_uid: 'bind_ui', account_uid: body.account_uid || 'wa_ui_new', status: 'pending' }
  } else if (pathname === '/api/whatsapp/bind-sessions/bind_ui') {
    bindGets++; data = { bind_session_uid: 'bind_ui', account_uid: 'wa_ui_new', status: 'active' }
  } else if (pathname.endsWith('/reader-candidates')) data = [{ id: 3, name: 'Synthetic Reader' }]
  else if (pathname.endsWith('/consent')) data = accounts[0]
  else if (pathname.endsWith('/revoke')) {
    Object.assign(accounts[0], { status: 'revoke_pending', consent_state: 'revoked', can_read_body: false, revoke_state: 'remote_unconfirmed' }); data = accounts[0]
  } else if (pathname.endsWith('/revoke-confirmation')) {
    Object.assign(accounts[0], { status: 'revoked', connector_status: 'owner_confirmed', revoke_state: 'owner_confirmed' }); data = accounts[0]
  }
  else if (pathname.endsWith('/sync/pull')) data = { account_uid: 'wa_ui', resource: 'messages', pulled: 2, next_cursor: null }
  else if (pathname.includes('/announcements')) data = { items: [], total: 0, unread_count: 0 }
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(raw ? data : { code: 200, message: 'ok', data }) })
})
try {
  await page.goto(`${base}/system/whatsapp-connector`)
  await page.waitForLoadState('networkidle')
  await page.getByText('Synthetic Business', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(evidence, 'desktop.png'), fullPage: true })
  const restricted = page.locator('.el-table__row').filter({ hasText: 'Metadata Only' })
  assert.equal(await restricted.getByRole('button', { name: '查看对话', exact: true }).isDisabled(), true)
  await page.getByRole('button', { name: '关联业务号', exact: true }).click()
  const bindDialog = page.getByRole('dialog', { name: '关联公司业务号', exact: true })
  assert.equal(await bindDialog.getByRole('button', { name: '确认授权并关联' }).isDisabled(), true)
  await bindDialog.getByText('我确认这是公司专用业务号，允许同步全部会话（包含群聊）', { exact: true }).click()
  assert.equal(await bindDialog.getByRole('checkbox', { name: /我确认这是公司专用业务号/ }).isChecked(), true)
  await bindDialog.getByRole('button', { name: '确认授权并关联' }).click()
  await bindDialog.getByText('已关联，可关闭窗口').waitFor({ timeout: 10000 })
  assert.ok(bindGets > 0)
  await bindDialog.getByRole('button', { name: '关闭', exact: true }).click()
  await page.locator('.el-table__row').filter({ hasText: 'Synthetic Business' }).getByRole('button', { name: '查看对话', exact: true }).click()
  await page.getByText('Synthetic Chat 0', { exact: true }).first().waitFor()
  await page.getByText('[消息已撤回]', { exact: true }).waitFor()
  assert.equal(await page.getByText('obsolete synthetic content', { exact: true }).count(), 0)
  await page.screenshot({ path: path.join(evidence, 'chat-records.png'), fullPage: true })
  await page.locator('.conversation-list .el-pagination').getByLabel('下一页').click()
  await page.getByText('Synthetic Chat 20', { exact: true }).first().waitFor()
  assert.ok(requests.some(item => item.path.endsWith('/conversations') && item.query.includes('page=2')))
  await page.locator('.el-table__row').filter({ hasText: 'Synthetic Business' }).getByRole('button', { name: '授权范围', exact: true }).click()
  const consentDialog = page.getByRole('dialog', { name: '账号授权范围', exact: true })
  assert.equal(await consentDialog.getByRole('button', { name: '保存授权' }).isDisabled(), true)
  await consentDialog.getByText('确认公司专用业务号允许全部会话（包含群聊）', { exact: true }).click()
  await consentDialog.getByRole('button', { name: '保存授权' }).click()
  await page.locator('.el-table__row').filter({ hasText: 'Synthetic Business' }).getByRole('button', { name: '解绑', exact: true }).click()
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await page.getByText(/远端注销未确认，请在手机/).waitFor()
  await page.getByRole('button', { name: '确认手机已移除', exact: true }).click()
  await page.getByRole('button', { name: '已核对并移除', exact: true }).click()
  await page.getByText('已记录持有人核对结果', { exact: true }).waitFor()
  await page.getByRole('dialog', { name: '持有人确认', exact: true }).waitFor({ state: 'hidden' })
  await page.waitForFunction(() => document.querySelectorAll('.el-message').length === 0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await page.waitForLoadState('networkidle')
  await page.getByText('Synthetic Business', { exact: true }).waitFor()
  await page.screenshot({ path: path.join(evidence, 'mobile.png'), fullPage: true })
  await page.getByRole('button', { name: '关联业务号', exact: true }).click()
  const mobileBind = page.getByRole('dialog', { name: '关联公司业务号', exact: true })
  await mobileBind.waitFor()
  await mobileBind.getByRole('button', { name: '确认授权并关联' }).waitFor()
  await page.waitForFunction(() => {
    const dialog = document.querySelector('[role="dialog"][aria-label="关联公司业务号"]')
    if (!dialog) return false
    const bounds = dialog.getBoundingClientRect()
    return bounds.width > 200 && bounds.top >= 0 && bounds.bottom <= innerHeight &&
      !dialog.closest('.dialog-fade-enter-active, .dialog-fade-enter-from')
  })
  await page.screenshot({ path: path.join(evidence, 'mobile-binding.png'), fullPage: true })
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log(JSON.stringify({ checks: ['metadata ACL', 'explicit bind consent', 'automatic bind poll', 'message tombstone', 'conversation pagination', 'separate consent controls', 'unconfirmed revoke', 'explicit owner phone attestation', 'desktop and mobile render'], pageErrors: errors.length, requests: requests.length }))
} catch (error) {
  await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true })
  console.error(JSON.stringify({ pageErrors: errors, dialogs: await page.getByRole('dialog').allTextContents() }))
  throw error
} finally { await browser.close() }
