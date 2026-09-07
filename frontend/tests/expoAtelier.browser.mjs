/**
 * Real kiosk UI smoke: run Vite on :3017, then run this file with Playwright available.
 * PLAYWRIGHT_MODULE and EXPO_BROWSER optionally point to a bundled install / Chrome.
 * Synthetic API fixtures only; no real customer data or paid generation.
 */
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { installExpoFixture, original } from './fixtures/expoAtelier.mjs'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const baseURL = process.env.EXPO_UI_URL || 'http://127.0.0.1:3017'
const out = resolve(process.env.EXPO_UI_OUTPUT || 'tmp/expo-atelier')
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.EXPO_BROWSER ? { executablePath: process.env.EXPO_BROWSER } : {}), args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] })
const evidence = [], errors = []
async function screenshot(page, name) {
  await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(a => a.effect.getComputedTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))) })
  await page.screenshot({ path: `${out}/${name}.png` })
}
async function hitTarget(page, selector) {
  const el = page.locator(selector).first()
  await el.scrollIntoViewIfNeeded()
  assert.equal(await el.evaluate(e => {
    const r = e.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
    return !!hit && (hit === e || e.contains(hit))
  }), true, `${selector} must be reachable and unobscured`)
}
async function registerAndUpload(page) {
  await page.locator('#expo-name').fill('演示女士')
  await page.locator('#expo-phone').fill('13800000000')
  await page.locator('.submit').click()
  assert.equal(await page.locator('.reg').count(), 1, 'consent is still required')
  await page.locator('.consent input').check()
  await page.locator('.submit').click()
  await page.locator('.gd-go').click()
  await page.locator('.viewport').waitFor()
  await screenshot(page, 'capture')
  await page.getByRole('button', { name: '拍照', exact: true }).click()
  await page.getByRole('button', { name: '重拍', exact: true }).click()
  await page.getByRole('button', { name: '扫码传照片', exact: true }).click()
  await page.locator('.qr-panel').waitFor()
  await screenshot(page, 'qr-upload')
  await page.locator('.qr-panel button').click()
  await page.locator('input[type=file]').first().setInputFiles(fileURLToPath(new URL('../src/assets/expo/atelier-hero.webp', import.meta.url)))
  await page.getByRole('button', { name: '就用这张' }).click()
}
try {
  const context = await browser.newContext({ viewport: { width: 768, height: 1024 }, permissions: ['camera'] })
  const page = await context.newPage()
  page.on('pageerror', e => errors.push(e.message))
  const state = await installExpoFixture(page, baseURL)
  await page.goto(`${baseURL}/expo/kiosk`)
  await page.locator('.cta').waitFor()
  for (const [width, height] of [[1440,1000],[768,1024],[390,844],[320,568],[667,375],[844,390]]) {
    await page.setViewportSize({ width, height })
    await hitTarget(page, '.cta'); await hitTarget(page, '.cta2'); await hitTarget(page, '.member-link')
    const brand = await page.locator('.xk-head').evaluate(e => ({ scroll: e.scrollWidth, width: e.clientWidth }))
    assert.ok(brand.scroll <= brand.width + 1, `header fits ${width}x${height}`)
    await page.locator('.attract').evaluate(e => { e.scrollTop = 0 })
    await screenshot(page, `welcome-${width}x${height}`)
    evidence.push(`Welcome ${width}x${height}: both paths and cooperation reachable; header fits`)
  }
  await page.setViewportSize({ width: 768, height: 1024 })
  await page.locator('.member-link').click(); await page.locator('.xm-panel').waitFor(); await screenshot(page,'cooperation'); await page.locator('.xm-close').click()
  await page.locator('.cta').click(); await screenshot(page,'register'); await registerAndUpload(page)
  await page.locator('.analyzing').waitFor(); await screenshot(page,'analyzing')
  await page.locator('.matching').waitFor(); await page.locator('.picker-option').first().waitFor()
  await page.locator('.card').nth(1).click()
  await page.locator('.chip').filter({ hasText: '栗棕' }).click()
  await page.locator('.picker-option').filter({ hasText: '柔光' }).click()
  await hitTarget(page, '.go')
  await page.locator('.m-scroll').evaluate(e=>{e.scrollTop=0})
  await screenshot(page,'matching-tablet')
  for(const [width,height] of [[1440,1000],[390,844],[667,375]]) {
    await page.setViewportSize({width,height}); await hitTarget(page,'.go'); await screenshot(page,`matching-${width}x${height}`)
  }
  await page.setViewportSize({width:768,height:1024})
  await page.locator('.lib-entry').click(); await page.locator('.lib-card').last().click()
  assert.equal(await page.locator('.card[aria-pressed=true]').innerText().then(t=>t.includes('自选造型')),true)
  await page.locator('.swap').first().click()
  await page.locator('.card').first().click()
  await page.locator('.picker-option').filter({hasText:'柔光'}).click()
  state.displayFail = true
  await page.locator('.go').click(); await page.locator('.waiting').waitFor(); await screenshot(page,'generating')
  assert.equal(await page.locator('.xk-nav').filter({hasText:'上一步'}).isDisabled(),true)
  await page.locator('.after.revealed').waitFor()
  assert.equal(await page.locator('.after').getAttribute('src'), `${original}?id=1`, 'failed display image falls back to original')
  const generate = state.calls.filter(c=>c.path.endsWith('/generate')).at(-1)
  assert.equal(generate.body.prompt_version_id,104)
  assert.equal(generate.body.wig_ids.length,1)
  assert.ok(generate.body.scene_key)
  const stage = await page.locator('.stage').boundingBox()
  await page.mouse.move(stage.x+stage.width*.5,stage.y+stage.height*.5);await page.mouse.down();await page.mouse.move(stage.x+stage.width*.8,stage.y+stage.height*.5);await page.mouse.up()
  assert.ok(Number(await page.locator('input[type=range]').inputValue())>70,'pointer comparison tracks drag')
  await page.locator('input[type=range]').focus();await page.keyboard.press('ArrowLeft')
  await page.getByRole('button',{name:'♡ 心动',exact:true}).click()
  assert.equal(state.calls.filter(c=>c.path.endsWith('/reaction')).at(-1).body.reaction,'loved')
  await page.getByRole('button',{name:'打印这张'}).click()
  assert.ok((await page.evaluate(()=>window.__printed))[0].includes(original),'native print retains original image URL')
  const ink = await page.locator('.qr-card canvas').evaluate(c=>[...c.getContext('2d').getImageData(0,0,c.width,c.height).data].some((v,i)=>i%4===3&&v>0))
  assert.ok(ink,'QR is drawn')
  for(const [width,height] of [[768,1024],[1440,1000],[390,844]]) {
    await page.setViewportSize({width,height});await page.locator('.result').evaluate(e=>{e.scrollTop=0});await screenshot(page,`result-${width}x${height}`)
    await hitTarget(page,'.print'); await hitTarget(page,'.react'); await hitTarget(page,'.qr-txt a')
  }
  await page.setViewportSize({width:768,height:1024})
  await page.getByRole('button',{name:'试试其他发型',exact:true}).click()
  state.originalFail=true
  await page.locator('.go').click()
  await page.getByText('效果图加载失败，请重试',{exact:true}).waitFor()
  assert.equal(await page.locator('.lbl.a').count(),0,'failed image cannot be presented as an after result')
  state.originalFail=false;state.displayFail=false
  await page.getByRole('button',{name:'重新加载图片',exact:true}).click()
  await page.locator('.after.revealed').waitFor()
  await page.locator('.result-thumbs button').first().click();await page.locator('.after.revealed').waitFor()
  await page.getByRole('button',{name:'试试其他发型',exact:true}).click()
  state.displayMissing=true;state.originalFail=true
  await page.locator('.go').click()
  await page.getByText('效果图加载失败，请重试',{exact:true}).waitFor()
  state.originalFail=false
  await page.getByRole('button',{name:'重新加载图片',exact:true}).click()
  await page.locator('.after.revealed').waitFor()
  state.displayMissing=false
  evidence.push('Historical result with only original URL: load failure offers retry and recovers')
  evidence.push('Images: display 404 falls back to original; both failures show retry; retry recovers; switching earlier results retains image reveal')
  await page.getByRole('button',{name:'查看完整效果图'}).click();await page.locator('.lb-close').click()
  await page.getByRole('button',{name:'请顾问过来',exact:true}).click();await page.locator('.sales .row').click();await screenshot(page,'sales');await page.locator('.xk-nav').filter({hasText:'上一步'}).click()
  await page.locator('.xk-nav').filter({hasText:'主页'}).click();await page.getByRole('button',{name:'继续体验'}).click();assert.equal(await page.locator('.result').count(),1)
  await page.locator('.xk-nav').filter({hasText:'主页'}).click();await page.getByRole('button',{name:'返回主页',exact:true}).click()
  evidence.push('Try-on: consent, camera upload, analysis, recommendation/library/swap, colors, dynamic version payload, generation, drag/keyboard comparison, reaction, QR, original-image print, advisor, home confirmation')
  await page.locator('.cta2').click();await registerAndUpload(page);await page.locator('.scene').waitFor();await page.locator('.picker-option').first().waitFor()
  assert.equal(await page.locator('.scene .card.on').count(),3)
  await page.locator('.scene .card').last().click();assert.equal(await page.locator('.scene .card.on').count(),3,'max 3 scenes retained')
  await screenshot(page,'scene');state.failGeneration=true;await page.locator('.go').click();await page.getByRole('button',{name:'重新生成',exact:true}).waitFor();await screenshot(page,'generation-failed');await page.getByRole('button',{name:'重新生成',exact:true}).click();await page.locator('.scene').waitFor();state.failGeneration=false;await page.locator('.go').click();await page.locator('.after.revealed').waitFor()
  assert.equal(state.calls.filter(c=>c.path.endsWith('/generate')).at(-1).body.scene_keys.length,3)
  await page.getByRole('button',{name:'再选场景',exact:true}).click();await page.locator('.scene').waitFor()
  state.versions=false;await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText('暂无可用风格，请联系顾问').waitFor();assert.equal(await page.locator('.go').isDisabled(),true)
  state.versions=true;await page.getByRole('button',{name:'刷新',exact:true}).click();await page.locator('.picker-option').first().waitFor()
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('.scene .card').first().evaluate(e=>getComputedStyle(e).animationDuration),'1e-05s')
  evidence.push('Scenes: max 3, preserved scene_keys request, reselect, empty prompt versions disable generation; reduced-motion applied')
  await page.goto(`${baseURL}/expo/kiosk`);state.quota=0;await page.reload();await page.locator('.xk-quota-panel').waitFor();await screenshot(page,'quota-zero');await hitTarget(page,'.xk-brand')
  await page.locator('.xk-brand').click();await page.locator('.sales').waitFor();await page.locator('.xk-quota-overlay').waitFor({state:'detached'});assert.equal(await page.locator('.xk-quota-overlay').count(),0)
  evidence.push('Zero quota blocks customer stage while sales remains accessible')
  state.quota=50;await page.goto(`${baseURL}/expo/kiosk`);await page.locator('.xk-head').getByRole('button',{name:'退出登录',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click();await page.locator('.xk-head').getByRole('button',{name:'退出登录',exact:true}).click();await page.locator('.xk-confirm').getByRole('button',{name:'退出登录',exact:true}).click();await page.waitForURL(url => url.pathname === '/login' && url.searchParams.get('redirect') === '/expo/kiosk');evidence.push('Logout confirmation returns to kiosk login')
  assert.deepEqual(errors,[])
  await writeFile(`${out}/verification.json`,JSON.stringify({evidence,errors},null,2))
  console.log(evidence.join('\n'));console.log('PASS: no uncaught browser errors')
  await context.close()
} finally { await browser.close() }
