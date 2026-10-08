import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { captureKeyboardEvidence, createBrowserInteraction } from './keyboardInteraction.mjs'
const [origin, modulePath, executablePath, output] = process.argv.slice(2)
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
let privateInput = ''
for await (const chunk of process.stdin) privateInput += chunk.toString('utf8')
const seed = JSON.parse(privateInput); privateInput = ''
const { chromium } = createRequire(import.meta.url)(modulePath)
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath, headless: true })
const buyer = await browser.newContext({ viewport: { width: 320, height: 1000 }, reducedMotion: 'reduce' })
const page = await buyer.newPage(), interaction = createBrowserInteraction('keyboard', output)
const api = origin + '/api/portal/v1'
let releaseCatalog, firstCatalogRequest, catalogFaults = 0, catalogPasses = 0
const catalogGate = new Promise(resolve => { releaseCatalog = resolve })
const catalogRequested = new Promise(resolve => { firstCatalogRequest = resolve })
await buyer.route('**/api/portal/v1/catalog?*', async route => {
 assert.equal(route.request().method(), 'GET')
 if (catalogFaults === 0) {
  catalogFaults++; firstCatalogRequest(); await catalogGate; await route.abort('failed')
 } else { catalogPasses++; await route.continue() }
})
async function data(response, status = 200) {
 assert.equal(response.status(), status)
 const body = await response.json(); assert.equal(body.code, status); return body.data
}
try {
 await page.goto(origin + '/collection')
 await interaction.fill(page.getByLabel('Email address', { exact: true }), seed.buyerEmail, 'access-email')
 const challenged = page.waitForResponse(response => response.url() === api + '/auth/challenges' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: /Continue with email/ }), 'access-challenge')
 const challenge = await data(await challenged, 202)
 const mail = await buyer.request.get(origin + '/__owned/otp/' + challenge.challenge_id, { headers: { 'X-Owned-Broker': seed.brokerKey } })
 assert.equal(mail.status(), 200)
 const code = (await mail.json()).code; assert.match(code, /^[0-9]{6}$/)
 await interaction.fill(page.getByLabel('Verification code', { exact: true }), code, 'access-code')
 const verified = page.waitForResponse(response => response.url() === api + '/auth/verify' && response.request().method() === 'POST')
 await interaction.click(page.getByRole('button', { name: /Enter your collection/ }), 'access-login')
 await data(await verified); await catalogRequested
 const loading = page.locator('.collection-results')
 assert.equal(await loading.getAttribute('aria-live'), 'polite')
 assert.match(await loading.innerText(), /Loading your collection/)
 assert.equal(await page.locator('.product-skeleton').count(), 6)
 const reduced = await page.locator('.product-skeleton').first().evaluate(element => ({ media: matchMedia('(prefers-reduced-motion: reduce)').matches, animation: getComputedStyle(element).animationDuration, transition: getComputedStyle(element).transitionDuration, scroll: getComputedStyle(document.documentElement).scrollBehavior }))
 assert.equal(reduced.media, true)
 assert.ok(reduced.animation.split(',').every(value => parseFloat(value) === 0))
 assert.ok(reduced.transition.split(',').every(value => parseFloat(value) === 0))
 assert.equal(reduced.scroll, 'auto')
 releaseCatalog()
 const unavailable = page.getByRole('alert').filter({ hasText: 'We couldn’t load your collection.' })
 await unavailable.waitFor(); await captureKeyboardEvidence(page, output + '/catalog-failure-320.png')
 const catalogue = page.waitForResponse(response => response.url().split('?')[0] === api + '/catalog' && response.request().method() === 'GET')
 await interaction.click(unavailable.getByRole('button', { name: 'Try again', exact: true }), 'access-retry')
 const result = await data(await catalogue), item = result.items.find(item => item.item_id === seed.itemId)
 assert.ok(item); assert.equal(item.availability, 'available')
 assert.equal(await unavailable.count(), 0)
 const product = page.getByRole('button', { name: 'View ' + item.model_name + ', ' + item.color_name, exact: true })
 await interaction.click(product, 'access-product')
 const dialog = page.getByRole('dialog'), quantity = dialog.getByLabel('Quantity', { exact: true })
 await interaction.fill(quantity, '0', 'access-invalid-quantity')
 await interaction.click(dialog.getByRole('button', { name: 'Add to selection', exact: true }), 'access-invalid-add')
 const invalid = dialog.getByRole('alert')
 await invalid.waitFor(); assert.match(await invalid.innerText(), /whole quantity greater than zero/)
 await captureKeyboardEvidence(page, output + '/quantity-invalid-320.png')
 assert.equal(await quantity.getAttribute('aria-invalid'), 'true', 'Invalid quantity must be exposed to assistive technology')
 assert.equal(await quantity.evaluate(element => element === document.activeElement), true, 'Invalid quantity must receive application focus')
 const errorId = await invalid.getAttribute('id'); assert.equal(errorId, 'product-add-error')
 assert.equal(await quantity.getAttribute('aria-describedby'), errorId)
 assert.ok(await quantity.evaluate(element => { const bounds = element.getBoundingClientRect(); return bounds.left >= 0 && bounds.right <= innerWidth && bounds.top >= 0 && bounds.bottom <= innerHeight }))
 await interaction.fill(quantity, '3', 'access-correct-quantity')
 assert.notEqual(await quantity.getAttribute('aria-invalid'), 'true')
 assert.equal(await invalid.count(), 0)
 await interaction.click(dialog.getByRole('button', { name: 'Add to selection', exact: true }), 'access-correct-add')
 await dialog.getByRole('status').filter({ hasText: 'Added to your selection.' }).waitFor()
 await interaction.click(dialog.getByRole('button', { name: 'Review selection', exact: true }), 'access-checkout')
 assert.equal(await page.getByRole('heading', { name: 'Your selection.', exact: true }).count(), 1)
 assert.equal(await page.getByLabel('Quantity', { exact: true }).inputValue(), '3')
 assert.equal(catalogFaults, 1); assert.ok(catalogPasses >= 1)
 const report = { status: 'pass', scope: 'Actual owned app.main/OTP/MySQL and built customer UI; one controlled catalog GET network abort then actual retry, reduced motion and keyboard quantity recovery; no production network proof', catalogGetAborts: catalogFaults, catalogGetContinues: catalogPasses, businessResponseReplacements: 0, reduced, quantityErrorAccessible: true, quantityRecovered: 3, interaction: interaction.summary() }
 await writeFile(output + '/report.json', JSON.stringify(report, null, 2)); console.log(JSON.stringify(report))
} finally { releaseCatalog(); await buyer.close(); await browser.close() }
