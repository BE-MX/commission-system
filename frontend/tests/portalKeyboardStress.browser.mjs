import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3211', output = process.env.PORTAL_QA_OUTPUT
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/); assert.ok(output)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const uuid = n => `${n}1111111-1111-4111-8111-111111111111`, results = []
function gate() { let release; const waiting = new Promise(resolve => { release = resolve }); return { waiting, release } }
async function reach(page, locator, reverse = false) {
  await locator.waitFor({ state: 'attached' })
  for (let i = 0; i < 100; i++) {
    if (await locator.evaluate(el => document.activeElement === el)) return
    await page.keyboard.press(reverse ? 'Shift+Tab' : 'Tab')
  }
  throw new Error(`Unreachable by keyboard: ${await locator.evaluate(el => el.outerHTML)}`)
}
async function activate(page, locator, key = 'Enter') { await reach(page, locator); await page.keyboard.press(key) }
async function type(page, locator, value) { await reach(page, locator); await page.keyboard.press('Control+A'); await page.keyboard.type(value); await page.keyboard.press('Tab') }
async function geometry(page, dialog, label) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${label}: root overflow`)
  const bad = await dialog.evaluate(el => {
    const bad = [], d = el.getBoundingClientRect()
    if (d.left < -1 || d.right > innerWidth + 1 || d.top < -1 || d.bottom > innerHeight + 1 || el.scrollWidth > el.clientWidth + 1) bad.push(`dialog [${d.left},${d.right},${d.top},${d.bottom}] scroll ${el.scrollWidth}/${el.clientWidth}`)
    for (const field of el.querySelectorAll('input, textarea, .el-dialog__footer button')) {
      const r = field.getBoundingClientRect()
      if (!r.width || !r.height) continue
      if (r.left < d.left - 1 || r.right > d.right + 1) bad.push(`horizontal ${field.getAttribute('aria-label') || field.tagName}: ${r.left}/${r.right}`)
      if (field.closest('.el-dialog__footer') && (r.top < d.top || r.bottom > d.bottom + 1)) bad.push('footer outside dialog')
    }
    return bad
  })
  assert.deepEqual(bad, [], label)
}
try {
  for (const width of [1440, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 950 }, reducedMotion: 'reduce' })
    await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-keyboard-only'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
    const page = await context.newPage(), errors = [], calls = [], shellPaths = [], blockedExternal = []
    page.on('pageerror', error => errors.push(error.message))
    await context.route('**/*', route => { const url = new URL(route.request().url()); if (url.origin === origin) return route.continue(); blockedExternal.push(url.origin); return route.abort() })
    const model = 'SignatureWeft'.repeat(10).slice(0, 128), color = 'ChampagnePearl'.repeat(10).slice(0, 128), address = 'LongAddress'.repeat(19).slice(0, 200)
    const display = id => ({ item_id: id, model_name: model, color_name: color, customer_sku: 'GW'.repeat(32), length: '22 in', weight: '25 g', unit: 'pack' })
    const line = { line_key: uuid(8), quantity: 4, display_snapshot: display(uuid(2)), unit_price: '35.2750', discount_amount: '0.00', line_amount: '141.10' }
    const order = { request_id: uuid(1), request_no: 'REQ-KEYBOARD-STAFF-001', row_version: 1, status: 'submitted', customer_po: 'P'.repeat(80), submitted_at: '2026-10-04T10:00:00+08:00', currency: 'USD', product_amount: '141.10', total_amount: null, items: [line], fees: { status: 'pending', shipping_amount: null, packaging_amount: null, surcharge_amount: null, surcharge_name: '' }, delivery: { contact_name: 'Keyboard buyer', phone: '+44 123456', address_line1: address, address_line2: '', city: 'London', country_code: 'GB', region: '', postal_code: '' }, payment_terms_snapshot: { code: 'prepay', display_text: 'Full payment before dispatch', deposit_percent: '100.00' }, remark: 'R'.repeat(1000), customer_safe_timeline: [] }
    let reviewGate = gate(), catalogGate = gate(), previewGate, commandGate, previewFailure = true, approved = false, proposalSent, approvalAttempts = 0
    const send = (route, data, status = 200, message = 'OK') => route.fulfill({ status, json: { code: status, message, data } })
    await context.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname, body = request.postDataJSON()
      if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Keyboard employee', roles: ['sales'], permissions: ['portal_order:read', 'portal_order:write', 'invoice:write'] } })
      if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-keyboard-only' } })
      if (!path.startsWith('/api/portal/')) { shellPaths.push(path); return send(route, {}) }
      calls.push({ path, body, version: request.headers()['if-match'], method: request.method() })
      if (path.endsWith('/orders')) return send(route, { items: [order], total: 1 })
      if (path.endsWith('/orders/' + order.request_id)) return send(route, order)
      if (path.endsWith('/review')) {
        await reviewGate.waiting
        return send(route, { order, quantity_rules: order.items.map(item => ({ item_id: item.display_snapshot.item_id, min_order_qty: 3, step_qty: 2 })), standard_lines: order.items.map(item => ({ line_key: item.line_key, product_id: item.display_snapshot.item_id === uuid(2) ? '101' : '102', sku_id: item.display_snapshot.item_id === uuid(2) ? '201' : '202', standard: { model: 'Standard Weft', color: item.display_snapshot.item_id === uuid(2) ? '1' : '2' } })), customer: { customer_id: '101', okki_company_id: '501', sales_user_id: '5', company_name: 'C'.repeat(100) }, available_actions: approved ? [] : order.status === 'ready_for_review' ? ['approve', 'propose', 'reject'] : ['propose', 'reject'], policy: { payment_terms: [order.payment_terms_snapshot], proposal_valid_hours: [24, 48], default_payment_term_code: 'prepay' } })
      }
      if (path.endsWith('/proposal-catalog')) { await catalogGate.waiting; return send(route, { request_id: order.request_id, row_version: 1, items: [{ item_id: uuid(3), display_snapshot: display(uuid(3)), standard: { model: 'Standard Weft', color: '2' }, product_id: '102', sku_id: '202', min_order_qty: 3, step_qty: 2, sale_unit: 'pack' }], total: 1 }) }
      if (path.endsWith('/proposal-preview')) {
        await previewGate.waiting
        if (previewFailure) return send(route, { error_code: 'INVENTORY_UNAVAILABLE' }, 503, '暂时无法核验库存，请重试。')
        assert.equal(request.headers()['if-match'], '"1"')
        const lines = body.items.map(item => ({ ...item, display_snapshot: display(item.item_id), unit_price: '35.2750', discount_amount: '0.00', line_amount: item.quantity === 6 ? '211.65' : '141.10' }))
        return send(route, { request_id: order.request_id, row_version: 1, currency: 'USD', binding: false, requires_customer_acceptance: true, items: lines, changes: lines.map(item => ({ item_id: item.item_id, kind: item.item_id === uuid(2) ? 'changed' : 'added', changed_fields: ['quantity'], before: item.item_id === uuid(2) ? line : null, after: item })), product_amount: '352.75', previous_product_amount: '141.10', total_amount: '377.75', previous_total_amount: null, fees: body.fees, previous_fees: order.fees, payment_terms_snapshot: order.payment_terms_snapshot, previous_payment_terms_snapshot: order.payment_terms_snapshot, valid_for_hours: 48, calculated_at: '2026-10-04T10:01:00+08:00' })
      }
      if (path.endsWith('/proposals')) {
        await commandGate.waiting
        assert.equal(request.headers()['if-match'], '"1"'); assert.deepEqual(body.items, [{ item_id: uuid(2), quantity: 6 }, { item_id: uuid(3), quantity: 4 }]); assert.equal(body.delivery.address_line1, address); assert.equal(body.fees.shipping_amount, '25.00'); assert.equal(body.valid_for_hours, 48); assert.equal(body.reason.length, 500); assert.equal(body.customer_po.length, 80)
        proposalSent = structuredClone(body); order.status = 'awaiting_customer'; order.row_version = 2
        return send(route, { original_receipt: { request_id: order.request_id, row_version: 2 }, current_state: order.status, row_version: 2 })
      }
      if (path.endsWith('/approve')) {
        await commandGate.waiting; approvalAttempts++
        assert.equal(request.headers()['if-match'], '"3"'); assert.deepEqual(body, { accepted_revision_id: uuid(7) })
        if (approvalAttempts === 1) return route.abort('failed')
        approved = true; order.status = 'invoice_created'; order.row_version = 4
        return send(route, { replayed: true, original_receipt: { request_id: order.request_id, row_version: 4 }, current_state: order.status, row_version: 4 })
      }
      throw new Error(`Unexpected business API ${request.method()} ${path}`)
    })
    try {
      await page.goto(origin + '/portal/orders')
      await activate(page, page.getByRole('button', { name: '详情', exact: true }))
      const process = page.getByRole('button', { name: '处理请求', exact: true })
      await activate(page, process)
      const dialog = page.getByRole('dialog', { name: '处理客户下单请求', exact: true })
      await dialog.waitFor(); assert.equal(await dialog.getByRole('button', { name: '确认操作', exact: true }).isDisabled(), true)
      await dialog.getByRole('status').filter({ hasText: '正在读取当前请求条款…' }).waitFor(); reviewGate.release(); await dialog.getByText('当前版本完整条款', { exact: true }).waitFor()
      await geometry(page, dialog, `long review ${width}`)
      await activate(page, dialog.getByRole('radio', { name: '发送确认提案', exact: true }), 'Space')
      const quantity = dialog.getByRole('spinbutton', { name: '商品数量', exact: true }).first()
      await reach(page, quantity); await page.keyboard.press('ArrowUp'); await page.keyboard.press('Tab')
      assert.equal(await quantity.inputValue(), '6')
      await activate(page, dialog.getByRole('button', { name: '新增授权商品', exact: true }))
      await dialog.locator('.proposal-catalog-picker').waitFor(); await dialog.getByRole('status').filter({ hasText: '正在读取客户授权商品…' }).waitFor()
      catalogGate.release()
      await activate(page, dialog.getByRole('button', { name: `添加商品 ${model} ${color}`, exact: true }))
      assert.equal(await dialog.getByRole('spinbutton', { name: '商品数量', exact: true }).nth(1).inputValue(), '4')
      await activate(page, dialog.getByRole('button', { name: '收起授权目录', exact: true }))
      for (const [label, value] of [['运费（USD）', '25.00'], ['包装费（USD）', '0.00'], ['附加费（USD）', '0.00'], ['操作原因', 'P'.repeat(500)]]) await type(page, dialog.getByLabel(label, { exact: true }), value)
      const expiry = dialog.getByRole('combobox', { name: '有效期（小时）', exact: true })
      await reach(page, expiry); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter')
      const preview = dialog.getByRole('button', { name: '预览金额与变化', exact: true })
      await type(page, dialog.getByLabel('运费（USD）', { exact: true }), '25')
      await activate(page, preview)
      const formError = dialog.getByRole('alert').filter({ hasText: '请明确填写每项费用' })
      await formError.waitFor()
      assert.equal(await formError.evaluate(el => el === document.activeElement), true, 'field validation must focus the error summary')
      assert.equal(await dialog.getByLabel('运费（USD）', { exact: true }).getAttribute('aria-invalid'), 'true'); assert.equal(await dialog.getByLabel('运费（USD）', { exact: true }).getAttribute('aria-describedby'), 'portal-review-error')
      assert.equal(calls.filter(call => call.path.endsWith('/proposal-preview')).length, 0)
      await type(page, dialog.getByLabel('运费（USD）', { exact: true }), '26')
      await activate(page, preview)
      assert.equal(await formError.evaluate(el => el === document.activeElement), true, 'repeated equal validation error must refocus the summary')
      assert.equal(calls.filter(call => call.path.endsWith('/proposal-preview')).length, 0)
      await type(page, dialog.getByLabel('运费（USD）', { exact: true }), '25.00')
      previewGate = gate(); await activate(page, preview)
      await dialog.getByRole('status').filter({ hasText: '正在核验当前价格和库存…' }).waitFor(); assert.equal(await preview.getAttribute('aria-busy'), 'true'); assert.equal(await preview.isDisabled(), true)
      previewGate.release()
      const sourceError = dialog.getByRole('alert').filter({ hasText: '暂时无法核验库存，请重试。' })
      await sourceError.waitFor(); assert.equal(await sourceError.evaluate(el => el === document.activeElement), true)
      assert.equal(await dialog.getByLabel('地址', { exact: true }).inputValue(), address)
      previewFailure = false; previewGate = gate(); await activate(page, preview); previewGate.release()
      await dialog.getByText('提案金额与变更预览', { exact: true }).waitFor()
      const confirmation = dialog.getByRole('checkbox', { name: '我已核对内容，确认发送确认提案', exact: true })
      await activate(page, confirmation, 'Space')
      await geometry(page, dialog, `prepared ${width}`)
      await page.screenshot({ path: `${output}/proposal-${width}.png`, fullPage: true })
      commandGate = gate(); await activate(page, dialog.getByRole('button', { name: '确认操作', exact: true }))
      await dialog.getByRole('status').filter({ hasText: '正在提交操作，请等待回执…' }).waitFor(); assert.equal(await dialog.getByRole('button', { name: '确认操作', exact: true }).getAttribute('aria-busy'), 'true')
      commandGate.release(); await dialog.waitFor({ state: 'hidden' })
      assert.ok(proposalSent)
      // Customer acceptance is simulated here; its actual keyboard path is tested separately.
      order.status = 'ready_for_review'; order.row_version = 3; order.total_amount = '377.75'; order.fees = proposalSent.fees; order.product_amount = '352.75'; order.items = proposalSent.items.map(item => ({ ...line, line_key: item.item_id === uuid(2) ? uuid(8) : uuid(9), quantity: item.quantity, line_amount: item.quantity === 6 ? '211.65' : '141.10', display_snapshot: display(item.item_id) })); order.proposal = { revision_id: uuid(7), accepted: true, expired: false, expires_at: new Date(Date.now() + 600000).toISOString() }
      await activate(page, process)
      await dialog.getByRole('radio', { name: '审核并生成正式 PI', exact: true }).waitFor()
      assert.match(await dialog.locator('.review-snapshot').innerText(), /商品 ID 101 \/ SKU ID 201/); assert.match(await dialog.locator('.review-snapshot').innerText(), /商品 ID 102 \/ SKU ID 202/); assert.match(await dialog.locator('.review-snapshot').innerText(), /商品 352.75/); assert.match(await dialog.locator('.review-snapshot').innerText(), /行金额 211.65/);
      await activate(page, dialog.getByRole('radio', { name: '审核并生成正式 PI', exact: true }), 'Space')
      await activate(page, dialog.getByRole('checkbox', { name: '我已核对内容，确认审核并生成正式 PI', exact: true }), 'Space')
      commandGate = gate(); await activate(page, dialog.getByRole('button', { name: '确认操作', exact: true })); commandGate.release()
      const retry = dialog.getByRole('button', { name: '重试原命令', exact: true })
      await retry.waitFor(); assert.equal(await dialog.getByRole('button', { name: '关闭', exact: true }).isDisabled(), true); assert.equal(await dialog.locator('.el-dialog__body > div').getAttribute('aria-busy'), null)
      await page.keyboard.press('Escape'); assert.equal(await dialog.isVisible(), true)
      await geometry(page, dialog, `unknown approval ${width}`)
      await page.screenshot({ path: `${output}/approval-${width}.png`, fullPage: true })
      await activate(page, retry); await dialog.waitFor({ state: 'hidden' })
      assert.equal(approvalAttempts, 2)
      const approvals = calls.filter(call => call.path.endsWith('/approve'))
      assert.deepEqual(approvals[0], approvals[1]); assert.equal(calls.filter(call => call.path.endsWith('/proposals')).length, 1)
      assert.deepEqual(errors, [])
      results.push({ width, keyboard: 'details/process/radio/quantity/add/fees/expiry/validation recovery/preview503 recovery/explicit consent/send/approve/unknown exact retry', longLengths: { model: model.length, color: color.length, sku: 64, address: address.length, reason: 500, remark: 1000, po: 80 }, apiCalls: calls.length, shellPaths, blockedExternal: [...new Set(blockedExternal)], scope: 'Built employee UI, synthetic JWT/bootstrap, intercepted APIs, simulated customer acceptance and PI creation; no real backend' })
    } catch (error) { await page.screenshot({ path: `${output}/failure-${width}.png`, fullPage: true }); throw error }
    finally { reviewGate.release(); catalogGate.release(); previewGate?.release(); commandGate?.release(); await context.close() }
  }
  await writeFile(`${output}/result.json`, JSON.stringify({ status: 'pass', results }, null, 2)); console.log(JSON.stringify({ status: 'pass', results, output }))
} finally { await browser.close() }
