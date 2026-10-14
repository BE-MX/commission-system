import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.argv[2])
const base = process.argv[3]
const output = process.argv[4]
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const results = []
try {
  for (const [width, height] of [[1440, 900], [1366, 768], [1024, 600], [390, 844]]) {
    const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce' })
    const page = await context.newPage()
    const errors = [], requests = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== new URL(base).origin) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      assert.equal(request.method(), 'GET', 'Layout test must never write business data')
      let data = {}
      if (url.pathname === '/api/v1/tracking/stats') data = { total: 120, in_transit: 40, customs: 10, delivered: 60, exception: 10 }
      if (url.pathname === '/api/v1/tracking/shipments') {
        const number = Number(url.searchParams.get('page') || 1)
        const size = Number(url.searchParams.get('page_size') || 20)
        requests.push({ number, size })
        data = { total: 120, items: Array.from({ length: size }, (_, i) => ({
          id: (number - 1) * size + i + 1, waybill_no: `TEST-${number}-${i + 1}`,
          carrier_name: 'DHL', receiver_name: 'Layout fixture', receiver_country: 'US',
          current_status: 'in_transit', current_status_text: 'In transit', is_active: true,
        })) }
      }
      return route.fulfill({ json: { code: 200, message: 'ok', data } })
    })
    await page.goto(base + '/tests/trackingPaginationHarness.html')
    try {
      await page.getByRole('button', { name: 'TEST-1-1', exact: true }).waitFor({ timeout: 10000 })
    } catch (error) {
      await page.screenshot({ path: `${output}/load-failure.png` })
      console.error(JSON.stringify({ errors, requests, text: await page.locator('body').innerText() }))
      throw error
    }
    async function reachableNext(mode) {
      const next = page.locator('.tracking-panel .pager .btn-next')
      const fullscreen = mode === 'fullscreen'
      const scroller = page.locator(fullscreen ? '.tracking-panel' : '.main-content')
      await scroller.evaluate(element => {
        if (['auto', 'scroll'].includes(getComputedStyle(element).overflowY)) element.scrollTop = element.scrollHeight
      })
      await page.waitForTimeout(100)
      const hit = await next.evaluate(button => {
        const rect = button.getBoundingClientRect()
        const target = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)
        return button.contains(target)
      })
      await page.screenshot({ path: `${output}/${width}-${height}-${mode}.png` })
      assert.equal(hit, true, `${width}x${height} ${mode}: pagination is clipped or covered`)
      await next.click({ timeout: 3000 })
    }
    await reachableNext('normal')
    await page.getByRole('button', { name: 'TEST-2-1', exact: true }).waitFor()
    // Page-size changes must still leave the pager accessible with a taller table.
    await page.locator('.pager .el-select').click()
    await page.getByRole('option', { name: '100条/页', exact: true }).click()
    await page.waitForFunction(() => document.querySelectorAll('.tracking-panel .el-table__body tbody tr').length === 100)
    await reachableNext('size-100')
    await page.getByRole('button', { name: 'TEST-2-1', exact: true }).waitFor()
    await page.getByRole('button', { name: '全屏', exact: true }).scrollIntoViewIfNeeded()
    await page.getByRole('button', { name: '全屏', exact: true }).click()
    await page.locator('.tracking-panel.table-card--fullscreen').waitFor()
    const previous = page.locator('.tracking-panel .pager .btn-prev')
    await page.locator('.tracking-panel').evaluate(element => {
      if (['auto', 'scroll'].includes(getComputedStyle(element).overflowY)) element.scrollTop = element.scrollHeight
    })
    assert.ok(['auto', 'scroll'].includes(await page.locator('.tracking-panel').evaluate(element => getComputedStyle(element).overflowY)), 'Fullscreen content must allow user scrolling')
    await previous.click({ timeout: 3000 })
    await page.getByRole('button', { name: 'TEST-1-1', exact: true }).waitFor()
    await reachableNext('fullscreen')
    await page.keyboard.press('Escape')
    await page.locator('.tracking-panel:not(.table-card--fullscreen)').waitFor()
    assert.deepEqual(errors, [])
    assert.ok(requests.some(item => item.number === 2 && item.size === 100))
    results.push({ width, height, normal: 'passed', size100: 'passed', fullscreen: 'passed', errors })
    await context.close()
  }
  await writeFile(output + '/results.json', JSON.stringify(results, null, 2))
  console.log(JSON.stringify(results))
} finally {
  await browser.close()
}
