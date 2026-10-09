import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3211', output = process.env.PORTAL_QA_OUTPUT
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/); assert.ok(output); await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true }), results = []
const uuid = n => `${n.toString(16).padStart(8, '0')}-1111-4111-8111-111111111111`, accessId = uuid(1)
function gate() { let release; const waiting = new Promise(resolve => { release = resolve }); return { waiting, release } }
async function reach(page, target) { await target.waitFor({ state: 'attached' }); for (let n = 0; n < 120; n++) { if (await target.evaluate(el => el === document.activeElement)) return; await page.keyboard.press('Tab') }; throw new Error('Unreachable ' + await target.evaluate(el => el.outerHTML)) }
async function activate(page, target, key = 'Enter') { await reach(page, target); await page.keyboard.press(key) }
async function type(page, target, value) { await reach(page, target); await page.keyboard.press('Control+A'); await page.keyboard.press('Backspace'); await page.keyboard.type(value); await page.keyboard.press('Tab') }
async function source(page, dialog, text) { const target = dialog.locator('.mapping-add .el-form-item').nth(1).locator('input').last(); await reach(page, target); await page.keyboard.press('Control+A'); await page.keyboard.type(text); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter'); await page.keyboard.press('Tab') }
async function bounds(page, dialog) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  const bad = await dialog.evaluate(el => { const d = el.getBoundingClientRect(), bad = []; if (d.left < -1 || d.right > innerWidth + 1 || d.top < -1 || d.bottom > innerHeight + 1 || el.scrollWidth > el.clientWidth + 1) bad.push('dialog'); for (const input of el.querySelectorAll('input, .el-dialog__footer button')) { const r = input.getBoundingClientRect(); if (!r.width || !r.height) continue; if (r.left < d.left - 1 || r.right > d.right + 1) bad.push(input.getAttribute('aria-label') || input.textContent); if (input.closest('.el-dialog__footer') && (r.top < d.top || r.bottom > d.bottom + 1)) bad.push('footer') }; return bad })
  assert.deepEqual(bad, [])
}
try {
  for (const width of [1440, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 950 }, reducedMotion: 'reduce' }); await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-mapping-keyboard'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
    const page = await context.newPage(), errors = [], calls = [], loadGate = gate(); let previewGate, publishGate, previewFail = true, publishAttempt = 0, rowVersion = 3, mappingVersion = 1
    page.on('pageerror', error => errors.push(error.message)); await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
    const sources = Array.from({ length: 21 }, (_, index) => ({ item_id: uuid(100 + index), model_key: 'MODEL' + index, color_key: index === 20 ? 'BROWN' : 'BLACK', model_name: index ? 'Base' + index : 'BaseZero', color_name: index === 20 ? 'Brown' : 'Black', length: index === 20 ? '22in' : '20in', weight: '25g', unit: 'pack', product_kind: 'hair' }))
    let entries = sources.map((s, index) => ({ kind: 'model', source_key: s.model_key, display_value: 'Alias' + index }))
    const company = 'C'.repeat(100), model = 'SignatureWeft'.repeat(10).slice(0, 128), color = 'ChampagnePearl'.repeat(10).slice(0, 128), sku = 'GW'.repeat(32), skuModel = 'SingleSKU'.repeat(16).slice(0, 128)
    const access = () => ({ id: accessId, company_display_name: company, status: 'enabled', row_version: rowVersion, canonical_customer_id: '55', sales_user_id: '5', capabilities: { can_view_price: true, can_order: true }, catalog_item_ids: sources.map(s => s.item_id), accounts: { items: [], total: 0 } })
    const send = (route, data, status = 200, message = 'OK') => route.fulfill({ status, json: { code: status, message, data } })
    await context.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (path === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Synthetic employee', roles: [], permissions: ['portal_access:read', 'portal_mapping:read', 'portal_mapping:write'] } })
      if (path === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-mapping-keyboard' } })
      if (!path.startsWith('/api/portal/')) return send(route, {})
      calls.push({ path, method: request.method(), body: request.postDataJSON(), version: request.headers()['if-match'] })
      if (path.endsWith('/customers')) return send(route, { items: [access()], total: 1 })
      if (path.endsWith('/customers/' + accessId)) return send(route, access())
      if (path.endsWith('/mapping')) { await loadGate.waiting; return send(route, { access_id: accessId, row_version: rowVersion, mapping_version: mappingVersion, sources, entries, draft: null }) }
      if (path.endsWith('/mapping/preview')) {
        await previewGate.waiting; const body = request.postDataJSON(); assert.deepEqual(Object.keys(body).sort(), ['base_version', 'entries']); assert.equal(body.base_version, mappingVersion)
        if (previewFail) { previewFail = false; return send(route, {}, 503, '映射校验暂时不可用，请重试。') }
        const changes = [], old = new Map(entries.map(e => [e.kind + e.source_key, e])), next = new Map(body.entries.map(e => [e.kind + e.source_key, e]))
        for (const key of new Set([...old.keys(), ...next.keys()])) { const before = old.get(key), after = next.get(key); if (JSON.stringify(before) !== JSON.stringify(after)) { const e = after || before; changes.push({ kind: e.kind, source_key: e.source_key, before: before || null, after: after || null, change: !before ? 'added' : !after ? 'removed' : 'modified' }) } }
        const conflict = body.entries.some(e => e.kind === 'color' && e.source_key === 'BLACK' && e.display_value === 'Brown')
        return send(route, { access_id: accessId, base_version: mappingVersion, row_version: rowVersion, affected_sku_count: 21, valid: !conflict, conflicts: conflict ? [{ code: 'COLOR_AMBIGUOUS', item_ids: [sources[0].item_id, sources[20].item_id] }] : [], changes, change_counts: Object.fromEntries(['added', 'modified', 'removed'].map(kind => [kind, changes.filter(c => c.change === kind).length])), items: sources.map(s => { const single = body.entries.find(e => e.kind === 'sku' && e.source_key === s.item_id); return { item_id: s.item_id, model_name: single?.display_value || body.entries.find(e => e.kind === 'model' && e.source_key === s.model_key)?.display_value || s.model_name, color_name: body.entries.find(e => e.kind === 'color' && e.source_key === s.color_key)?.display_value || s.color_name, customer_sku: single?.customer_sku || null, length: s.length, weight: s.weight, unit: s.unit } }) })
      }
      if (path.endsWith('/mapping/publish')) {
        await publishGate.waiting; const body = request.postDataJSON(); assert.equal(request.headers()['if-match'], '"' + rowVersion + '"'); assert.equal(body.base_version, mappingVersion); assert.equal(body.entries.length, 23)
        assert.deepEqual(body.entries[21], { kind: 'color', source_key: 'BLACK', display_value: color }); assert.deepEqual(body.entries[22], { kind: 'sku', source_key: sources[20].item_id, item_id: sources[20].item_id, display_value: skuModel, customer_sku: sku }); publishAttempt++
        if (publishAttempt === 1) { rowVersion++; mappingVersion++; return send(route, {}, 409, '记录已变化，请刷新确认。') }
        entries = structuredClone(body.entries); rowVersion++; mappingVersion++
        if (publishAttempt === 2) return route.abort('failed')
        return send(route, { id: uuid(2), mapping_version: mappingVersion, row_version: rowVersion, affected_sku_count: 21, expired_quotes: 1 })
      }
      throw new Error('Unexpected ' + request.method() + ' ' + path)
    })
    try {
      await page.goto(origin + '/portal/customers'); await activate(page, page.getByRole('button', { name: '管理', exact: true })); await activate(page, page.getByRole('button', { name: '型号颜色映射', exact: true }))
      const dialog = page.locator('.portal-mapping-dialog:visible'), preview = dialog.getByRole('button', { name: '校验并预览', exact: true }), publish = dialog.getByRole('button', { name: '发布映射', exact: true }), reload = dialog.getByRole('button', { name: '重新读取当前版本（舍弃草稿）', exact: true })
      await dialog.waitFor(); await dialog.getByRole('status').filter({ hasText: '正在读取客户映射…' }).waitFor(); loadGate.release()
      await dialog.getByRole('textbox', { name: '客户展示名 1', exact: true }).waitFor(); await bounds(page, dialog)
      await activate(page, dialog.locator('.el-pagination .btn-next').first()); await dialog.getByRole('textbox', { name: '客户展示名 21', exact: true }).waitFor()
      await type(page, dialog.getByRole('textbox', { name: '筛选映射条目', exact: true }), 'Base20'); await type(page, dialog.getByRole('textbox', { name: '客户展示名 21', exact: true }), 'LastCollection'); await type(page, dialog.getByRole('textbox', { name: '筛选映射条目', exact: true }), '')
      await type(page, dialog.getByRole('textbox', { name: '客户展示名 1', exact: true }), model)
      const kind = dialog.getByRole('combobox', { name: '映射类型', exact: true }); await reach(page, kind); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter')
      await source(page, dialog, 'Black'); await activate(page, dialog.getByRole('button', { name: '添加映射', exact: true })); await type(page, dialog.getByRole('textbox', { name: '客户展示名 22', exact: true }), 'Brown')
      await reach(page, kind); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter'); await source(page, dialog, 'Base20'); await activate(page, dialog.getByRole('button', { name: '添加映射', exact: true }))
      await type(page, dialog.getByRole('textbox', { name: '客户展示名 23', exact: true }), skuModel); await type(page, dialog.getByRole('textbox', { name: '客户货号 23', exact: true }), sku)
      await source(page, dialog, 'Base20'); await activate(page, dialog.getByRole('button', { name: '添加映射', exact: true })); const duplicate = dialog.getByRole('alert').filter({ hasText: '此来源已有映射，请编辑现有条目。' }); await duplicate.waitFor(); assert.equal(await duplicate.evaluate(el => el === document.activeElement), true)
      await activate(page, dialog.getByRole('button', { name: '添加映射', exact: true })); assert.equal(await duplicate.evaluate(el => el === document.activeElement), true)
      async function readPreview() { previewGate = gate(); await activate(page, preview); await dialog.getByRole('status').filter({ hasText: '正在校验映射与展示效果…' }).waitFor(); previewGate.release() }
      await readPreview(); const outage = dialog.getByRole('alert').filter({ hasText: '映射校验暂时不可用，请重试。' }); await outage.waitFor(); assert.equal(await outage.evaluate(el => el === document.activeElement), true); assert.equal(await dialog.getByRole('textbox', { name: '客户货号 23', exact: true }).inputValue(), sku)
      await readPreview(); const conflicts = dialog.getByRole('alert').filter({ hasText: '发现 1 项冲突，发布已阻止。' }); await conflicts.waitFor(); assert.equal(await conflicts.evaluate(el => el === document.activeElement), true); assert.equal(await publish.isDisabled(), true)
      await type(page, dialog.getByRole('textbox', { name: '客户展示名 22', exact: true }), color); assert.equal(await dialog.getByRole('checkbox').count(), 0); await readPreview()
      const feedback = dialog.getByRole('alert').filter({ hasText: '校验通过。请核对展示效果' }); await feedback.waitFor(); assert.equal(await feedback.evaluate(el => el === document.activeElement), true)
      const longCells = await dialog.locator('.list-table .cell').evaluateAll(cells => cells.filter(el => el.offsetWidth && el.textContent.trim().length >= 64).map(el => ({ textLength: el.textContent.trim().length, scroll: el.scrollWidth, width: el.clientWidth, whiteSpace: getComputedStyle(el).whiteSpace })))
      assert.ok(longCells.length > 0); for (const cell of longCells) { assert.ok(cell.scroll <= cell.width + 1, 'long mapping values must be fully readable'); assert.notEqual(cell.whiteSpace, 'nowrap') }
      await activate(page, dialog.getByRole('checkbox'), 'Space'); assert.equal(await dialog.getByRole('checkbox').isChecked(), true)
      await type(page, dialog.getByRole('textbox', { name: '客户展示名 22', exact: true }), 'Warm' + color.slice(4)); assert.equal(await dialog.getByRole('checkbox').count(), 0); assert.equal(await publish.isDisabled(), true)
      await type(page, dialog.getByRole('textbox', { name: '客户展示名 22', exact: true }), color); await readPreview(); await feedback.waitFor(); assert.equal(await dialog.getByRole('checkbox').isChecked(), false)
      await activate(page, dialog.locator('.el-pagination .btn-next').last()); await dialog.getByRole('cell', { name: sku, exact: true }).waitFor(); await bounds(page, dialog)
      const consent = dialog.getByRole('checkbox'); await activate(page, consent, 'Space')
      async function write() { publishGate = gate(); await activate(page, publish); await dialog.getByRole('status').filter({ hasText: '正在发布客户映射，请等待回执…' }).waitFor(); assert.equal(await publish.isDisabled(), true); publishGate.release() }
      await write(); const conflictError = dialog.getByRole('alert').filter({ hasText: '记录已变化，请刷新确认。' }); await conflictError.waitFor(); assert.equal(await conflictError.evaluate(el => el === document.activeElement), true); await activate(page, reload)
      await dialog.getByRole('textbox', { name: '客户展示名 1', exact: true }).waitFor(); await type(page, dialog.getByRole('textbox', { name: '客户展示名 1', exact: true }), model)
      // A conflict reload replaces drafts; the source selector still holds SKU, so ArrowUp selects color.
      await reach(page, kind); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowUp'); await page.keyboard.press('Enter'); await source(page, dialog, 'Black'); await activate(page, dialog.getByRole('button', { name: '添加映射', exact: true })); await type(page, dialog.getByRole('textbox', { name: '客户展示名 22', exact: true }), color)
      await reach(page, kind); await page.keyboard.press('Enter'); await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter'); await source(page, dialog, 'Base20'); await activate(page, dialog.getByRole('button', { name: '添加映射', exact: true })); await type(page, dialog.getByRole('textbox', { name: '客户展示名 23', exact: true }), skuModel); await type(page, dialog.getByRole('textbox', { name: '客户货号 23', exact: true }), sku)
      await readPreview(); await feedback.waitFor(); await activate(page, consent, 'Space'); await write(); await dialog.getByText('发布结果未知。不会自动重发；请读取当前已发布版本并核对，再决定后续修改。', { exact: true }).waitFor()
      assert.equal(await dialog.getByRole('textbox', { name: '客户展示名 23', exact: true }).isDisabled(), true); await page.keyboard.press('Escape'); assert.equal(await dialog.isVisible(), true); await bounds(page, dialog); await page.screenshot({ path: output + '/unknown-' + width + '.png', fullPage: true })
      const writes = calls.filter(c => c.path.endsWith('/publish')).length; await activate(page, reload); const recovered = dialog.getByRole('alert').filter({ hasText: '已读取当前已发布版本并替换草稿' }); await recovered.waitFor(); assert.equal(await recovered.evaluate(el => el === document.activeElement), true); assert.equal(calls.filter(c => c.path.endsWith('/publish')).length, writes); assert.equal(await publish.isDisabled(), true)
      await type(page, dialog.getByRole('textbox', { name: '客户展示名 1', exact: true }), 'Final' + model.slice(5)); await readPreview(); await feedback.waitFor(); await activate(page, consent, 'Space'); await bounds(page, dialog); await page.screenshot({ path: output + '/prepared-' + width + '.png', fullPage: true }); await write(); await dialog.waitFor({ state: 'hidden' })
      await page.getByRole('button', { name: '型号颜色映射', exact: true }).waitFor(); await page.waitForFunction(() => document.activeElement?.tagName === 'BUTTON' && document.activeElement.textContent.trim() === '型号颜色映射', undefined, { timeout: 3000 }); assert.equal(publishAttempt, 3); assert.deepEqual(errors, [])
      results.push({ width, keyboard: true, entries: entries.length, aliases: [model.length, color.length, skuModel.length, sku.length], simulatedPublishAttempts: publishAttempt, scope: 'Built employee UI and intercepted APIs; no real backend, authentication, mapping persistence or prices' })
    } catch (error) { await page.screenshot({ path: output + '/failure-' + width + '.png', fullPage: true }); await writeFile(output + '/failure-' + width + '.json', JSON.stringify(await page.evaluate(() => ({ active: document.activeElement?.outerHTML?.slice(0, 600), controls: [...document.querySelectorAll('input')].map(el => ({ role: el.getAttribute('role'), label: el.getAttribute('aria-label'), placeholder: el.getAttribute('placeholder') })) })), null, 2)); throw error }
    finally { loadGate.release(); previewGate?.release(); publishGate?.release(); await context.close() }
  }
  await writeFile(output + '/result.json', JSON.stringify({ status: 'pass', results }, null, 2)); console.log(JSON.stringify({ status: 'pass', widths: results.length, output }))
} finally { await browser.close() }
