import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
const require = createRequire(import.meta.url)
const { chromium } = require(process.argv[2] || 'playwright')

const base = process.argv[3] || 'http://127.0.0.1:3188'
const output = process.argv[4] || '../tmp/receipt-delete-ui'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const evidence = []

async function scenario({ invoice = false, manage = false, mobile = false, keyboard = false, unknown = false, revoked = false, stale = false } = {}) {
  const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 900 },
    reducedMotion: mobile ? 'reduce' : 'no-preference' })
  const errors = [], posts = []
  page.on('pageerror', error => errors.push(String(error)))
  const row = { id: 11, invoice_id: 1, receipt_no: 'HK-DELETE', invoice_no: '翟 #261027', source: 'auto', purpose: 'ordinary',
    status: 'active', sync_status: 'synced', xiaoman_receipt_id: '701', version: 1, amount: '3282.54', bank_charge: '156.31',
    currency: 'USD', attachment_ids: ['proof'], attachments: [], attachment_count: 1, remark: '', logs: [],
    shipment_applications: [], collection_date: '2026-10-14', payment_type: 'Other', deletion_pending: false }
  let held = null
  await page.route(`${base}/api/**`, async route => {
    const path = new URL(route.request().url()).pathname
    let data
    if (path === '/api/receipts') {
      data = { items: [row], total: 1, delivery_enabled: true, presale_delivery_enabled: false }
    } else if (path === '/api/receipts/11') {
      data = row
    } else if (path === '/api/receipts/11/deletion') {
      if (route.request().method() === 'GET') {
        data = { receipt_id: 11, receipt_no: row.receipt_no, invoice_no: row.invoice_no, amount: row.amount,
          bank_charge: row.bank_charge, net_amount: '3126.23', currency: 'USD', remote_id: '701',
          remote_state: 'active', expected_version: 'a'.repeat(64), can_delete: !row.deletion_pending,
          can_resume: row.deletion_pending, reason: row.deletion_pending ? '回款资料错误，重新提交' : '' }
        if (stale) { held = { route, data }; return }
      } else {
        const body = route.request().postDataJSON()
        assert.equal(body.confirmed, true)
        assert.equal(body.expected_version, 'a'.repeat(64))
        posts.push(body)
        row.version++
        if (unknown && posts.length === 1) {
          row.deletion_pending = true; row.sync_status = 'uncertain'
          data = { status: 'uncertain', message: '原删除结果仍待核对，请继续核验；系统不会重复发送删除', receipt: row }
        } else {
          row.status = 'remote_deleted'; row.sync_status = 'synced'; row.deletion_pending = false
          data = { status: 'deleted', message: '原回款已删除，刷新资金汇总后可重新登记回款', receipt: row }
        }
      }
    } else if (path === '/api/receipts/invoice-summary/1') {
      data = { initial_receipt: row, balance: row.deletion_pending ? null : {
        total_amount: '3282.54', registered_amount: row.status === 'active' ? '3282.54' : '0',
        effective_amount: row.status === 'active' ? '3282.54' : '0', pending_amount: '0',
        remaining_amount: row.status === 'active' ? '0' : '3282.54' },
        action_blocked_reason: row.deletion_pending ? '原回款删除待核验' : null }
    } else {
      await route.abort(); throw new Error(`Unexpected request: ${path}`)
    }
    await route.fulfill({ status: 200, json: { code: 200, data } })
  })
  await page.goto(`${base}/tests/receiptDeleteHarness.html${manage ? '?manage' : invoice ? '?invoice' : ''}`)
  if (manage) await page.getByRole('button', { name: 'HK-DELETE', exact: true }).click()
  await page.getByRole('button', { name: '删除回款单', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '删除回款单', exact: true })
  if (stale) {
    await page.waitForFunction(() => window.receipt.id === 11)
    while (!held) await page.waitForTimeout(20)
    await page.evaluate(() => window.switchReceipt())
    await held.route.fulfill({ status: 200, json: { code: 200, data: held.data } }).catch(() => {})
    await dialog.waitFor({ state: 'hidden', timeout: 2000 })
    assert.equal(await dialog.isVisible(), false)
  } else {
    await dialog.getByText('USD 3,282.54', { exact: true }).waitFor()
    const bounds = await dialog.boundingBox()
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= page.viewportSize().width + 1, 'Dialog fits the viewport')
    const submit = dialog.getByRole('button', { name: '确认删除', exact: true })
    assert.equal(await submit.isDisabled(), true)
    await dialog.getByRole('textbox', { name: '删除原因' }).fill('回款资料错误，重新提交')
    if (keyboard) {
      await dialog.getByRole('checkbox').focus()
      await page.keyboard.press('Space')
    } else await dialog.getByText('确认只删除以上回款单，保留原凭证与审计', { exact: true }).click()
    assert.equal(await dialog.getByRole('checkbox').isChecked(), true)
    assert.equal(await submit.isEnabled(), true)
    if (revoked) {
      await page.evaluate(() => window.revoke())
      await dialog.waitFor({ state: 'hidden', timeout: 2000 })
      assert.equal(await dialog.isVisible(), false)
      assert.equal(posts.length, 0)
    } else {
      await page.screenshot({ path: path.join(output, `${manage ? 'management' : invoice ? 'invoice' : 'receipt'}-${mobile ? 'mobile' : 'desktop'}-${unknown ? 'resume' : 'delete'}.png`), fullPage: true })
      await submit.click()
      await dialog.waitFor({ state: 'hidden' })
      if (unknown) {
        await page.getByRole('button', { name: '继续核验删除', exact: true }).click()
        await dialog.getByRole('button', { name: '继续核验', exact: true }).waitFor()
        assert.equal(await dialog.getByRole('textbox', { name: '删除原因' }).isDisabled(), true)
        await dialog.getByRole('button', { name: '继续核验', exact: true }).click()
        await dialog.waitFor({ state: 'hidden' })
      }
      assert.equal(posts.length, unknown ? 2 : 1) // Second application request verifies only; backend enforces one OKKI POST.
      assert.equal(await page.getByRole('button', { name: '删除回款单', exact: true }).count(), 0)
      if (invoice) assert.equal(await page.getByRole('button', { name: '补登记回款', exact: true }).isEnabled(), true)
    }
  }
  assert.deepEqual(errors, [])
  evidence.push({ invoice, manage, mobile, keyboard, unknown, revoked, stale, applicationRequests: posts.length, pageErrors: errors })
  await page.close()
}

try {
  await scenario()
  await scenario({ keyboard: true })
  await scenario({ invoice: true })
  await scenario({ manage: true })
  await scenario({ mobile: true, invoice: true, unknown: true })
  await scenario({ revoked: true })
  await scenario({ stale: true })
  await writeFile(path.join(output, 'results.json'), JSON.stringify(evidence, null, 2))
  process.stdout.write(JSON.stringify(evidence, null, 2) + '\n')
} finally { await browser.close() }
