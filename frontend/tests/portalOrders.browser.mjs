import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const id = '12345678-1234-1234-1234-123456789abc'
let failDetail = false, detailCalls = 0, failList = false, piStatus = 'voided', failures = [], calls = 0
page.on('pageerror', error => failures.push(error.message))
await context.addInitScript(() => { localStorage.setItem('ark_access_token', 'synthetic-browser-test'); sessionStorage.setItem('leshine_welcome_shown_session', '1') })
await context.route('**/api/**', async route => {
  const url = new URL(route.request().url()); calls++
  let data = {}
  if (url.pathname === '/api/auth/me') return route.fulfill({ json: { id: 5, name: 'Portal reviewer', username: 'portal-test', roles: [], permissions: ['portal_order:read'] } })
  if (url.pathname === '/api/auth/refresh') return route.fulfill({ json: { access_token: 'synthetic-browser-test' } })
  if (url.pathname === '/api/portal/admin/v1/orders') {
    if (failList) return route.fulfill({ status: 503, json: { code: 503, message: 'unavailable', data: { error_code: 'SERVICE_UNAVAILABLE' } } })
    data = { items: [{ request_id: id, request_no: 'REQ-QA-001', customer_po: 'QA-PO', status: 'invoice_created', submitted_at: '2026-09-30T09:00:00', currency: 'USD', product_amount: '100.00', total_amount: '120.00' }], total: 1 }
  } else if (url.pathname.endsWith(`/orders/${id}`)) {
    detailCalls++
    if (failDetail) return route.fulfill({ status: 404, json: { code: 404, message: 'not allowed', data: { error_code: 'RESOURCE_NOT_FOUND' } } })
    data = { request_id: id, request_no: 'REQ-QA-001', status: 'invoice_created', submitted_at: '2026-09-30T09:00:00', currency: 'USD', product_amount: '100.00', total_amount: '120.00', fees: { status: 'confirmed', shipping_amount: '20.00', packaging_amount: '0.00', surcharge_amount: '0.00' }, proposal: { accepted: true, expired: true }, pi_amendment: { status: piStatus }, delivery: { contact_name: 'QA buyer', country_code: 'US', address_line1: 'Synthetic address' }, items: [{ line_key: 'line1', quantity: 2, display_snapshot: { model_name: 'QA Hair', color_name: 'Natural', customer_sku: 'QA-SKU', length: '20 in', weight: '100 g', unit: 'piece' }, unit_price: '50.0000', discount_amount: '0.00', line_amount: '100.00' }], customer_safe_timeline: [{ event: 'order.pi_voided', at: '2026-09-30T10:00:00' }] }
  }
  return route.fulfill({ json: { code: 200, message: 'ok', data } })
})
try {
  await page.goto(`http://127.0.0.1:3211/portal/orders?request=${id}`)
  await page.getByRole('cell', { name: 'REQ-QA-001', exact: true }).waitFor()
  await page.getByText('PI 已作废。下方为最近发布的历史快照。', { exact: true }).waitFor()
  assert.equal(await page.getByText('当前提案已过期，建 PI 前需要重新确认。').count(), 0)
  await page.waitForFunction(() => { const r = document.querySelector('.detail-drawer')?.getBoundingClientRect(); return r && Math.abs(r.right - innerWidth) < 1 }); await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT || '.'}/admin-detail-1440.png`, fullPage: true })
  await page.keyboard.press('Escape'); await page.locator('.detail-drawer').waitFor({ state: 'hidden' })
  piStatus = 'withdrawn'
  await page.getByRole('button', { name: '详情', exact: true }).click()
  await page.getByText('PI 已撤回，修改内容尚未重新发布。下方为最近发布的历史快照。', { exact: true }).waitFor()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => { const r = document.querySelector('.detail-drawer')?.getBoundingClientRect(); return r && Math.abs(r.right - innerWidth) < 1 }); await page.screenshot({ animations: 'disabled', path: `${process.env.PORTAL_QA_OUTPUT || '.'}/admin-detail-390.png`, fullPage: true })
  const drawer = page.locator('.detail-drawer')
  assert.ok(await drawer.evaluate(el => el.scrollWidth <= el.clientWidth + 1))
  await page.keyboard.press('Escape'); await page.locator('.detail-drawer').waitFor({ state: 'hidden' })
  failList = true
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await page.getByText('暂时无法读取数据，请重试。', { exact: true }).waitFor()
  assert.equal(await page.getByRole('cell', { name: 'REQ-QA-001', exact: true }).count(), 0)
  failList = false; failDetail = true
  await page.reload()
  await page.getByText('请求不存在或已不在当前授权范围内。', { exact: true }).waitFor()
  assert.equal(await page.getByText('QA buyer', { exact: true }).count(), 0)
  const priorDetailCalls = detailCalls
  await page.goto('http://127.0.0.1:3211/portal/orders?request=invalid')
  await page.getByRole('cell', { name: 'REQ-QA-001', exact: true }).waitFor()
  assert.equal(await page.locator('.detail-drawer:visible').count(), 0)
  assert.equal(detailCalls, priorDetailCalls)
  assert.deepEqual(failures, [])
  console.log(JSON.stringify({ status: 'pass', scenarios: ['notification link opens authorized detail', 'notification scope denial clears data', 'invalid request link ignored', 'scoped list', 'voided PI', 'published proposal expiry', 'withdrawn PI', 'mobile drawer', 'failed refresh clears records'], calls }))
} finally { await browser.close() }
