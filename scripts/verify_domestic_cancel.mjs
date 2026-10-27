/** Isolated real-component check; start qa_domestic_delivery.py with a fresh DB first. */
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright')
const evidence = fileURLToPath(new URL('../tmp/domestic-delivery-evidence/', import.meta.url))
await fs.mkdir(evidence, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' })
const page = await browser.newPage({ viewport: { width: 1690, height: 980 } })
const errors = [], writes = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()) })
const idle = async () => {
  await page.waitForLoadState('networkidle')
  await page.waitForFunction(() => !document.querySelector('.delivery-dialog .el-loading-mask'))
}
const history = async () => (await (await page.request.get('http://127.0.0.1:8766/api/domestic/customers/1/delivery')).json()).data
async function createBatch() {
  await page.getByRole('tab', { name: '创建发货批次', exact: true }).click()
  const quantity = page.getByRole('spinbutton', { name: '顾客01 本次发货数量', exact: true })
  await quantity.fill('2'); await quantity.press('Tab')
  const response = page.waitForResponse(r => r.url().endsWith('/shipments') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '登记发货批次', exact: true }).click()
  assert.equal((await response).status(), 200)
  await idle()
}
try {
  await page.goto('http://127.0.0.1:8766/tmp/domestic-delivery-qa/index.html')
  await page.getByRole('button', { name: '从客户页打开', exact: true }).click()
  await idle()
  await createBatch()
  const before = await history()
  assert.equal(before.items.length, 1)
  const original = before.items[0]
  const cancel = page.getByRole('button', { name: '取消批次', exact: true })
  await cancel.click()
  assert.match(await page.locator('.el-message-box').innerText(), /账户余额不变/)
  await page.getByRole('button', { name: '保留批次', exact: true }).click()
  assert.equal(writes.filter(url => url.endsWith('/cancel')).length, 0)
  await cancel.click()
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.el-message-box')).opacity === '1')
  await page.screenshot({ path: evidence + 'cancel-confirm.png', fullPage: true })
  const response = page.waitForResponse(r => r.url().endsWith('/cancel') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '确定取消批次', exact: true }).click()
  assert.equal((await response).status(), 200)
  await idle()
  await page.getByText('已取消', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '确认收货', exact: true }).count(), 0)
  assert.equal(await page.getByRole('button', { name: '取消批次', exact: true }).count(), 0)
  const after = await history()
  assert(after.items[0].cancelled_at)
  assert.deepEqual(after.items[0].items, original.items)
  assert.equal(after.summary.transit_unpaid_amount, 0)
  assert.equal(after.summary.unshipped_amount, before.summary.unshipped_amount + 200)
  // The compact table's button wrapper has zero content width; its visible icon
  // is the actual pointer target, matching the existing expand affordance.
  await page.locator('.el-table__expand-icon .el-icon').first().click()
  await page.screenshot({ path: evidence + 'cancelled-desktop.png', fullPage: true })
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出清单', exact: true }).click()
  const csv = await download
  await csv.saveAs(evidence + 'cancelled-batch.csv')
  assert.match(await fs.readFile(evidence + 'cancelled-batch.csv', 'utf8'), new RegExp(original.shipment_no))
  await createBatch()
  const resent = await history()
  assert.equal(resent.items.length, 2)
  assert.deepEqual(resent.items[0].items[0].unit_codes, original.items[0].unit_codes)
  assert.equal(resent.summary.transit_unpaid_amount, 200)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '取消批次', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: evidence + 'cancel-mobile.png', fullPage: true })
  assert.deepEqual(errors, [])
  const result = { passed: true, checks: ['dismiss without write', 'confirm cancellation', 'history retained', 'summary restored', 'CSV export', 'same units reshipped', '390px action reachable'], writes: writes.length, errors }
  await fs.writeFile(evidence + 'cancel-result.json', JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} finally { await browser.close() }
