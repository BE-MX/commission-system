import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.argv[2]), base = process.argv[3], output = process.argv[4]
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const results = []
try {
  for (const width of [1440, 390]) for (const scenario of ['success', 'active', 'unavailable', 'denied']) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
    const page = await context.newPage(), errors = [], writes = [], unexpected = []
    let state = 'outbound_uncertain', version = 6
    const row = () => ({
      id: 7, invoice_id: 1, settlement_no: 'TEST-02', state, version, payment_term: 'pay_first',
      quote: { freight_amount: '121.16', items: [{ invoice_item_id: 8, quantity: 4 }] },
      outbound: { id: 6, number: 'TEST-02', remote_id: '401',
        status: state === 'cancelled_keep_freight' ? 'cancelled' : 'uncertain' },
      freight_target: { id: 7, status: 'bound', remote_order_id: '300' },
      balance: { outstanding_amount: '0', pending_amount: '0', goods_remaining: '0', freight_remaining: '0' },
      receipt_applications: [
        { receipt_id: 1062, receipt_no: 'ORIGINAL-GOODS', amount: '1415.54', component: 'goods',
          status: state === 'cancelled_keep_freight' ? 'released' : 'reserved', effective: true },
        { receipt_id: 1385, receipt_no: 'ORIGINAL-FREIGHT', amount: '121.16', component: 'freight',
          status: state === 'cancelled_keep_freight' ? 'applied' : 'reserved', effective: true },
      ],
      actions: {
        cancel: { allowed: false, reason: '已有出库任务，请先核实远端效果' },
        cancel_deleted: { allowed: state !== 'cancelled_keep_freight', keep_freight: true, retained_freight_amount: '121.16' },
      },
    })
    page.on('pageerror', e => errors.push(e.message))
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const ok = data => route.fulfill({ json: { code: 200, message: 'ok', data } })
      if (url.pathname === '/api/invoice/invoices/1') return ok({ id: 1, invoice_no: 'TEST', currency: 'USD',
        items: [{ id: 8, product_name: 'Hair', quantity: 10 }] })
      if (url.pathname === '/api/invoices/1/shipment-inventory') return ok({
        invoice_id: 1, source: 'okki_live', queried_at: '2026-10-26T11:00:00',
        items: [{ invoice_item_id: 8, available_stock: '100' }],
      })
      if (url.pathname === '/api/shipments/order/1') return ok({ items: [row()] })
      if (url.pathname === '/api/shipments/7') return ok(row())
      if (url.pathname === '/api/shipments/7/cancel-deleted-outbound') {
        const body = request.postDataJSON()
        assert.equal(body.version, 6); assert.ok(body.reason.length >= 2)
        writes.push(url.pathname)
        const failures = { active: [409, '小满原出库单仍有效，请先在小满删除后重新核实'],
          unavailable: [503, '发货结算结果暂无法确认，请先刷新原结算核对版本，不要重复提交'],
          denied: [403, '当前账号无权执行此回款操作'] }
        if (failures[scenario]) return route.fulfill({
          status: failures[scenario][0], json: { detail: failures[scenario][1] },
        })
        state = 'cancelled_keep_freight'; version++
        return ok(row())
      }
      if (url.pathname === '/api/invoices/1/shipment-quotes') {
        assert.equal(state, 'cancelled_keep_freight')
        assert.equal(Number(request.postDataJSON().freight_amount), 0)
        assert.equal(request.postDataJSON().items[0].quantity, 2)
        return ok({ quote_hash: 'a'.repeat(64), goods_amount: '200', advance_applied: '200',
          packaging_amount: '0', handling_amount: '0', freight_amount: '0', deposit_applied: '0',
          new_payment_due: '0', retained_freight_settlement_id: 7, retained_freight_amount: '121.16' })
      }
      unexpected.push(url.pathname)
      return route.fulfill({ status: 503, json: { detail: 'Unexpected isolated endpoint' } })
    })
    await page.goto(base + '/tests/shipmentSubmissionHarness.html')
    await page.getByRole('button', { name: '打开出库结算', exact: true }).click()
    const cancel = page.getByRole('button', { name: '核实删除并撤销', exact: true })
    await cancel.waitFor()
    await page.getByRole('button', { name: 'TEST-02', exact: true }).click()
    await page.getByText('ORIGINAL-FREIGHT', { exact: true }).waitFor()
    await cancel.click()
    const prompt = page.getByRole('dialog', { name: '核实删除并撤销', exact: true })
    await prompt.getByText(/保留原运费 USD 121.16 及其抵扣/).waitFor()
    await prompt.getByRole('textbox').fill('小满已删除，保留原运费及抵扣')
    await prompt.getByRole('button', { name: '核实删除并撤销', exact: true }).click()
    if (scenario === 'success') {
      await page.getByText('已撤销·运费保留', { exact: true }).first().waitFor()
      await page.getByText(/原批次已保留运费 USD 121.16/).waitFor()
      await page.getByText('已释放', { exact: true }).waitFor()
      assert.equal(await cancel.count(), 0)
      // Element Plus labels the input directly in current versions.
      const freightInput = page.locator('.el-form-item').filter({ hasText: '本批运费' }).getByRole('spinbutton')
      assert.equal(await freightInput.isDisabled(), true)
      assert.equal(await freightInput.inputValue(), '0.00')
      const quantity = page.locator('.el-table').first().getByRole('spinbutton')
      assert.equal(await quantity.getAttribute('aria-valuemax'), '10')
      await quantity.fill('2'); await quantity.press('Tab')
      await page.getByRole('button', { name: '核算本批金额', exact: true }).click()
      await page.getByText('USD 200.00', { exact: true }).first().waitFor()
    } else {
      await page.locator('.el-alert--error').waitFor()
      assert.equal(state, 'outbound_uncertain')
      const preview = page.getByRole('button', { name: '核算本批金额', exact: true })
      if (scenario === 'denied') assert.equal(await preview.count(), 0)
      else assert.equal(await preview.isDisabled(), true)
    }
    assert.deepEqual(writes, ['/api/shipments/7/cancel-deleted-outbound'])
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, [])
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: output + '/' + scenario + '-' + width + '.png', fullPage: true })
    results.push({ width, scenario, preservedOriginalCash: true, noAutomaticRetry: true })
    await context.close()
  }
  await writeFile(output + '/results.json', JSON.stringify(results, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
