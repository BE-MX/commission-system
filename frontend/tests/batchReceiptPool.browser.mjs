import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'

const require = createRequire(import.meta.url), { chromium } = require(process.argv[2])
const base = process.argv[3], output = process.argv[4], results = []
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO6sAAAAASUVORK5CYII=', 'base64')
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce' })
    const page = await context.newPage(), writes = [], errors = [], unexpected = []
    const invoice = { id: 1, invoice_no: 'PI-NEW-CASH-38', customer_id: 'C1', customer_name: 'Synthetic Customer', currency: 'USD', sync_status: 'synced' }
    const balance = { funding_mode: 'presale_pool', version: 'a'.repeat(64), remaining_amount: '0.00', pool_available_amount: '412.00',
      active_settlement: { settlement_id: 9, funding_version: 2, version: 'b'.repeat(64), remaining_amount: '0.00', charge_remaining: '0.00', state: 'outbound_pending' } }
    page.on('pageerror', error => errors.push(error.message))
    const ok = (route, data) => route.fulfill({ json: { code: 200, message: 'ok', data } })
    await page.route(base + '/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (path === '/api/receipts/order-options') return ok(route, { items: [invoice] })
      if (path === '/api/receipts/order-balance/1') return ok(route, balance)
      if (path === '/api/receipts/types') return ok(route, ['T/T'])
      if (path === '/api/receipts/attachments' && request.method() === 'POST') return ok(route, { id: 'synthetic-proof', name: 'payment.png' })
      if (path === '/api/receipts/attachments/synthetic-proof') return route.fulfill({ contentType: 'image/png', body: png })
      if (path === '/api/receipts/batches') {
        const body = request.postDataJSON(); writes.push(body)
        return ok(route, { id: 7, request_key: body.request_key, status: 'active', items: [{ invoice_id: 1, amount: '38' }] })
      }
      unexpected.push(path)
      return route.fulfill({ status: 503, json: { detail: 'Unexpected isolated request' } })
    })
    await page.goto(base + '/tests/batchReceiptHarness.html')
    await page.getByRole('button', { name: '打开批次回款', exact: true }).click()
    await page.locator('.el-form .el-select').first().click()
    await page.getByRole('option', { name: /PI-NEW-CASH-38/ }).click()
    const purpose = page.locator('.el-table .el-select')
    await page.getByText('预付余额 412.00', { exact: true }).waitFor()
    assert.match(await purpose.innerText(), /预付货款/)
    await purpose.click(); await page.getByRole('option', { name: '本批补款', exact: true }).click()
    await page.getByRole('spinbutton', { name: '本次分配金额', exact: true }).fill('38'); await page.keyboard.press('Tab')
    await page.locator('.fields-grid .el-form-item').filter({ hasText: '本次回款金额' }).getByRole('spinbutton').fill('38'); await page.keyboard.press('Tab')
    await page.locator('.fields-grid .el-select').click(); await page.getByRole('option', { name: 'T/T', exact: true }).click()
    await page.locator('input[type=file]').setInputFiles({ name: 'payment.png', mimeType: 'image/png', buffer: png })
    const submit = page.getByRole('button', { name: '创建回款单', exact: true })
    await submit.click()
    await page.getByText(/PI-NEW-CASH-38：本批可补款余额为 0/).first().waitFor()
    assert.equal(writes.length, 0)
    await purpose.click(); await page.getByRole('option', { name: '预付货款', exact: true }).click()
    await page.getByRole('button', { name: '刷新', exact: true }).click()
    await page.getByText('预付余额 412.00', { exact: true }).waitFor()
    assert.match(await purpose.innerText(), /预付货款/)
    await submit.click(); await page.getByRole('dialog').waitFor({ state: 'hidden' })
    assert.equal(writes.length, 1)
    assert.equal(writes[0].amount, '38')
    assert.deepEqual(writes[0].allocations, [{ invoice_id: 1, settlement_id: null, amount: '38', balance_version: 'a'.repeat(64), purpose: 'presale_advance', bank_charge: '0' }])
    assert.deepEqual(await page.evaluate(() => window.saved.map(row => row.id)), [7])
    assert.equal(await page.evaluate(() => sessionStorage.getItem('ark_receipt_batch_pending_v1:1')), null)
    // A legacy batch keeps its explicit supplement route and cannot accept pool cash.
    balance.active_settlement.funding_version = 1
    await page.getByRole('button', { name: '打开批次回款', exact: true }).click()
    await page.locator('.el-form .el-select').first().click(); await page.getByRole('option', { name: /PI-NEW-CASH-38/ }).click()
    await page.locator('.el-table .el-select').filter({ hasText: '本批补款' }).waitFor()
    await page.locator('.el-table .el-select').click()
    assert.equal(await page.getByRole('option', { name: '预付货款', exact: true }).getAttribute('aria-disabled'), 'true')
    assert.equal(await page.getByRole('option', { name: '定金（最后一批抵扣）', exact: true }).getAttribute('aria-disabled'), 'true')
    assert.deepEqual(errors, []); assert.deepEqual(unexpected, [])
    results.push({ width, zeroBalanceBlocked: true, new38RegisteredAsPool: true, refreshedPurposePreserved: true, legacyPoolBlocked: true, errors })
    await context.close()
  }
  await writeFile(output + '/results.json', JSON.stringify(results, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
