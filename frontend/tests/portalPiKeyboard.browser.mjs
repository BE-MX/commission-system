import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3211', output = process.env.PORTAL_QA_OUTPUT
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/); assert.ok(output); await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const id = '11111111-1111-4111-8111-111111111111', revision = '22222222-2222-4222-8222-222222222222', results = []
function gate() { let release; const waiting = new Promise(resolve => { release = resolve }); return { waiting, release } }
async function reach(page, locator) {
  await locator.waitFor({ state: 'attached' })
  for (let index = 0; index < 100; index++) { if (await locator.evaluate(el => document.activeElement === el)) return; await page.keyboard.press('Tab') }
  throw new Error(`Unreachable: ${await locator.evaluate(el => el.outerHTML)}`)
}
async function activate(page, locator, key = 'Enter') { await reach(page, locator); await page.keyboard.press(key) }
async function bounds(page, dialog, label) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, label + ' root overflow')
  const bad = await dialog.evaluate(el => {
    const d = el.getBoundingClientRect(), problems = []
    if (d.left < -1 || d.right > innerWidth + 1 || d.top < -1 || d.bottom > innerHeight + 1 || el.scrollWidth > el.clientWidth + 1) problems.push(`dialog:${el.scrollWidth}/${el.clientWidth}`)
    for (const field of el.querySelectorAll('.pi-document, .pi-fields, .pi-fields dt, .pi-fields dd, .totals dt, .totals dd, .delivery dt, .delivery dd, input, textarea, .el-dialog__footer button')) {
      const r = field.getBoundingClientRect(); if (!r.width || !r.height) continue
      if (r.left < d.left - 1 || r.right > d.right + 1) problems.push(`horizontal ${field.className || field.tagName}:${r.left}/${r.right}`)
      if (field.matches('.el-dialog__footer button') && (r.top < d.top || r.bottom > d.bottom + 1)) problems.push('footer outside')
    }
    return problems
  })
  assert.deepEqual(bad, [], label)
}
try {
  for (const width of [1440, 390, 320]) for (const mode of ['propose', 'publish', 'void', 'blocked', 'denied']) {
    const context = await browser.newContext({ viewport: { width, height: 950 }, reducedMotion: 'reduce' })
    await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-pi-keyboard'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
    const page = await context.newPage(), errors = [], calls = [], blocked = [], reviewGate = gate(); let commandGate, readAttempt = 0, attempts = 0
    page.on('pageerror', error => errors.push(error.message))
    await context.route('**/*', route => { if (new URL(route.request().url()).origin === origin) return route.continue(); blocked.push(new URL(route.request().url()).origin); return route.abort() })
    const model = 'SignatureWeft'.repeat(10).slice(0, 128), color = 'ChampagnePearl'.repeat(10).slice(0, 128), address = 'LongAddress'.repeat(19).slice(0, 200), surcharge = 'HandlingFee'.repeat(10).slice(0, 100)
    const doc = { commercial_header: { invoice_no: 'PI-KBD-20261004', customer_name: 'C'.repeat(100), invoice_date: '2026-10-04', express_channel: 'DHL', contact_email: 'buyer@example.test', sales_user_name: 'Synthetic seller', sales_phone: '123456', sales_email: 'sales@example.test', packaging_quantity: '2' }, currency: 'USD', product_amount: '100.00', total_amount: '130.00', fees: { status: 'confirmed', shipping_amount: '25.00', packaging_amount: '0.00', surcharge_amount: '5.00', surcharge_name: surcharge }, payment_terms_snapshot: { display_text: 'T'.repeat(256), deposit_percent: '100.00' }, delivery: { contact_name: 'Keyboard buyer', phone: '123456', address_line1: address, address_line2: address, city: 'London', country_code: 'GB' }, remark: 'R'.repeat(1000), items: [{ line_key: 'line1', product_id: '101', sku_id: '201', display_snapshot: { model_name: model, color_name: color, customer_sku: 'GW'.repeat(32), length: '22 in', weight: '25 g', unit: 'pack' }, quantity: 2, unit_price: '50.0000', discount_amount: '0.00', line_amount: '100.00' }] }
    const historical = { ...structuredClone(doc), invoice_document_version: 1, total_amount: '125.00', commercial_header: { ...doc.commercial_header, customer_name: 'Historical buyer' }, fees: { ...doc.fees, shipping_amount: '20.00' } }
    const proposal = mode === 'publish' ? { ...structuredClone(doc), revision_id: revision, bound_invoice_document_version: 2, expired: false, expires_at: '2026-10-05T10:00:00+08:00' } : null
    const order = { ...historical, request_id: id, request_no: 'REQ-PI-KEYBOARD', status: 'invoice_created', row_version: 8, submitted_at: '2026-10-04T08:00:00+08:00', pi_amendment: { status: 'withdrawn' }, customer_safe_timeline: [] }
    const send = (route, data, status = 200, message = 'OK') => route.fulfill({ status, json: { code: status, message, data } })
    await context.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic employee', roles: ['sales'], permissions: ['portal_order:read', 'portal_order:write', 'invoice:write'] } })
      if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-pi-keyboard' } })
      if (!path.startsWith('/api/portal/')) return send(route, {})
      if (path.endsWith('/orders')) return send(route, { items: [order], total: 1 })
      if (path.endsWith('/orders/' + id)) return send(route, order)
      if (path.endsWith('/pi-review')) {
        await reviewGate.waiting; readAttempt++
        if (mode === 'denied') return send(route, {}, 404, '原 PI 不在当前处理范围。')
        if (mode === 'propose' && readAttempt === 1) return send(route, {}, 503, '暂时无法读取 PI，请重试。')
        return send(route, { request_id: id, request_no: order.request_no, row_version: 8, invoice_id: '90', invoice_document_version: 2, invoice_status: 'ready', amendment_status: mode === 'publish' ? 'accepted' : 'withdrawn', customer: { company_name: 'C'.repeat(100), customer_id: '10', okki_company_id: '20', sales_user_id: '5', invoice_sales_user_id: '6' }, current_invoice: doc, last_published: historical, proposal, available_actions: mode === 'blocked' ? [] : [mode === 'publish' ? 'publish_pi' : mode === 'void' ? 'void_pi' : 'propose_pi'], blocked_reasons: mode === 'blocked' ? [{ code: 'PI_VOID_REQUIRES_REVIEW', message: 'PI 已有出库记录，须先核对。' }] : [], policy: { proposal_valid_hours: [24, 48] } })
      }
      if (request.method() === 'POST' && /\/(pi-proposals|publish-pi|void-pi)$/.test(path)) {
        await commandGate.waiting
        const call = { path, body: request.postDataJSON(), version: request.headers()['if-match'] }; calls.push(call); attempts++
        assert.equal(call.version, '"8"'); assert.equal(call.body.invoice_document_version, 2)
        if (mode === 'publish') assert.deepEqual(call.body, { invoice_document_version: 2, accepted_revision_id: revision })
        else assert.deepEqual(call.body, { invoice_document_version: 2, reason: 'P'.repeat(500), ...(mode === 'propose' ? { valid_for_hours: 48 } : {}) })
        if (attempts === 1) return route.abort('failed')
        return send(route, { replayed: true, original_receipt: { request_id: id, invoice_document_version: 2 }, current_state: 'invoice_created', row_version: 9 })
      }
      throw new Error(`Unexpected ${request.method()} ${path}`)
    })
    try {
      await page.goto(origin + '/portal/orders'); await activate(page, page.getByRole('button', { name: '详情', exact: true })); await activate(page, page.getByRole('button', { name: '处理原 PI', exact: true }))
      const dialog = page.getByRole('dialog', { name: '处理原 PI', exact: true }); await dialog.waitFor(); assert.equal(await dialog.getByRole('button', { name: '确认 PI 操作', exact: true }).isDisabled(), true)
      await dialog.getByRole('status').filter({ hasText: '正在读取原 PI 条款…' }).waitFor()
      reviewGate.release()
      if (mode === 'denied') {
        const error = dialog.getByRole('alert').filter({ hasText: '原 PI 不在当前处理范围。' }); await error.waitFor(); assert.equal(await error.evaluate(el => el === document.activeElement), true)
        assert.equal(await dialog.locator('.pi-document').count(), 0); assert.equal(await dialog.getByRole('radio').count(), 0)
        await activate(page, dialog.getByRole('button', { name: '关闭', exact: true })); await dialog.waitFor({ state: 'hidden' })
      } else {
        if (mode === 'propose') {
          const error = dialog.getByRole('alert').filter({ hasText: '暂时无法读取 PI，请重试。' }); await error.waitFor()
          assert.equal(await error.evaluate(el => el === document.activeElement), true)
          await activate(page, dialog.getByRole('button', { name: '刷新 PI', exact: true }))
        }
        const current = dialog.getByRole('tabpanel', { name: '当前方舟 PI', exact: true }); await current.locator('.pi-document').waitFor(); await bounds(page, dialog, `${width}/${mode} current`)
        const cdp = await context.newCDPSession(page); await cdp.send('DOM.enable'); await cdp.send('CSS.enable'); const { root } = await cdp.send('DOM.getDocument'); const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: '.portal-pi-dialog .pi-document article strong' }); const font = await cdp.send('CSS.getPlatformFontsForNode', { nodeId }); assert.ok(font.fonts.some(f => !f.isCustomFont && f.glyphCount > 0)); await cdp.detach()
        await reach(page, current.locator('.pi-document')); await page.keyboard.press('PageDown'); await page.keyboard.press('End')
        await page.waitForFunction(() => {
          const body = document.querySelector('.portal-pi-dialog .el-dialog__body')
          return body && body.scrollTop + body.clientHeight >= body.scrollHeight - 1
        }, undefined, { timeout: 3000 })
        const scroll = await dialog.locator('.el-dialog__body').evaluate(el => ({ top: el.scrollTop, height: el.clientHeight, total: el.scrollHeight }))
        assert.ok(scroll.top + scroll.height >= scroll.total - 1, `${width}/${mode} keyboard must read to the body bottom`)
        await bounds(page, dialog, `${width}/${mode} after keyboard scroll`)
        await reach(page, dialog.getByRole('tab', { name: '当前方舟 PI', exact: true })); await page.keyboard.press('ArrowRight'); await page.keyboard.press('Enter')
        await dialog.getByRole('tabpanel', { name: '最近发布历史快照', exact: true }).getByText('Historical buyer', { exact: true }).waitFor(); await bounds(page, dialog, `${width}/${mode} historical`)
        if (mode === 'publish') { await page.keyboard.press('ArrowRight'); await page.keyboard.press('Enter'); await dialog.getByRole('tabpanel', { name: '客户修改提案', exact: true }).locator('.pi-document').waitFor(); await bounds(page, dialog, `${width}/${mode} proposal`); await page.keyboard.press('ArrowLeft') }
        await page.keyboard.press('ArrowLeft'); await page.keyboard.press('Enter'); await current.waitFor()
        if (mode === 'blocked') { await dialog.getByText('PI 已有出库记录，须先核对。', { exact: true }).waitFor(); assert.equal(await dialog.getByRole('radio').count(), 0); await activate(page, dialog.getByRole('button', { name: '关闭', exact: true })); await dialog.waitFor({ state: 'hidden' }) }
        else {
          const label = mode === 'publish' ? '发布已确认 PI' : mode === 'void' ? '作废未流转 PI' : '发送 PI 修改提案'
          await activate(page, dialog.getByRole('radio', { name: label, exact: true }), 'Space')
          const confirmation = dialog.getByRole('checkbox'), button = dialog.getByRole('button', { name: '确认 PI 操作', exact: true })
          if (mode !== 'publish') {
            await activate(page, confirmation, 'Space'); await activate(page, button)
            const error = dialog.getByRole('alert').filter({ hasText: '请填写 1–500 字的操作原因。' }); await error.waitFor(); assert.equal(await error.evaluate(el => el === document.activeElement), true)
            await activate(page, button); assert.equal(await error.evaluate(el => el === document.activeElement), true); assert.equal(calls.length, 0)
            const reason = dialog.getByLabel('操作原因', { exact: true }); assert.equal(await reason.getAttribute('aria-invalid'), 'true'); await reach(page, reason); await page.keyboard.type('P'.repeat(500)); await page.keyboard.press('Tab'); assert.equal(await confirmation.isChecked(), false)
            if (mode === 'propose') { await reach(page, dialog.getByRole('combobox', { name: '提案有效期（小时）', exact: true })); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter') }
          }
          await activate(page, confirmation, 'Space'); await bounds(page, dialog, `${width}/${mode} prepared`)
          commandGate = gate(); await activate(page, button); await dialog.getByRole('status').filter({ hasText: '正在提交 PI 操作，请等待回执…' }).waitFor(); assert.equal(await button.isDisabled(), true); commandGate.release()
          const retry = dialog.getByRole('button', { name: '重试原命令', exact: true }); await retry.waitFor();
          const networkError = dialog.getByRole('alert').filter({ hasText: '网络连接中断，请按页面提示重试。' }); await networkError.waitFor(); assert.equal(await networkError.evaluate(el => el === document.activeElement), true); assert.equal(await dialog.getByRole('button', { name: '关闭', exact: true }).isDisabled(), true); assert.equal(await dialog.locator('.el-dialog__body > div').getAttribute('aria-busy'), null)
          await page.keyboard.press('Escape'); assert.equal(await dialog.isVisible(), true); await bounds(page, dialog, `${width}/${mode} uncertain`); await page.screenshot({ path: `${output}/${mode}-${width}.png`, fullPage: true })
          await activate(page, retry); await dialog.waitFor({ state: 'hidden' }); assert.equal(attempts, 2); assert.deepEqual(calls[0], calls[1])
        }
        results.push({ width, mode, font: font.fonts, scroll, attempts, keyboard: true, blockedExternal: [...new Set(blocked)], scope: 'Built employee UI, synthetic JWT/bootstrap, intercepted APIs and simulated PI command receipts; no real backend' })
      }
      await page.getByRole('button', { name: '处理原 PI', exact: true }).waitFor()
      await page.waitForFunction(() => document.activeElement?.tagName === 'BUTTON' && document.activeElement.textContent.trim() === '处理原 PI', undefined, { timeout: 3000 })
      await bounds(page, page.locator('.detail-drawer:visible'), width + '/' + mode + ' returned detail')
      assert.deepEqual(errors, []); if (mode === 'denied') results.push({ width, mode, attempts, keyboard: true })
    } catch (error) { await writeFile(output + '/failure-' + mode + '-' + width + '.json', JSON.stringify(await page.evaluate(() => ({ active: document.activeElement?.outerHTML, buttons: [...document.querySelectorAll('button')].filter(el => el.offsetWidth).map(el => el.textContent.trim()) })), null, 2)); await page.screenshot({ path: `${output}/failure-${mode}-${width}.png`, fullPage: true }); throw error }
    finally { reviewGate.release(); commandGate?.release(); await context.close() }
  }
  await writeFile(`${output}/result.json`, JSON.stringify({ status: 'pass', results }, null, 2)); console.log(JSON.stringify({ status: 'pass', scenarios: results.length, output }))
} finally { await browser.close() }
