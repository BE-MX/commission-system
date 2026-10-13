// Synthetic API only. Run against a task-local Vite preview, never the production backend.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(require.resolve('playwright', { paths: [process.env.ARK_PLAYWRIGHT_MODULE_DIR || process.cwd()] }))
const base = process.env.ARK_UI_TEST_URL || 'http://127.0.0.1:4321'
const evidence = path.resolve(process.env.ARK_UI_EVIDENCE_DIR || '../tmp/whatsapp-assistant')
fs.mkdirSync(evidence, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: 'America/Los_Angeles' })
const errors = [], posts = [], requests = [], runs = []
let runGets = 0, readbackAvailable = false, stale = false, allowAi = true, presetAvailable = true, knowledgeAvailable = true, configurationReason = '', patchConflict = false
const owner = { id: 1, username: 'synthetic', real_name: 'Synthetic Owner', roles: ['super_admin'], permissions: ['whatsapp:read', 'whatsapp:write'] }
const account = { id: 1, account_uid: 'synthetic_account', ark_user_id: 1, ark_user_name: 'Synthetic Owner', display_name: 'Synthetic Business', provider: 'baileys', status: 'active', consent_state: 'active', can_read_body: true, crm_shared: false, ai_egress_allowed: true, consent_version: 1, reader_user_ids: [], history_state: 'partial' }
const result = { conversation_uid: 'chat_one', title: 'Synthetic Customer', message_count: 2, summary: '客户希望确认交期。<img src=x onerror="window.__unsafe=1">', open_questions: ['交期是否满足要求？'], follow_up_suggestions: [{ text: '先核对产品交期，再回复客户。', message_uids: ['synthetic_msg_1'], knowledge_source_ids: ['knowledge_one'] }], tasks: [{ task_uid: 'task_one', title: '核对客户交期', description: '核对库存与交付时间后回复', priority: 'P1', due_date: '2026-10-14', completed: false, message_uids: ['synthetic_msg_1'], knowledge_source_ids: ['knowledge_one'] }], knowledge_sources: [{ source_id: 'knowledge_one', document_id: 1, revision_id: 3, title: 'Synthetic Delivery Policy', version_no: 3 }], coverage: { history_state: 'partial', gap_reason: '旧历史未同步' } }
const completedRun = run => ({ ...run, status: 'succeeded', processed_conversations: 1, results: [structuredClone(result)] })
page.on('pageerror', error => errors.push(error.message))
await page.addInitScript(() => localStorage.setItem('ark_access_token', 'synthetic-ui-test'))
await page.clock.setFixedTime(new Date('2026-10-12T16:30:00Z'))
await page.route('**/*', route => new URL(route.request().url()).origin === new URL(base).origin ? route.continue() : route.abort())
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method()
  requests.push({ pathname, method })
  let data = [], status = 200, raw = false
  if (pathname === '/api/auth/me') { data = owner; raw = true }
  else if (pathname === '/api/whatsapp/accounts') data = [account, { ...account, id: 2, account_uid: 'metadata_only', ark_user_id: 2, display_name: 'Metadata Only', can_read_body: false }]
  else if (pathname === '/api/whatsapp/conversations') data = { total: 1, items: [{ conversation_uid: 'chat_one', contact_name: 'Synthetic Customer', chat_id: 'synthetic@g.us', history_state: 'partial' }] }
  else if (pathname === '/api/whatsapp/messages') data = { total: 1, items: [{ message_uid: 'synthetic_msg_1', content_text: 'Please confirm delivery.', sent_at: '2026-10-13T00:20:00+08:00' }] }
  else if (pathname.endsWith('/reader-candidates')) data = []
  else if (pathname === '/api/whatsapp/ai-assistant/options') data = { ai_allowed: allowAi, knowledge_available: knowledgeAvailable, preset_available: presetAvailable, can_analyze: allowAi && presetAvailable, reason: configurationReason, limits: { max_days: 31, max_messages: 2000, max_conversations: 25, max_calls: 20 } }
  else if (pathname === '/api/whatsapp/ai-assistant/runs' && method === 'GET') data = { items: [...runs].reverse() }
  else if (pathname === '/api/whatsapp/ai-assistant/runs' && method === 'POST') {
    const payload = request.postDataJSON(); posts.push(payload)
    const existing = runs.find(item => item.client_request_uid === payload.client_request_uid)
    if (existing) {
      assert.deepEqual(payload, posts[1]); data = { ...completedRun(existing), results: [] }
      runs[runs.indexOf(existing)] = completedRun(existing)
    } else {
      const run = { ...payload, run_uid: `run_${posts.length}`, status: 'pending', message_count: 2, conversation_count: 1, processed_conversations: 0, created_at: '2026-10-13T00:30:00+08:00', results: [], warnings: [] }
      runs.push(run); data = run
      if (posts.length === 2) { await route.abort('failed'); return }
    }
  } else if (pathname.includes('/ai-assistant/runs/requests/')) {
    if (!readbackAvailable) { status = 404; data = null }
    else data = completedRun(runs.at(-1))
  } else if (pathname.includes('/tasks/') && method === 'PATCH') {
    if (patchConflict) { status = 409; stale = true; data = null }
    else {
      assert.equal(request.postDataJSON().completed, true)
      data = completedRun(runs[0]); data.results[0].tasks[0].completed = true; runs[0] = data
    }
  } else if (pathname.includes('/ai-assistant/runs/')) {
    runGets++
    const uid = pathname.split('/').at(-1), stored = runs.find(item => item.run_uid === uid)
    data = stale ? { ...stored, status: 'stale', error_message: '消息或知识来源已变化，请重新分析', results: [] }
      : runGets < 2 ? { ...stored, status: 'running', results: [] } : stored?.status === 'succeeded' ? stored : completedRun(stored)
  } else if (pathname.includes('/announcements')) data = { items: [], total: 0, unread_count: 0 }
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(status === 404 ? { detail: 'not found' } : status === 409 ? { detail: 'source changed' } : raw ? data : { code: 200, message: 'ok', data }) })
})
const dialog = () => page.getByRole('dialog', { name: 'AI消息助手', exact: true })
async function openAssistant() { await page.getByRole('button', { name: 'AI消息助手', exact: true }).click(); await dialog().waitFor() }
try {
  await page.goto(`${base}/system/whatsapp-connector`); await page.waitForLoadState('networkidle')
  const row = page.locator('.el-table__row').filter({ hasText: 'Synthetic Business' })
  assert.equal(await page.locator('.el-table__row').filter({ hasText: 'Metadata Only' }).getByRole('button', { name: '查看对话', exact: true }).isDisabled(), true)
  await row.getByRole('button', { name: '授权范围', exact: true }).click()
  const consent = page.getByRole('dialog', { name: '账号授权范围', exact: true })
  assert.equal(await consent.getByRole('checkbox', { name: '允许客户工作台共享已绑定会话', exact: true }).isChecked(), false)
  assert.equal(await consent.getByRole('checkbox', { name: /允许主动调用已有 AI 供应商/ }).isDisabled(), false)
  await consent.getByRole('button', { name: '取消', exact: true }).click()
  await row.getByRole('button', { name: '查看对话', exact: true }).click()
  await page.getByText('Please confirm delivery.', { exact: true }).waitFor()
  await openAssistant()
  await dialog().getByRole('button', { name: '开始分析', exact: true }).waitFor()
  const inputs = dialog().locator('.assistant-range input')
  assert.equal(await inputs.nth(0).inputValue(), '2026-10-06 00:30:00')
  assert.equal(await inputs.nth(1).inputValue(), '2026-10-13 00:30:00')
  await dialog().getByRole('button', { name: '开始分析', exact: true }).click()
  await dialog().getByText('等待分析', { exact: true }).waitFor()
  assert.equal(posts.length, 1); assert.equal(posts[0].conversation_uid, null)
  assert.equal(posts[0].start_at, '2026-10-06T00:30:00+08:00'); assert.match(posts[0].client_request_uid, /^[\da-f-]{36}$/)
  await dialog().getByText('分析完成', { exact: true }).waitFor({ timeout: 12000 })
  await dialog().getByText(/旧历史未同步/).waitFor()
  assert.equal(await dialog().locator('img').count(), 0)
  assert.equal(await page.evaluate(() => window.__unsafe), undefined)
  assert.ok((await dialog().textContent()).includes('Synthetic Delivery Policy · 版本 3'))
  await dialog().getByText('核对客户交期', { exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.report-task.completed'))
  assert.equal(requests.some(item => item.pathname.includes('/task/')), false)
  await page.screenshot({ path: path.join(evidence, 'assistant-desktop.png'), fullPage: true })
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  await openAssistant(); await dialog().getByText('分析完成', { exact: true }).waitFor()
  assert.equal(posts.length, 1); assert.equal(await dialog().getByRole('checkbox', { name: '核对客户交期', exact: true }).isChecked(), true)
  await dialog().getByText('当前会话', { exact: true }).click()
  await dialog().getByRole('button', { name: '开始分析', exact: true }).click()
  await dialog().getByRole('button', { name: '查询提交状态', exact: true }).waitFor()
  await dialog().getByText(/暂未找到提交记录/).waitFor()
  assert.equal(posts.length, 2); assert.equal(posts[1].conversation_uid, 'chat_one')
  assert.equal(await dialog().locator('.assistant-range input').nth(0).isDisabled(), true)
  await page.screenshot({ path: path.join(evidence, 'assistant-retry.png'), fullPage: true })
  await dialog().getByRole('button', { name: '重新提交本次分析', exact: true }).click()
  await dialog().getByText('分析完成', { exact: true }).waitFor()
  assert.equal(posts.length, 3); assert.deepEqual(posts[2], posts[1]); assert.equal(runs.length, 2)
  patchConflict = true
  await dialog().getByText('核对客户交期', { exact: true }).click()
  await dialog().getByText('结果已失效', { exact: true }).waitFor()
  assert.equal(await dialog().getByText('聊天摘要', { exact: true }).count(), 0)
  await page.screenshot({ path: path.join(evidence, 'assistant-stale.png'), fullPage: true })
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  allowAi = false
  await openAssistant(); await dialog().getByText(/账号尚未允许 AI 分析外发/).waitFor()
  assert.equal(await dialog().getByRole('button', { name: '开始分析', exact: true }).isDisabled(), true)
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  allowAi = true; presetAvailable = false; knowledgeAvailable = false
  await openAssistant(); await dialog().getByText(/AI消息助手尚未配置可用模型/).waitFor()
  assert.equal(await dialog().getByText(/当前没有可用的知识来源/).count(), 0)
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  configurationReason = 'Synthetic administrator configuration required'
  await openAssistant(); await dialog().getByText(configurationReason, { exact: true }).waitFor()
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  presetAvailable = true; configurationReason = ''; stale = false; patchConflict = false
  await openAssistant(); await dialog().getByText('分析完成', { exact: true }).waitFor()
  assert.equal(await dialog().getByRole('button', { name: '开始分析', exact: true }).isDisabled(), false)
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  knowledgeAvailable = true
  await page.setViewportSize({ width: 390, height: 844 })
  await openAssistant(); await dialog().getByText('分析完成', { exact: true }).waitFor()
  await page.waitForFunction(() => { const el = document.querySelector('[role="dialog"][aria-label="AI消息助手"]'), b = el?.getBoundingClientRect(); return b && b.left >= 0 && b.right <= innerWidth && b.top >= 0 && b.bottom <= innerHeight && !el.closest('.dialog-fade-enter-active') })
  assert.equal(await dialog().locator('.assistant-body').evaluate(el => el.scrollWidth <= el.clientWidth), true, 'mobile report contents must not overflow horizontally')
  await page.screenshot({ path: path.join(evidence, 'assistant-mobile.png'), fullPage: true })
  await dialog().getByText('核对客户交期', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(evidence, 'assistant-mobile-checklist.png'), fullPage: true })
  await dialog().getByRole('button', { name: '开始分析', exact: true }).click()
  await dialog().getByText('等待分析', { exact: true }).waitFor()
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  const countAtClose = runGets
  await page.waitForTimeout(3500)
  assert.equal(runGets, countAtClose)
  await page.getByText('Please confirm delivery.', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(evidence, 'assistant-mobile-chat.png'), fullPage: true })
  account.ark_user_id = 2; account.reader_user_ids = [1]
  await page.locator('.whatsapp-panel .table-tools').getByRole('button', { name: /刷新/ }).click()
  await page.waitForLoadState('networkidle')
  assert.equal(await row.getByRole('button', { name: '授权范围', exact: true }).count(), 0)
  await openAssistant(); await dialog().getByText('聊天摘要', { exact: true }).waitFor()
  await dialog().getByRole('button', { name: '关闭', exact: true }).click()
  account.can_read_body = false
  await page.locator('.whatsapp-panel .table-tools').getByRole('button', { name: /刷新/ }).click()
  await page.getByText('选择一个账号查看记录', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'AI消息助手', exact: true }).count(), 0)
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log(JSON.stringify({ checks: ['AI consent independent of CRM', 'metadata ACL', 'Beijing midnight and inclusive endpoints', 'whole account and selected chat', 'poll to completion', 'safe text rendering and citations', 'report-only checklist readback', 'restore without rerun', '404 does not automatically resend', 'explicit retry uses original UID and payload', '409 clears stale summary', 'AI authorization disabled', 'model failure not masked by knowledge', 'server configuration reason preferred', 'missing knowledge allows analysis', 'desktop/mobile overlay and contents', 'close cancels polling', 'granted body reader', 'body revocation clears panel'], posts: posts.length, pageErrors: errors.length, evidence }))
} catch (error) {
  await page.screenshot({ path: path.join(evidence, 'failure.png'), fullPage: true })
  console.error(JSON.stringify({ pageErrors: errors, dialogs: await page.getByRole('dialog').allTextContents() })); throw error
} finally { await browser.close() }
