import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), { chromium } = require(process.argv[2])
const base = process.argv[3], red = process.argv[4] === '--red'
const browser = await chromium.launch({ headless: true })
const results = []
await mkdir('../tmp/receipt-register-http', { recursive: true })
try {
  for (const roles of [[], ['super_admin']]) {
    const page = await browser.newPage()
    const errors = [], requests = [], submissions = []
    let registered = false
    page.on('pageerror', error => errors.push(error.message))
    const receipt = { id: 11, invoice_id: 1, receipt_no: 'HK-OLD', source: 'auto', purpose: 'ordinary',
      status: 'remote_deleted', sync_status: 'synced', version: 7, amount: '3282.54', bank_charge: '156.31',
      currency: 'USD', attachments: [], xiaoman_receipt_id: '701' }
    await page.route(base + '/api/**', async route => {
      const url = new URL(route.request().url()), path = url.pathname
      requests.push({ path, method: route.request().method() })
      let data
      if (path === '/api/receipts/invoice-summary/1') data = { initial_receipt: receipt,
        balance: { total_amount: '3004.29', remaining_amount: registered ? '2904.29' : '3004.29', registered_amount: registered ? '100' : '0', effective_amount: '0',
          pending_amount: '0', version: 'a'.repeat(64) }, action_blocked_reason: null }
      else if (path === '/api/receipts/types') data = ['Other']
      else if (path === '/api/receipts/attachments' && route.request().method() === 'POST') data = { id: 'b'.repeat(32), filename: 'proof.png' }
      else if (path === '/api/receipts' && route.request().method() === 'POST') {
        submissions.push(route.request().postDataJSON())
        if (submissions.length === 1) {
          await route.fulfill({ status: 503, json: { detail: 'Simulated unconfirmed response' } }); return
        }
        registered = true
        data = { id: 12, invoice_id: 1, source: 'manual', amount: '100', bank_charge: '0', status: 'active', sync_status: 'pending' }
      }
      else { await route.abort(); throw new Error(`Unexpected business call ${path}`) }
      await route.fulfill({ status: 200, json: { code: 200, data } })
    })
    await page.goto(base + '/tests/receiptDeleteHarness.html?invoice')
    await page.evaluate(roles => { window.setRoles?.(roles) }, roles)
    const environment = await page.evaluate(() => ({ secure: isSecureContext,
      randomUUID: typeof crypto.randomUUID, getRandomValues: typeof crypto.getRandomValues }))
    assert.equal(environment.secure, false)
    assert.equal(environment.randomUUID, 'undefined')
    await page.getByRole('button', { name: '补登记回款', exact: true }).click()
    if (red) {
      await page.waitForFunction(() => !!document.querySelector('.invoice-funds'))
      await page.waitForTimeout(150)
      assert.ok(errors.some(error => error.includes('crypto.randomUUID is not a function')))
      assert.equal(requests.filter(call => call.method === 'POST').length, 0)
    } else {
      await page.getByRole('dialog', { name: '补登记实际回款', exact: true }).waitFor()
      assert.deepEqual(errors, [])
      assert.equal(requests.filter(call => call.method === 'POST').length, 0)
      await page.screenshot({ path: '../tmp/receipt-register-http/registration-dialog.png', fullPage: true })
      const dialog = page.getByRole('dialog', { name: '补登记实际回款', exact: true })
      await dialog.getByRole('spinbutton').first().fill('100')
      await dialog.locator('.el-select').click()
      await page.getByRole('option', { name: 'Other', exact: true }).click()
      await dialog.locator('input[type=file]').setInputFiles({ name: 'proof.png', mimeType: 'image/png',
        buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jW1kAAAAASUVORK5CYII=', 'base64') })
      const submit = dialog.getByRole('button', { name: '登记回款', exact: true })
      await submit.click()
      await dialog.getByText('Simulated unconfirmed response', { exact: true }).waitFor()
      assert.equal(submissions.length, 1)
      assert.equal(await dialog.getByRole('spinbutton').first().inputValue(), '100.00')
      await submit.click()
      await dialog.waitFor({ state: 'hidden' })
      assert.equal(submissions.length, 2)
      assert.match(submissions[0].request_key, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
      assert.deepEqual(submissions[1], submissions[0])
      assert.deepEqual(errors, [])
    }
    results.push({ roles, environment, errors, requests, submissions })
    await page.close()
  }
  await writeFile('../tmp/receipt-register-http/' + (red ? 'before' : 'after') + '.json', JSON.stringify(results, null, 2))
  process.stdout.write(JSON.stringify(results, null, 2) + '\n')
} finally { await browser.close() }
