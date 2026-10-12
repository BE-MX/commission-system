/** Run against scripts/qa_domestic_delivery.py and the local real-component Vite harness. */
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright')
const evidence = fileURLToPath(new URL('../tmp/domestic-delivery-evidence/', import.meta.url))
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const screen = async name => page.screenshot({ path: evidence + name + '.png', fullPage: true })
async function clickWrite(name, path) {
  const response = page.waitForResponse(r => r.url().includes(path) && r.request().method() === 'POST').catch(() => null)
  await page.getByRole('button', { name, exact: true }).last().click()
  const result = await response
  assert(result, "Expected write response for " + path)
  assert.equal(result.status(), 200, await result.text())
  await page.waitForLoadState('networkidle')
  await page.waitForFunction(() => { let p = document.querySelector('.delivery-dialog').__vueParentComponent; while(p && p.type.__name !== 'DomesticDeliveryDialog') p=p.parent; return !p.setupState.saving && !p.setupState.loading })
  return result.json()
}
try {
  await page.goto('http://127.0.0.1:8766/tmp/domestic-delivery-qa/index.html')
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: '从订单页打开', exact: true }).click()
  await page.waitForLoadState('networkidle')
  await page.locator('.delivery-toolbar .el-select').first().click()
  await page.getByRole('option', { name: '验收客户', exact: true }).click()
  await page.waitForLoadState('networkidle')
  await page.getByRole('tab', { name: '创建发货批次' }).click()
  const height = await page.locator('.delivery-picker .el-table__body tr').first().evaluate(e => e.getBoundingClientRect().height)
  assert(height >= 32 && height <= 36, 'compact row height: ' + height)
  const footer = await page.locator('.delivery-footer').boundingBox()
  assert(footer.y + footer.height <= 1000, 'footer must remain visible')
  await screen('picker-desktop')
  await page.getByRole('spinbutton', { name: '顾客01 本次发货数量', exact: true }).fill('2')
  await page.getByRole('spinbutton', { name: '顾客01 本次发货数量', exact: true }).press('Tab')
  await page.locator('.delivery-dialog .el-pagination .btn-next').click()
  assert.match(await page.locator('.delivery-footer').innerText(), /已选 1 条 · 2 件/)
  await page.getByPlaceholder('搜索顾客、订单号、产品规格').fill('张女士')
  await page.getByRole('spinbutton', { name: '张女士 本次发货数量', exact: true }).fill('3')
  await page.getByRole('spinbutton', { name: '张女士 本次发货数量', exact: true }).press('Tab')
  assert.match(await page.locator('.delivery-footer').innerText(), /已选 2 条 · 5 件/)
  await screen('guest-search')
  const first = (await clickWrite('登记发货批次', '/api/domestic/shipments')).data
  assert.equal(first.total_amount, 500)
  assert.equal(first.items.length, 2)
  assert.equal(new Set(first.items.map(row => row.domestic_no)).size, 2)
  await page.getByRole('button', { name: '确认收货', exact: true }).click()
  await clickWrite('确认收货', '/receive')
  // A second delivery from the same line, with explicitly selected physical units.
  await page.getByRole('tab', { name: '创建发货批次' }).click()
  await page.getByPlaceholder('搜索顾客、订单号、产品规格').fill('顾客01')
  await page.getByRole('button', { name: '指定件号', exact: true }).click()
  const unitDialog = page.getByRole('dialog').filter({ hasText: '指定实际发货件号' })
  for (const code of ['A1-03', 'A1-05', 'A1-06']) await unitDialog.getByText(code, { exact: true }).click()
  await page.getByRole('button', { name: '使用这些件号', exact: true }).click()
  const second = (await clickWrite('登记发货批次', '/api/domestic/shipments')).data
  assert.deepEqual(second.items[0].unit_codes, ['A1-03', 'A1-05', 'A1-06'])
  // First cash receipt: 300 received, 200 allocated, 100 explicitly unallocated.
  const firstRow = page.locator('.delivery-dialog .el-table__body tr').filter({ hasText: first.shipment_no }).first()
  await firstRow.getByRole('button', { name: '登记收款', exact: true }).click()
  let dialog = page.getByRole('dialog').filter({ hasText: '登记货款收款（提交审核）' })
  await dialog.getByRole('spinbutton').first().fill('300')
  await dialog.getByRole('spinbutton').first().press('Tab')
  const firstAlloc = dialog.locator('.el-table__body tr').filter({ hasText: first.shipment_no })
  await firstAlloc.getByRole('spinbutton').fill('200'); await firstAlloc.getByRole('spinbutton').press('Tab')
  await page.waitForFunction(() => { let p = document.querySelector('.delivery-dialog').__vueParentComponent; while (p && p.type.__name !== 'DomesticDeliveryDialog') p=p.parent; return p.setupState.allocationTotal === 200 })
  await dialog.locator('input[type="file"]').setInputFiles({ name: 'voucher.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nQA voucher') })
  await screen('receipt-review')
  await clickWrite('提交收款审核', '/receipts')
  assert.equal((await (await page.request.get('http://127.0.0.1:8767/qa/readback')).json()).receipt_ledger_rows, 0)
  assert.equal((await page.request.post('http://127.0.0.1:8767/qa/approve-latest')).status(), 200)
  await page.getByRole('button', { name: '刷新', exact: true }).click(); await page.waitForLoadState('networkidle')
  await page.getByRole('tab', { name: '收款记录' }).click()
  await page.getByRole('button', { name: '核销到批次', exact: true }).click()
  dialog = page.getByRole('dialog').filter({ hasText: '核销已入账货款' })
  const targetRow = dialog.locator('.el-table__body tr').filter({ hasText: first.shipment_no })
  await targetRow.getByRole('spinbutton').fill('300'); await targetRow.getByRole('spinbutton').press('Tab')
  await clickWrite('保存核销', '/allocate')
  // Next cash receipt settles two separate delivery batches.
  await page.getByRole('button', { name: '登记收款', exact: true }).click()
  dialog = page.getByRole('dialog').filter({ hasText: '登记货款收款（提交审核）' })
  await dialog.getByRole('spinbutton').first().fill('400'); await dialog.getByRole('spinbutton').first().press('Tab')
  for (const number of [first.shipment_no, second.shipment_no]) {
    const row = dialog.locator('.el-table__body tr').filter({ hasText: number })
    await row.getByRole('spinbutton').fill('200'); await row.getByRole('spinbutton').press('Tab')
  }
  await dialog.locator('input[type="file"]').setInputFiles({ name: 'voucher2.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nQA second voucher') })
  await clickWrite('提交收款审核', '/receipts')
  assert.equal((await page.request.post('http://127.0.0.1:8767/qa/approve-latest')).status(), 200)
  await page.getByRole('button', { name: '刷新', exact: true }).click(); await page.waitForLoadState('networkidle')
  await page.getByRole('tab', { name: '发货批次', exact: true }).click()
  const readback = await (await page.request.get('http://127.0.0.1:8767/qa/readback')).json()
  assert.deepEqual(readback, { shipped_units: 8, receipt_ledger_rows: 2 })
  const delivery = (await (await page.request.get('http://127.0.0.1:8767/api/domestic/customers/1/delivery')).json()).data
  assert.equal(delivery.summary.received_unpaid_amount, 0)
  assert.equal(delivery.summary.transit_unpaid_amount, 100)
  assert.equal(delivery.summary.unallocated_receipts, 0)
  await screen('reconciliation-desktop')
  const downloadEvent = page.waitForEvent('download')
  await page.locator('.delivery-dialog .el-table__body tr').filter({ hasText: first.shipment_no }).first().getByRole('button', { name: '导出清单', exact: true }).click()
  const download = await downloadEvent; await download.saveAs(evidence + 'shipment-export.csv')
  assert.match(await fs.readFile(evidence + 'shipment-export.csv', 'utf8'), /张女士/)
  assert.deepEqual(errors, [])
  const result = { row_height_px: height, cross_page_selection: true, explicit_units: true,
    cross_order_batch: true, partial_receipt: true, later_allocation: true, cross_batch_receipt: true,
    export_verified: true, readback, console_page_errors: errors }
  await fs.writeFile(evidence + 'verification.json', JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} catch (error) {
  await screen('failure')
  console.error(error)
  process.exitCode = 1
} finally {
  await browser.close()
}
