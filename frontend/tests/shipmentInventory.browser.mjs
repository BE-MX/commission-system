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
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' })
    const page = await context.newPage(), errors = [], unexpected = [], posts = []
    let available = '5.9', stockReads = 0, unavailable = false, releaseFirstStock
    const firstStock = new Promise(resolve => { releaseFirstStock = resolve })
    const items = Array.from({ length: 33 }, (_, index) => ({ id: index + 7, product_id: 11,
      sku_id: index < 3 ? 22 : index + 100, product_name: `Stock product ${index + 1}`,
      quantity: index === 1 ? 2 : 10 }))
    page.on('pageerror', e => errors.push(e.message))
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const ok = data => route.fulfill({ json: { code: 200, message: 'ok', data } })
      if (url.pathname === '/api/invoice/invoices/1') return ok({ id: 1, invoice_no: 'STOCK-TEST', currency: 'USD', items })
      if (url.pathname === '/api/shipments/order/1') return ok({ items: [] })
      if (url.pathname === '/api/invoices/1/shipment-inventory') {
        stockReads++
        if (stockReads === 1) await firstStock
        if (unavailable) return route.fulfill({ status: 503, json: { detail: 'stock unavailable' } })
        return ok({ invoice_id: 1, warehouse_id: '17', source: 'okki_live', queried_at: '2026-10-16T00:01:00',
          items: items.map((row, index) => ({ invoice_item_id: row.id, product_id: '11', sku_id: String(row.sku_id),
            available_stock: index === 3 ? '0' : index === 4 ? null : available, reason: index === 4 ? 'missing mapping' : '' })) })
      }
      if (url.pathname === '/api/invoices/1/shipment-quotes') {
        posts.push(request.postDataJSON())
        return ok({ quote_hash: 'a'.repeat(64), goods_amount: '50.00', packaging_amount: '0', handling_amount: '0',
          freight_amount: '0', deposit_applied: '0', advance_applied: '0', new_payment_due: '50.00' })
      }
      unexpected.push(url.pathname)
      return route.fulfill({ status: 503, json: { detail: 'unexpected isolated request' } })
    })
    await page.goto(base + '/tests/shipmentSubmissionHarness.html')
    await page.getByRole('button', { name: '打开出库结算', exact: true }).click()
    const table = page.locator('.shipment-products-table'), inputs = table.getByRole('spinbutton')
    const preview = page.getByRole('button', { name: '核算本批金额', exact: true })
    const fill = page.getByRole('button', { name: '一键填充', exact: true })
    await table.getByText('Stock product 1', { exact: true }).waitFor()
    assert.equal(await fill.isDisabled(), true)
    await page.getByText(/正在查询实时可用库存/).waitFor()
    await page.waitForFunction(() => [...document.querySelectorAll('.shipment-content .el-loading-mask')].every(node => getComputedStyle(node).display === 'none' || getComputedStyle(node).opacity === '0'))
    releaseFirstStock()
    await table.getByText('5.9', { exact: true }).first().waitFor()
    await table.getByRole('columnheader', { name: /剩余待出库/ }).waitFor()
    await table.getByRole('columnheader', { name: /可用库存/ }).waitFor()
    assert.equal(await inputs.nth(0).getAttribute('max'), '5')
    assert.equal(await inputs.nth(1).getAttribute('max'), '2')
    assert.equal(await inputs.nth(3).getAttribute('max'), '0')
    assert.equal(await inputs.nth(4).isDisabled(), true)
    await inputs.nth(0).fill('99'); await inputs.nth(0).press('Tab')
    assert.equal(await inputs.nth(0).inputValue(), '5')
    await inputs.nth(0).fill('3'); await inputs.nth(0).press('Tab')
    await inputs.nth(2).fill('3'); await inputs.nth(2).press('Tab')
    await page.getByText('同一产品本批数量合计超过可用库存，请调整数量', { exact: true }).waitFor()
    assert.equal(await preview.isDisabled(), true)
    await inputs.nth(2).fill('2'); await inputs.nth(2).press('Tab')
    await preview.click(); await page.getByText('USD 50.00', { exact: true }).first().waitFor()
    assert.deepEqual(posts[0].items, [{ invoice_item_id: 7, quantity: 3 }, { invoice_item_id: 9, quantity: 2 }])
    const productHeader = table.getByRole('columnheader', { name: /^产品/ })
    await productHeader.click(); await productHeader.click() // Visual descending sort cannot change allocation priority.
    await fill.click()
    const productInput = name => table.locator('.el-table__body tr').filter({ has: page.getByText(name, { exact: true }) }).getByRole('spinbutton')
    assert.equal(await productInput('Stock product 1').inputValue(), '5')
    assert.equal(await productInput('Stock product 2').inputValue(), '0')
    assert.equal(await productInput('Stock product 3').inputValue(), '0')
    assert.equal(await productInput('Stock product 4').inputValue(), '0')
    assert.equal(await productInput('Stock product 5').inputValue(), '0')
    assert.equal(posts.length, 1)
    assert.equal(await page.getByRole('button', { name: '生成本批结算单', exact: true }).isDisabled(), true)
    await preview.click()
    await page.getByText('USD 50.00', { exact: true }).first().waitFor()
    assert.equal(posts[1].items.length, 29)
    assert.equal(posts[1].items[0].invoice_item_id, 7)
    assert.equal(posts[1].items.reduce((sum, row) => sum + row.quantity, 0), 145)
    await productHeader.click()
    await inputs.nth(0).fill('3'); await inputs.nth(0).press('Tab')
    await inputs.nth(2).fill('2'); await inputs.nth(2).press('Tab')
    await page.screenshot({ path: `${output}/inventory-available-${width}.png`, fullPage: true })
    available = '1'
    await page.getByRole('button', { name: '刷新库存', exact: true }).click()
    await table.getByText('1', { exact: true }).first().waitFor()
    assert.equal(await inputs.nth(0).inputValue(), '3') // Refresh never silently rewrites the draft.
    assert.equal(await inputs.nth(0).getAttribute('aria-valuemax'), '1')
    assert.equal(await preview.isDisabled(), true)
    assert.equal(await page.getByRole('button', { name: '生成本批结算单', exact: true }).isDisabled(), true)
    unavailable = true
    await page.getByRole('button', { name: '刷新库存', exact: true }).click()
    await page.getByText('所选产品可用库存待核对，请刷新库存', { exact: true }).waitFor()
    assert.equal(await inputs.nth(0).inputValue(), '3')
    assert.equal(await inputs.nth(0).isDisabled(), true)
    assert.equal(await inputs.nth(0).getAttribute('aria-disabled'), 'true')
    const metrics = await table.evaluate(node => {
      const body = node.querySelector('.el-scrollbar__wrap')
      return { height: body.clientHeight, scrollHeight: body.scrollHeight }
    })
    assert.ok(metrics.scrollHeight > metrics.height)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, []); assert.equal(stockReads, 3); assert.equal(posts.length, 2)
    await page.screenshot({ path: `${output}/inventory-${width}.png`, fullPage: true })
    results.push({ width, stockReads, metrics, earlyProductList: true, fillRespectsOriginalOrderAndSkuBudget: true, filledItems: 29, preservedDraft: true, unknownBlocked: true, skuAggregateBlocked: true, scope: 'Actual Vue/Chrome, synthetic API; no production writes' })
    await context.close()
  }
  await writeFile(output + '/results.json', JSON.stringify(results, null, 2))
} finally { await browser.close() }
console.log(JSON.stringify(results))
