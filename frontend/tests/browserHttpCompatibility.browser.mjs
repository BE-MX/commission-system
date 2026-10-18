import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const require = createRequire(import.meta.url), { chromium } = require(process.argv[2])
const base = process.argv[3], output = process.argv[4], production = process.argv[5] === '--production'
const browser = await chromium.launch({ headless: true }), results = []
await mkdir(output, { recursive: true })
try {
  if (!production) {
    const page = await browser.newPage(), errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(base + '/tests/browserHttpHarness.html')
    await page.waitForFunction(() => typeof window.newRequestKey === 'function')
    const environment = await page.evaluate(() => ({ secure: isSecureContext,
      randomUUID: typeof crypto.randomUUID, clipboard: typeof navigator.clipboard }))
    assert.deepEqual(environment, { secure: false, randomUUID: 'undefined', clipboard: 'undefined' })
    const keys = await page.evaluate(() => Array.from({ length: 1000 }, () => window.newRequestKey()))
    assert.equal(new Set(keys).size, 1000)
    for (const key of keys) assert.match(key, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    await page.locator('#original').focus()
    await page.locator('#original').evaluate(el => el.setSelectionRange(2, 6))
    await page.getByRole('button', { name: '复制', exact: true }).click()
    await page.locator('#result').filter({ hasText: 'true' }).waitFor()
    assert.deepEqual(await page.evaluate(() => [document.activeElement.id,
      document.activeElement.selectionStart, document.activeElement.selectionEnd]), ['original', 2, 6])
    await page.locator('#paste').click()
    await page.keyboard.press('Control+V')
    assert.equal(await page.locator('#paste').inputValue(), '内网复制验证 · HTTP')
    await page.evaluate(() => { document.execCommand = () => false; document.querySelector('#result').textContent = '' })
    await page.getByRole('button', { name: '复制', exact: true }).click()
    await page.locator('#result').filter({ hasText: 'false' }).waitFor()
    assert.equal(await page.locator('textarea').count(), 2)
    assert.deepEqual(errors, [])
    results.push({ scenario: 'HTTP shared UUID and actual copy/paste, denial, focus and selection', environment, errors })
    await page.close()

  }
  // The standalone mobile page must work from both dev and the production bundle.
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } }), page = await context.newPage()
  const errors = [], unexpected = [], actions = [], prompts = []
  let blocked = false
  page.on('pageerror', error => errors.push(error.message))
  page.on('dialog', async dialog => { prompts.push({ message: dialog.message(), value: dialog.defaultValue() }); await dialog.dismiss() })
  await context.addInitScript(() => localStorage.setItem('ark_access_token', 'synthetic-local-test'))
  await page.route(base + '/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    let data
    if (path === '/api/assets/1') data = { id: 1, file_name: 'Synthetic asset', file_type: 'document', tags: [], versions: [], status: 'latest' }
    else if (path === '/api/assets/1/share-link') data = { url: 'https://example.test/share/1' }
    else if (path === '/api/assets/1/actions') { actions.push(request.postDataJSON().action); data = {} }
    else { unexpected.push(path); await route.abort(); return }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto(base + '/m/#/assets/1')
  await page.getByText('Synthetic asset', { exact: true }).first().waitFor()
  assert.equal(await page.evaluate(() => isSecureContext), false)
  const copyButton = page.getByRole('button', { name: /复制链接/ })
  await copyButton.click()
  await page.getByRole('button', { name: /已复制/ }).waitFor()
  await page.waitForFunction(() => !document.querySelector('.btn-copied'))
  assert.equal(actions.filter(action => action === 'copy_link').length, 1)
  await page.evaluate(() => { document.execCommand = () => false })
  blocked = true
  await copyButton.click()
  await page.getByText('自动复制未成功，请手动复制分享链接', { exact: true }).waitFor()
  assert.equal(prompts.length, 1)
  assert.equal(prompts[0].value, 'https://example.test/share/1')
  assert.equal(actions.filter(action => action === 'copy_link').length, 1)
  assert.equal(await page.locator('.btn-copied').count(), 0)
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, [])
  await page.screenshot({ path: output + '/mobile-copy-failure.png', fullPage: true })
  results.push({ scenario: production ? 'production mobile HTTP copy' : 'dev mobile HTTP copy', blocked,
    actions, prompts, errors, unexpected })
  await context.close()
  await writeFile(output + '/results.json', JSON.stringify(results, null, 2))
  process.stdout.write(JSON.stringify(results, null, 2) + '\n')
} finally { await browser.close() }
