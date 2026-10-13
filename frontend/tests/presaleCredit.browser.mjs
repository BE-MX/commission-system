import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir, writeFile} from 'node:fs/promises'
const require = createRequire(import.meta.url), {chromium} = require(process.argv[2])
const base = process.argv[3], output = process.argv[4]
await mkdir(output, {recursive: true})
const browser = await chromium.launch({executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true})
const results = [], png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO6sAAAAASUVORK5CYII=', 'base64')
try {
  for (const width of [1440, 390, 320]) {
    console.log('Checking viewport ' + width)
    const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce'})
    const page = await context.newPage(), errors = [], quotes = [], writes = []
    let created = false
    page.on('pageerror', error => errors.push(error.message))
    const invoice = {id: 1, invoice_no: 'TEST-CREDIT', currency: 'USD', items: [{id: 7, product_name: '测试产品', quantity: 10}]}
    const row = () => ({id: 8, invoice_id: 1, settlement_no: 'TEST-CREDIT-01', payment_term: 'ship_first',
      state: 'shipped', version: 2, quote: {payment_term: 'ship_first', items: [{invoice_item_id: 7, quantity: 4}]},
      balance: {goods_remaining: '400.00', freight_remaining: '0.00', outstanding_amount: '400.00', pending_amount: '0.00'},
      outbound: {id: 9, number: 'TEST-CREDIT-01', remote_id: '401', status: 'shipped'},
      receipt_applications: []})
    const ok = (route, data) => route.fulfill({json: {code: 200, message: 'ok', data}})
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (url.pathname === '/api/invoice/invoices/1') return ok(route, invoice)
      if (url.pathname === '/api/shipments/order/1') return ok(route, {items: created ? [row()] : []})
      if (url.pathname === '/api/shipments/8') return ok(route, row())
      if (url.pathname === '/api/invoices/1/shipment-quotes') {
        const body = request.postDataJSON(); quotes.push(body)
        return ok(route, {quote_hash: 'a'.repeat(64), payment_term: body.payment_term, is_final: false,
          goods_amount: '400.00', packaging_amount: '0.00', handling_amount: '0.00', freight_amount: '0.00',
          deposit_applied: '0.00', advance_applied: '0.00', new_payment_due: '400.00', pool_balances: []})
      }
      if (url.pathname === '/api/invoices/1/shipment-settlements') {
        const body = request.postDataJSON(); writes.push(body); created = true
        return ok(route, {...row(), state: 'awaiting_payment', request_key: body.request_key, quote_hash: body.quote_hash})
      }
      throw new Error('Unexpected isolated shipment request ' + url.pathname)
    })
    await page.goto(base + '/tests/shipmentSubmissionHarness.html')
    await page.getByRole('button', {name: '打开出库结算', exact: true}).click()
    await page.getByRole('radio', {name: '先付款后出库', exact: true}).waitFor()
    assert.equal(await page.getByRole('radio', {name: '先付款后出库', exact: true}).isChecked(), true)
    await page.locator('.el-table').getByRole('spinbutton').fill('4')
    await page.keyboard.press('Tab')
    await page.getByRole('button', {name: '核算本批金额', exact: true}).click()
    await page.getByRole('button', {name: '生成本批结算单', exact: true}).waitFor()
    assert.equal(quotes[0].payment_term, 'pay_first')
    await page.locator('label.el-radio').filter({hasText: '先出库后回款'}).click()
    assert.equal(await page.getByRole('button', {name: '生成本批结算单', exact: true}).isDisabled(), true)
    await page.getByRole('button', {name: '核算本批金额', exact: true}).click()
    await page.getByText('本批允许欠款生成出库单。', {exact: false}).waitFor()
    await page.screenshot({path: output + '/credit-choice-' + width + '.png', fullPage: true})
    await page.getByRole('button', {name: '生成本批结算单', exact: true}).click()
    await page.getByRole('dialog').waitFor({state: 'hidden'})
    assert.equal(writes.length, 1)
    assert.equal(writes[0].payment_term, 'ship_first')
    assert.equal(writes[0].payment, undefined)
    await page.getByRole('button', {name: '打开出库结算', exact: true}).click()
    await page.getByRole('button', {name: 'TEST-CREDIT-01', exact: true}).click()
    const detail = page.locator('.el-descriptions').filter({hasText: '本批欠款'})
    await detail.getByText('400.00', {exact: true}).last().waitFor()
    assert.match(await detail.innerText(), /已出库/)
    assert.match(await detail.innerText(), /先出库后回款/)
    assert.equal(await page.getByRole('radio', {name: '先付款后出库', exact: true}).isChecked(), true)
    const box = await page.getByRole('dialog').boundingBox()
    assert.ok(box.x >= 0 && box.x + box.width <= width + 1)
    await detail.getByText('本批欠款', {exact: true}).scrollIntoViewIfNeeded()
    await page.screenshot({path: output + '/credit-debt-' + width + '.png', fullPage: true})
    assert.deepEqual(errors, [])
    await context.close()

    const receiptContext = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce'})
    const receiptPage = await receiptContext.newPage(), payments = [], paymentErrors = []
    let balanceReads = 0
    receiptPage.on('pageerror', error => paymentErrors.push(error.message))
    const candidate = (id, remaining) => ({settlement_id: id, settlement_no: 'TEST-OLD-' + id,
      payment_term: 'ship_first', state: 'shipped', funding_version: 2, version: String(id).repeat(64),
      remaining_amount: remaining, outstanding_amount: remaining, charge_remaining: '0'})
    await receiptPage.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (url.pathname === '/api/receipts/order-options') return ok(route, {items: [{
        id: 1, invoice_no: 'TEST-CREDIT', customer_id: 'C1', customer_name: '测试客户', currency: 'USD', sync_status: 'synced'}]})
      if (url.pathname === '/api/receipts/order-balance/1') {
        balanceReads++
        const batches = [candidate(8, '50.00'), candidate(9, '20.00')]
        return ok(route, {version: 'pool-v1', funding_mode: 'presale_pool', remaining_amount: '100',
          pool_available_amount: '0', payment_settlements: balanceReads === 1 ? batches : batches.reverse()})
      }
      if (url.pathname === '/api/receipts/types') return ok(route, ['T/T'])
      if (url.pathname === '/api/receipts/attachments' && request.method() === 'POST') return ok(route, {id: 'proof', name: 'payment.png'})
      if (url.pathname === '/api/receipts/attachments/proof') return route.fulfill({contentType: 'image/png', body: png})
      if (url.pathname === '/api/receipts/batches') {
        const body = request.postDataJSON(); payments.push(body)
        return ok(route, {id: 10, status: 'active', request_key: body.request_key, items: [{invoice_id: 1, amount: '30'}]})
      }
      throw new Error('Unexpected isolated receipt request ' + url.pathname)
    })
    await receiptPage.goto(base + '/tests/presaleCreditReceiptHarness.html')
    await receiptPage.getByRole('button', {name: '打开批次回款', exact: true}).click()
    await receiptPage.locator('.el-form .el-select').first().click()
    await receiptPage.getByRole('option', {name: /TEST-CREDIT/}).click()
    const selector = receiptPage.getByRole('combobox', {name: '关联发货批次', exact: true})
    await selector.waitFor()
    await receiptPage.locator('.el-select').filter({has: selector}).click()
    await receiptPage.getByRole('option', {name: /TEST-OLD-8/}).click()
    await receiptPage.locator('.el-table').getByRole('spinbutton', {name: '本次分配金额'}).fill('30')
    await receiptPage.keyboard.press('Tab')
    await receiptPage.getByRole('button', {name: '刷新', exact: true}).click()
    await receiptPage.getByText('50.00', {exact: true}).waitFor()
    assert.match(await receiptPage.locator('.el-select').filter({has: selector}).innerText(), /TEST-OLD-8/)
    await receiptPage.locator('.fields-grid .el-form-item').filter({hasText: '本次回款金额'}).getByRole('spinbutton').fill('30')
    await receiptPage.keyboard.press('Tab')
    await receiptPage.locator('.fields-grid .el-select').scrollIntoViewIfNeeded()
    await receiptPage.locator('.fields-grid .el-select').click()
    try {
      await receiptPage.getByRole('option', {name: 'T/T', exact: true}).click({timeout: 5000})
    } catch (error) {
      await receiptPage.screenshot({path: output + '/payment-error-' + width + '.png', fullPage: true})
      console.log(JSON.stringify({width, paymentErrors, text: await receiptPage.locator('body').innerText()}))
      throw error
    }
    await receiptPage.locator('input[type=file]').setInputFiles({name: 'payment.png', mimeType: 'image/png', buffer: png})
    await receiptPage.locator('textarea').fill('本笔实际到账分配到旧信用批次')
    await receiptPage.screenshot({path: output + '/credit-payment-' + width + '.png', fullPage: true})
    await receiptPage.getByRole('button', {name: '创建回款单', exact: true}).click()
    await receiptPage.getByRole('dialog').waitFor({state: 'hidden'})
    assert.equal(payments.length, 1)
    assert.equal(payments[0].allocations[0].settlement_id, 8)
    assert.equal(payments[0].allocations[0].balance_version, '8'.repeat(64))
    assert.deepEqual(paymentErrors, [])
    results.push({width, creditCreates: writes.length, paymentCreates: payments.length, selectedBatch: 8, refreshPreservedSelection: true})
    await receiptContext.close()
  }
  await writeFile(output + '/results.json', JSON.stringify({syntheticApi: true, results}, null, 2))
  console.log(JSON.stringify(results))
} finally { await browser.close() }
