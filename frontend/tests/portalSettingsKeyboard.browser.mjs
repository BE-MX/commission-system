import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3211', output = process.env.PORTAL_QA_OUTPUT
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/); assert.ok(output); await mkdir(output, { recursive: true })
const motion = process.env.PORTAL_UI_MOTION || 'reduce'; assert.ok(['reduce', 'no-preference'].includes(motion))
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true }), results = []
function gate() { let release; const waiting = new Promise(resolve => { release = resolve }); return { waiting, release } }
async function reach(page, target) { await target.waitFor({ state: 'attached' }); for (let n = 0; n < 180; n++) { if (await target.evaluate(el => el === document.activeElement)) return; await page.keyboard.press('Tab') }; throw new Error('Unreachable ' + await target.evaluate(el => el.outerHTML)) }
async function activate(page, target, key = 'Enter') { await reach(page, target); await page.keyboard.press(key) }
async function waitFocused(page, target) { await page.waitForFunction(el => document.activeElement === el, await target.elementHandle()) }
async function observeClicks(target) { await target.evaluate(el => { el.dataset.qaClicks = '0'; if (el.dataset.qaClickObserver) return; el.dataset.qaClickObserver = '1'; el.addEventListener('click', () => { el.dataset.qaClicks = String(Number(el.dataset.qaClicks) + 1) }) }) }
async function type(page, target, value) { await reach(page, target); await page.keyboard.press('Control+A'); await page.keyboard.press('Backspace'); await page.keyboard.type(value); await page.keyboard.press('Tab') }
async function bounds(page) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No root horizontal overflow')
  assert.deepEqual(await page.locator('.portal-settings').evaluate(root => { const r = root.getBoundingClientRect(), bad = []; if (root.scrollWidth > root.clientWidth + 1) bad.push('root'); for (const el of root.querySelectorAll('input,textarea,button,.el-checkbox,.site-facts')) { const b = el.getBoundingClientRect(); if (!b.width || !b.height) continue; if (b.left < r.left - 1 || b.right > r.right + 1) bad.push(el.getAttribute('aria-label') || el.textContent); } return bad }), [], 'All settings controls remain horizontally inside')
}
try {
  for (const width of [1440, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 950 }, reducedMotion: motion })
    await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-settings-keyboard'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
    const page = await context.newPage(), errors = [], writes = [], blockedExternal = [], readGate = gate(); let saveGate, mode = 'ready', readFailure = false, version = 3, navigationPermissions = ['portal_site:admin']
    const name = 'LeShineApprovedPortal'.repeat(5).slice(0, 100), termCode = 'a'.repeat(64), termText = 'ApprovedPaymentConditions'.repeat(12).slice(0, 256), contactName = 'ApprovedRepresentative'.repeat(5).slice(0, 100), reason = 'ReviewedApprovedPolicy'.repeat(25).slice(0, 500)
    const email = 'a'.repeat(64) + '@' + 'b'.repeat(63) + '.' + 'c'.repeat(63) + '.' + 'd'.repeat(56) + '.test', whatsapp = '+123456789012345'
    assert.equal(email.length, 254)
    let value = { configured: true, id: '11111111-1111-4111-8111-111111111111', row_version: version, name: 'Initial Portal', site_code: 'leshine', origin: 'https://orders.example.test', currency: 'USD', language: 'en', status: 'enabled', contact_employee_options: [{ id: '5', name: 'Approved Employee' }], policy: { quote_valid_minutes: 15, proposal_valid_hours: [24,48], payment_terms: [{ code: 'prepaid', display_text: 'Payment before shipment', deposit_percent: '100.00' }], default_payment_term_code: 'prepaid', sales_contacts: [{ user_id: '5', display_name: 'Representative', email: 'representative@example.test', whatsapp: null, approved: true }] } }
    page.on('pageerror', error => errors.push(error.message))
    await context.route('**/*', route => { const url = new URL(route.request().url()); if (url.origin === origin) return route.continue(); blockedExternal.push(url.href); return route.abort() })
    await context.route('**/api/**', async route => {
      const req = route.request(), path = new URL(req.url()).pathname
      if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic administrator', roles: [], permissions: navigationPermissions } })
      if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-settings-keyboard' } })
      const send = (data, status=200, message='OK') => route.fulfill({ status, json: { code: status, message, data } })
      if (path !== '/api/portal/admin/v1/settings') return send({})
      if (req.method() === 'GET') { await readGate.waiting; if (readFailure) { readFailure = false; return send({}, 503, '站点配置暂不可用，请重试。') }; if (mode === 'denied') return send({ error_code: 'ACTION_FORBIDDEN' }, 403, '当前员工无此操作权限。'); return send(value) }
      assert.equal(req.method(), 'PATCH'); await saveGate.waiting
      writes.push({ body: req.postDataJSON(), version: req.headers()['if-match'] })
      if (mode === 'stale') return send({ error_code: 'VERSION_CONFLICT' }, 409, '记录已变化，请刷新确认。')
      if (mode === 'denied-save') return send({ error_code: 'ACTION_FORBIDDEN' }, 403, '当前员工无此操作权限。')
      assert.equal(req.headers()['if-match'], '"'+version+'"')
      assert.deepEqual(req.postDataJSON(), { name, status: 'enabled', reason, policy: { sales_contacts: [{ user_id: '5', display_name: contactName, approved: true, email, whatsapp }], quote_valid_minutes: 30, proposal_valid_hours: [24,168], payment_terms: [{ code: termCode, display_text: termText, deposit_percent: '100.00' }], default_payment_term_code: termCode } })
      value = { ...value, ...req.postDataJSON(), row_version: ++version }
      if (mode === 'lost') return route.abort('failed')
      return send(value)
    })
    try {
      await page.goto(origin+'/portal/settings'); await page.getByRole('status').filter({ hasText: '正在读取站点配置…' }).waitFor(); assert.equal(await page.locator('.portal-settings').getAttribute('aria-busy'), 'true'); readGate.release(); await page.getByRole('textbox', { name: '站点名称', exact: true }).waitFor()
      const save = page.getByRole('button', { name: '保存站点配置', exact: true }), reload = page.getByRole('button', { name: '读取当前配置并放弃草稿', exact: true }), confirm = page.getByRole('checkbox', { name: '我已核对启停、报价失效和付款条件对客户的影响', exact: true })
      await type(page, page.getByRole('textbox', { name: '站点操作原因', exact: true }), '')
      await activate(page, confirm, 'Space'); await activate(page, save)
      const invalid = page.getByRole('alert').filter({ hasText: '请填写站点名称和 1–500 字的操作原因。' }); await invalid.waitFor(); assert.equal(await invalid.evaluate(el => el === document.activeElement), true, 'Validation error must receive focus')
      await activate(page, save); assert.equal(await invalid.evaluate(el => el === document.activeElement), true, 'Repeated identical error must receive focus again'); assert.equal(writes.length, 0)
      await type(page, page.getByRole('textbox', { name: '站点名称', exact: true }), name)
      await type(page, page.getByRole('spinbutton', { name: '报价有效期', exact: true }), '30')
      await type(page, page.getByRole('textbox', { name: '提案有效期', exact: true }), '24, 168')
      await type(page, page.getByRole('textbox', { name: '付款代码 1', exact: true }), termCode)
      await type(page, page.getByRole('textbox', { name: '付款说明 1', exact: true }), termText)
      const term = page.getByRole('combobox', { name: '默认付款条件', exact: true }); await reach(page, term); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter'); await page.keyboard.press('Tab')
      await type(page, page.getByRole('textbox', { name: '对外称呼 1', exact: true }), contactName)
      await type(page, page.getByRole('textbox', { name: '对外邮箱 1', exact: true }), email)
      await type(page, page.getByRole('textbox', { name: 'WhatsApp 1', exact: true }), whatsapp)
      await type(page, page.getByRole('textbox', { name: '站点操作原因', exact: true }), reason)
      await activate(page, confirm, 'Space'); assert.equal(await confirm.isChecked(), true)
      await reach(page, page.getByRole('textbox', { name: '提案有效期', exact: true })); await page.keyboard.press('ArrowLeft'); await page.keyboard.press('ArrowRight'); await page.keyboard.press('Tab'); assert.equal(await confirm.isChecked(), true, 'Focus and caret movement are not edits')
      await type(page, page.getByRole('textbox', { name: '提案有效期', exact: true }), '24, 72'); assert.equal(await confirm.isChecked(), false); assert.equal(await save.isDisabled(), true)
      await type(page, page.getByRole('textbox', { name: '提案有效期', exact: true }), '24, 168'); await activate(page, confirm, 'Space'); await bounds(page)
      await page.screenshot({ path: output+'/prepared-'+width+'.png', fullPage: true }); await page.locator('.main-content').evaluate(el => { el.scrollTop = 0 }); await page.screenshot({ path: output+'/prepared-top-'+width+'.png', fullPage: true })
      async function submit(nextMode) { mode = nextMode; saveGate = gate(); await activate(page, save); await page.getByRole('status').filter({ hasText: '正在保存站点配置，请等待回执…' }).waitFor(); assert.equal(await page.locator('.portal-settings').getAttribute('aria-busy'), 'true'); assert.equal(await save.isDisabled(), true); saveGate.release() }
      await submit('stale'); const stale = page.getByRole('alert').filter({ hasText: '记录已变化，请刷新确认。' }); await stale.waitFor(); assert.equal(await stale.evaluate(el => el === document.activeElement), true); assert.equal(await page.getByRole('textbox', { name: '站点操作原因', exact: true }).inputValue(), reason)
      await submit('lost'); const network = page.getByRole('alert').filter({ hasText: '网络连接中断，请按页面提示核对。' }); await network.waitFor(); assert.equal(await network.evaluate(el => el === document.activeElement), true)
      assert.equal(await page.getByRole('textbox', { name: '站点名称', exact: true }).isDisabled(), true); const count = writes.length
      if (width < 768) await activate(page, page.getByRole('button', { name: '打开导航菜单', exact: true }))
      const group = page.locator('[data-nav-group-trigger="customerPortal"]')
      assert.equal(await group.getAttribute('aria-expanded'), 'true', 'The current route group is already open')
      await activate(page, group, 'Space'); assert.equal(await group.getAttribute('aria-expanded'), 'false'); await page.getByRole('menuitem', { name: '站点设置', exact: true }).waitFor({ state: 'hidden' })
      await activate(page, group); await page.getByRole('menuitem', { name: '站点设置', exact: true }).waitFor({ state: 'visible' }); assert.equal(await group.getAttribute('aria-expanded'), 'true')
      assert.equal(await page.getByRole('menuitem', { name: '客户访问', exact: true }).count(), 0)
      assert.equal(await page.getByRole('menuitem', { name: '下单请求', exact: true }).count(), 0)
      const settingsMenuItem = page.getByRole('menuitem', { name: '站点设置', exact: true }); await observeClicks(settingsMenuItem); await activate(page, settingsMenuItem, 'Space'); assert.equal(await settingsMenuItem.getAttribute('data-qa-clicks'), '1', 'Expanded child Space emits exactly one native click')
      if (width === 1440) {
        await activate(page, page.getByRole('button', { name: '收起导航栏', exact: true })); await page.locator('.el-menu--collapse').waitFor(); assert.equal(await group.getAttribute('aria-expanded'), 'false')
        await activate(page, group); const first = page.getByRole('menuitem', { name: '商品目录', exact: true }); await first.waitFor({ state: 'visible' }); await waitFocused(page, first); assert.equal(await first.evaluate(el => el === document.activeElement), true, 'Collapsed Enter opens and focuses first item')
        await page.waitForFunction(() => { const el = document.activeElement, r = el?.getBoundingClientRect(); if (!r || !r.width || r.left < 0 || r.right > innerWidth || r.top < 0 || r.bottom > innerHeight) return false; const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return el === hit || el?.contains(hit) }); await page.screenshot({ path: output+'/collapsed-focus-'+width+'.png', fullPage: true }); const focusOutline = await first.evaluate(el => ({ style: getComputedStyle(el).outlineStyle, width: Number.parseFloat(getComputedStyle(el).outlineWidth) })); assert.equal(focusOutline.style, 'solid', 'Teleported keyboard item has a visible focus outline'); assert.ok(focusOutline.width >= 2)
        await page.keyboard.press('Escape'); assert.equal(await group.getAttribute('aria-expanded'), 'false'); assert.equal(await group.evaluate(el => el === document.activeElement), true, 'Escape returns to collapsed group')
        await page.keyboard.press('Space'); await first.waitFor({ state: 'visible' }); await waitFocused(page, first); assert.equal(await first.evaluate(el => el === document.activeElement), true); await page.keyboard.press('Tab'); assert.equal(await page.getByRole('menuitem', { name: '站点设置', exact: true }).evaluate(el => el === document.activeElement), true)
        await page.keyboard.press('Tab'); assert.equal(await group.getAttribute('aria-expanded'), 'false', 'Tab departure closes keyboard popup')
        await activate(page, group); await first.waitFor({ state: 'visible' }); await waitFocused(page, first); await page.keyboard.press('Tab'); await observeClicks(settingsMenuItem); await page.keyboard.press('Space'); assert.equal(await settingsMenuItem.getAttribute('data-qa-clicks'), '1', 'Collapsed child Space emits exactly one native click'); assert.equal(new URL(page.url()).pathname, '/portal/settings')
        await activate(page, page.getByRole('button', { name: '展开导航栏', exact: true })); await page.locator('.side-menu:not(.el-menu--collapse)').waitFor()
      }
      await activate(page, page.getByRole('menuitem', { name: '工作台', exact: true })); await page.getByText('请先核对站点保存结果。', { exact: true }).waitFor(); assert.equal(new URL(page.url()).pathname, '/portal/settings', 'Unknown save blocks route departure'); if (width < 768) await page.keyboard.press('Escape')
      const unloadDialog = page.waitForEvent('dialog'), reloadAttempt = page.reload({ timeout: 5000 }).then(() => false, () => true)
      const dialog = await unloadDialog; assert.equal(dialog.type(), 'beforeunload'); await dialog.dismiss(); assert.equal(await reloadAttempt, true, 'Unknown save cancels browser reload'); assert.equal(writes.length, count); assert.equal(await page.getByRole('textbox', { name: '站点名称', exact: true }).isDisabled(), true)
      mode = 'ready'; readFailure = true; await activate(page, reload); const readError = page.getByRole('alert').filter({ hasText: '站点配置暂不可用，请重试。' }); await readError.waitFor(); assert.equal(await readError.evaluate(el => el === document.activeElement), true); assert.equal(await page.getByRole('textbox', { name: '站点名称', exact: true }).isDisabled(), true)
      await activate(page, reload); const recovered = page.getByRole('alert').filter({ hasText: '已读取当前配置并放弃本地草稿' }); await recovered.waitFor(); assert.equal(await recovered.evaluate(el => el === document.activeElement), true); assert.equal(writes.length, count); assert.equal(await page.getByRole('textbox', { name: '站点名称', exact: true }).inputValue(), name); assert.equal(await confirm.isChecked(), false)
      await type(page, page.getByRole('textbox', { name: '站点操作原因', exact: true }), reason); await activate(page, confirm, 'Space'); await submit('success')
      const saved = page.getByRole('alert').filter({ hasText: '站点配置已保存。客户访问仍受部署功能开关、账号、目录与价格等条件共同控制。' }); await saved.waitFor(); assert.equal(await saved.evaluate(el => el === document.activeElement), true, 'Successful save notice receives focus'); assert.equal(await confirm.isChecked(), false)
      await type(page, page.getByRole('textbox', { name: '站点操作原因', exact: true }), reason); await activate(page, confirm, 'Space'); await submit('denied-save'); const denied = page.getByRole('alert').filter({ hasText: '当前员工无此操作权限。' }); await denied.waitFor(); assert.equal(await denied.evaluate(el => el === document.activeElement), true); assert.equal(await page.getByRole('textbox', { name: '站点名称', exact: true }).count(), 0, 'Save authorization failure clears private settings')
      mode = 'ready'; await activate(page, reload); await page.getByRole('textbox', { name: '站点名称', exact: true }).waitFor(); mode='denied'; await activate(page, reload); await denied.waitFor(); assert.equal(await denied.evaluate(el => el === document.activeElement), true); assert.equal(await page.getByRole('textbox', { name: '站点名称', exact: true }).count(), 0)
      assert.equal(writes.length, 4); await bounds(page)
      // Add one external-link permission only after the site-only isolation checks.
      mode = 'ready'; navigationPermissions = ['portal_site:admin', 'festival:read']
      await context.route(origin+'/festival/', route => route.fulfill({ contentType: 'text/html', body: '<title>Synthetic destination</title><p>Keyboard destination</p>' }))
      await page.reload(); await page.getByRole('textbox', { name: '站点名称', exact: true }).waitFor()
      if (width < 768) await activate(page, page.getByRole('button', { name: '打开导航菜单', exact: true }))
      const invoiceGroup = page.locator('[data-nav-group-trigger="invoice"]'), external = page.getByRole('link', { name: '采购节看板', exact: true })
      await activate(page, invoiceGroup); await external.waitFor({ state: 'visible' })
      await reach(page, external); const popupPromise = context.waitForEvent('page'); await page.keyboard.press('Enter'); const popup = await popupPromise; await popup.waitForURL(origin+'/festival/'); await popup.close(); assert.equal(new URL(page.url()).pathname, '/portal/settings')
      if (width === 1440) {
        await activate(page, page.getByRole('button', { name: '收起导航栏', exact: true })); await page.locator('.el-menu--collapse').waitFor()
        await activate(page, invoiceGroup); await external.waitFor({ state: 'visible' }); assert.equal(await external.evaluate(el => el === document.activeElement), true)
        const collapsedPopupPromise = context.waitForEvent('page'); await page.keyboard.press('Enter'); const collapsedPopup = await collapsedPopupPromise; await collapsedPopup.waitForURL(origin+'/festival/'); await collapsedPopup.close()
        await page.keyboard.press('Escape'); assert.equal(await invoiceGroup.getAttribute('aria-expanded'), 'false'); assert.equal(await invoiceGroup.evaluate(el => el === document.activeElement), true)
        await activate(page, page.getByRole('button', { name: '展开导航栏', exact: true }))
      } else await page.keyboard.press('Escape')
      assert.deepEqual(errors, []); assert.equal(writes.length, 4); await bounds(page); assert.ok(blockedExternal.some(url => new URL(url).hostname === 'fonts.googleapis.com'), 'Actual font stylesheet request failed during usable keyboard flows')
      results.push({ width, keyboard: true, unknownBeforeUnload: true, collapsedNavigation: width === 1440, nativeExternalEnter: true, blockedFontRequests: blockedExternal.filter(url => new URL(url).hostname === 'fonts.googleapis.com').length, lengths: { name: name.length, termCode: termCode.length, termText: termText.length, contactName: contactName.length, email: email.length, whatsapp: whatsapp.length, reason: reason.length }, simulatedWriteAttempts: writes.length, pageErrors: errors.length })
    } catch (error) { await page.screenshot({ path: output+'/failure-'+width+'.png', fullPage: true }); await writeFile(output+'/failure-'+width+'.json', JSON.stringify(await page.evaluate(() => ({ active: document.activeElement?.outerHTML?.slice(0,700), text: document.querySelector('.portal-settings')?.innerText, navigation: document.querySelector('.side-menu')?.outerHTML, navigationTrace: window.qaNavTrace, controls: [...document.querySelectorAll('.portal-settings input')].map(el => ({ role: el.getAttribute('role'), label: el.getAttribute('aria-label'), type: el.type })) })), null, 2)); throw error }
    finally { readGate.release(); saveGate?.release(); await context.close() }
  }
  const result = { status: 'pass', motion, scope: 'Built employee UI with intercepted synthetic authentication/settings. No real backend, settings persistence or authorization proof.', results }
  await writeFile(output+'/result.json', JSON.stringify(result,null,2)); console.log(JSON.stringify(result))
} finally { await browser.close() }
