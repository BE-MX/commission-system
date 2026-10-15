import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'

const require = createRequire(import.meta.url), { chromium } = require(process.argv[2])
const base = process.argv[3], output = process.argv[4]
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const results = []
try {
  for (const width of [1440, 390]) {
    for (const scenario of ['normal', 'payment', 'failed', 'failed_remote', 'failed_unavailable']) {
      const blocked = scenario === 'payment', failed = scenario.startsWith('failed')
      const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
      const page = await context.newPage(), errors = [], writes = [], unexpected = []
      let state = failed ? 'review_required' : 'awaiting_payment', version = 6, listReads = 0
      const reason = '已有真实付款或运费目标，仅支持原批暂停/恢复'
      const row = () => ({ id: 8, invoice_id: 1, settlement_no: 'TEST-01', state, version,
        quote: { items: [{ invoice_item_id: 7, quantity: 4 }] }, payment_term: 'pay_first',
        balance: { registered_amount: state === 'cancelled' ? '0.00' : '1000.00', goods_remaining: '3777.42',
          outstanding_amount: '3777.42', pending_amount: '0.00', freight_remaining: '0.00' },
        receipt_applications: [{ receipt_id: 1114, receipt_no: 'ORIGINAL-1000', amount: '1000.00',
          status: state === 'cancelled' ? 'released' : 'reserved', effective: true }],
        ...(failed ? { outbound: { id: 9, number: 'TEST-01', remote_id: null,
          status: state === 'cancelled' ? 'cancelled' : 'failed', last_error: '库存不足，出库创建失败' } } : {}),
        actions: { cancel: { allowed: !blocked && state !== 'cancelled', reason: blocked ? reason : '',
          requires_remote_check: failed && state !== 'cancelled' },
          pause: { allowed: state === 'awaiting_payment', reason: '' },
          resume: { allowed: state === 'paused', reason: '' } } })
      page.on('pageerror', error => errors.push(error.message))
      await page.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url())
        if (url.origin !== new URL(base).origin) return route.abort()
        if (!url.pathname.startsWith('/api/')) return route.continue()
        const ok = data => route.fulfill({ json: { code: 200, message: 'ok', data } })
        if (url.pathname === '/api/invoice/invoices/1') return ok({ id: 1, invoice_no: 'TEST', currency: 'USD',
          items: [{ id: 7, product_name: 'Test product', quantity: 10 }] })
        if (url.pathname === '/api/shipments/order/1') { listReads++; return ok({ items: [row()] }) }
        if (url.pathname === '/api/shipments/8') return ok(row())
        if (['/api/shipments/8/pause', '/api/shipments/8/cancel'].includes(url.pathname)) {
          const body = request.postDataJSON()
          assert.equal(body.version, version)
          assert.ok(body.reason.length >= 2)
          writes.push(url.pathname)
          if (scenario === 'failed_remote') return route.fulfill({ status: 409,
            json: { detail: '小满已有同编号出库单，请先核对原单，不能取消重建' } })
          if (scenario === 'failed_unavailable') return route.fulfill({ status: 503,
            json: { detail: '发货结算结果暂无法确认，请先刷新原结算核对版本，不要重复提交' } })
          state = url.pathname.endsWith('/pause') ? 'paused' : 'cancelled'; version++
          return ok(row())
        }
        if (url.pathname === '/api/invoices/1/shipment-quotes') {
          assert.equal(state, 'cancelled')
          assert.equal(request.postDataJSON().items[0].quantity, 2)
          return ok({ quote_hash: 'a'.repeat(64), goods_amount: '200.00', advance_applied: '200.00',
            packaging_amount: '0.00', handling_amount: '0.00', freight_amount: '0.00',
            deposit_applied: '0.00', new_payment_due: '0.00',
            pool_balances: [{ purpose: 'presale_advance', effective: true, remaining_amount: '800.00' }] })
        }
        unexpected.push(url.pathname)
        return route.fulfill({ status: 503, json: { detail: 'Unexpected isolated endpoint' } })
      })
      await page.goto(base + '/tests/shipmentSubmissionHarness.html')
      await page.getByRole('button', { name: '打开出库结算', exact: true }).click()
      const cancel = page.getByRole('button', { name: '取消本批次', exact: true })
      const preview = page.getByRole('button', { name: '核算本批金额', exact: true })
      await cancel.waitFor()
      if (blocked) {
        assert.equal(await cancel.isDisabled(), true)
        await page.getByText(reason, { exact: true }).waitFor()
        assert.deepEqual(writes, [])
      } else {
        assert.equal(await cancel.isEnabled(), true) // Existing USD 1000 never hides it.
        if (!failed) {
          await page.getByRole('button', { name: '暂停', exact: true }).click()
          const prompt = page.getByRole('dialog', { name: '暂停本批次', exact: true })
          await prompt.getByText(/暂停仍保留本批数量和预付款占用/).waitFor()
          await prompt.getByRole('textbox').fill('Temporarily hold this batch')
          await prompt.getByRole('button', { name: '暂停本批次', exact: true }).click()
          await page.getByRole('button', { name: '恢复', exact: true }).waitFor()
          assert.equal(await preview.isDisabled(), true)
          await page.getByText(/当前批次已暂停，仍保留数量和预付款占用/).waitFor()
        } else {
          await page.getByText(/本批出库创建失败。可取消本批次后调整数量重新创建/).waitFor()
        }
        await page.getByRole('button', { name: 'TEST-01', exact: true }).click()
        await page.getByText('ORIGINAL-1000', { exact: true }).waitFor()
        await cancel.click()
        const confirmation = page.getByRole('dialog', { name: '取消本批次', exact: true })
        await confirmation.getByText(failed ? /先核实小满未生成原出库单/ : /保留原回款及审计记录/).waitFor()
        await confirmation.getByRole('textbox').fill('Rearrange quantities and payment terms')
        await confirmation.getByRole('button', { name: '取消本批次', exact: true }).click()
        if (['failed_remote', 'failed_unavailable'].includes(scenario)) {
          await page.locator('.el-alert--error').getByText(scenario === 'failed_remote' ? /小满已有同编号出库单/ : /发货结算结果暂无法确认/).waitFor()
          assert.equal(state, 'review_required')
          assert.equal(await preview.isDisabled(), true)
          assert.equal(await page.locator('.el-table').first().getByRole('spinbutton').getAttribute('max'), '6')
          assert.deepEqual(writes, ['/api/shipments/8/cancel'])
          assert.deepEqual(errors, []); assert.deepEqual(unexpected, [])
          results.push({ width, scenario, writes, keepsOriginalBatch: true, automaticRetry: false })
          await context.close()
          continue
        }
        await page.getByText('已释放', { exact: true }).waitFor()
        await page.waitForFunction(expected => window.saved.length === expected, failed ? 1 : 2)
        assert.equal(await preview.isEnabled(), true)
        assert.ok(listReads >= (failed ? 2 : 3))
        const quantity = page.locator('.el-table').first().getByRole('spinbutton')
        assert.equal(await quantity.getAttribute('aria-valuemax'), '10')
        assert.equal(await quantity.getAttribute('aria-disabled'), 'false')
        await quantity.fill('2'); await quantity.press('Tab')
        await preview.click()
        await page.getByText('USD 800.00', { exact: true }).waitFor()
        await page.getByText('ORIGINAL-1000', { exact: true }).waitFor()
        assert.deepEqual(writes, failed ? ['/api/shipments/8/cancel'] : ['/api/shipments/8/pause', '/api/shipments/8/cancel'])
      }
      assert.deepEqual(errors, []); assert.deepEqual(unexpected, [])
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      await page.screenshot({ path: `${output}/${scenario}-${width}.png`, fullPage: true })
      results.push({ width, scenario, writes, listReads, noPageErrors: true,
        scope: 'Actual Vue/shared API client with synthetic responses; no production writes' })
      await context.close()
    }
  }
  await writeFile(output + '/results.json', JSON.stringify(results, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
