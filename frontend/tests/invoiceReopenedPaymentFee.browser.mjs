import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

// Start Vite in frontend, then pass the Playwright module path and optional base URL.
const { chromium } = createRequire(import.meta.url)(process.argv[2] || 'playwright')
const base = process.argv[3] || 'http://127.0.0.1:5179'
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', route => {
  const url = new URL(route.request().url())
  return url.origin === new URL(base).origin && !url.pathname.startsWith('/api/') ? route.continue() : route.abort()
})
const fixture = {
  invoice_no: 'SYNTHETIC-FEE', order_type: 'stock', customer_id: 'complete', customer_name: 'complete',
  express_channel: 'FEDEX9610', internal_payment_method: '大莱莎信保（便捷发货）',
  alibaba_order_no: '00123456789012345', shipping_fee: 226.57,
  surcharge_amount: 51.80, internal_accessory: 0,
  items: [{ id: 10, product_kind: 'hair', item_type: 'stock', product_id: 1, sku_id: 1,
    product_name: 'Test product', quantity: 1, price_per_piece: 1500, total_price: 1500 }],
  receipt_draft: { amount: 100, bank_charge: 4.25, collection_date: '2026-11-26', status: 'draft', attachment_ids: [], remark: '' },
}
try {
  await page.goto(`${base}/tests/fixtures/invoice-contact-freight/index.html`)
  await page.waitForFunction(() => window.invoiceTest?.editor)
  await page.evaluate(async invoice => { invoiceTest.seed(invoice); await invoiceTest.editor.openEdit(7) }, fixture)
  const drawer = page.locator('.el-drawer:visible')
  const field = label => drawer.locator('.el-form-item').filter({ has: page.locator('label', { hasText: new RegExp(`^${label}$`) }) })
  const fee = field('手续费').locator('input')
  const freight = drawer.locator('.pane-main .el-form-item').filter({ has: page.locator('label', { hasText: /^运费$/ }) }).locator('input')
  const method = field('付款方式').locator('.el-select')
  const choose = async label => { await method.click(); await page.getByRole('option', { name: label, exact: true }).click() }
  await fee.waitFor()
  assert.equal(await fee.inputValue(), '51.80')
  await choose('PayPal')
  assert.equal(await fee.inputValue(), '86.33')
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await page.waitForFunction(() => invoiceTest.saved.length === 1)
  assert.equal((await page.evaluate(() => invoiceTest.saved[0])).surcharge_amount, 86.33)
  await page.evaluate(() => invoiceTest.editor.openEdit(7))
  await fee.waitFor()
  assert.equal(await fee.inputValue(), '86.33')
  await freight.fill('426.57'); await freight.press('Tab')
  await page.waitForFunction(() => invoiceTest.editor.form.surcharge_amount === 96.33, null, { timeout: 3000 })
  assert.equal(await fee.inputValue(), '96.33')
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await page.waitForFunction(() => invoiceTest.saved.length === 2)
  const saved = await page.evaluate(() => invoiceTest.saved[1])
  assert.equal(saved.surcharge_amount, 96.33)
  assert.equal(Number(saved.receipt_draft.bank_charge), 4.25)
  await page.evaluate(() => invoiceTest.editor.openEdit(7))
  await fee.waitFor()
  assert.equal(await fee.inputValue(), '96.33')
  const price = drawer.locator('.line-price-input input').first()
  await price.fill('1600'); await price.press('Tab')
  await page.waitForFunction(() => invoiceTest.editor.form.surcharge_amount === 101.33)
  await choose('大莱莎信保（便捷发货）')
  assert.equal(await fee.inputValue(), '60.80')
  await choose('PayPal')
  assert.equal(await fee.inputValue(), '101.33')
  await drawer.getByRole('button', { name: '保存并同步', exact: true }).first().click()
  await page.waitForFunction(() => invoiceTest.requests.some(request => request.url.endsWith('/sync')), null, { timeout: 5000 })
  assert.equal(await page.evaluate(() => Number(invoiceTest.editor.form.receipt_draft.bank_charge)), 4.25)
  // A historical fee that does not match the formula is treated as a manual value.
  await page.setViewportSize({ width: 390, height: 900 })
  await page.reload()
  await page.waitForFunction(() => window.invoiceTest?.editor)
  await page.evaluate(async invoice => {
    invoiceTest.seed({ ...invoice, express_channel: 'FEDEX普货', internal_payment_method: 'PayPal', surcharge_amount: 50.67 })
    await invoiceTest.editor.openEdit(7)
  }, fixture)
  await fee.waitFor()
  assert.equal(await fee.inputValue(), '50.67')
  await freight.fill('426.57'); await freight.press('Tab')
  assert.equal(await fee.inputValue(), '50.67')
  const recalculate = drawer.getByRole('button', { name: '按费率重算', exact: true })
  await recalculate.scrollIntoViewIfNeeded()
  const box = await recalculate.boundingBox()
  assert.ok(box && box.x >= 0 && box.x + box.width <= 390)
  await recalculate.focus(); await page.keyboard.press('Enter')
  assert.equal(await fee.inputValue(), '96.33')
  await freight.fill('526.57'); await freight.press('Tab')
  await page.waitForFunction(() => invoiceTest.editor.form.surcharge_amount === 101.33)
  await recalculate.waitFor({ state: 'hidden' })
  await fee.fill('77'); await fee.press('Tab')
  await freight.fill('626.57'); await freight.press('Tab')
  assert.equal(await fee.inputValue(), '77.00')
  assert.deepEqual(errors, [])
  console.log('PASS: saved and reopened fee follows freight and product price; manual fee retained; mobile keyboard recalculation restores automatic mode; mocked sync and receipt fee independence')
} finally { await browser.close() }
