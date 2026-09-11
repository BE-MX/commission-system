import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { CDPSession, Page } from '@playwright/test'
import { build } from 'vite'
import { aliases, buildTarget } from '../../vite.config'

let fixture: string, editorBundle: string, extensionBundle: string
const url = 'http://127.0.0.1:4179/reply-regression'
async function bundle(entry: string) {
  const output = await build({ configFile: false, logLevel: 'silent', resolve: { alias: aliases }, build: {
    target: buildTarget, write: false, minify: false,
    lib: { entry: fileURLToPath(new URL(entry, import.meta.url)), formats: ['iife'], name: 'ReplyHarness' },
  } })
  const result = Array.isArray(output) ? output[0] : output
  if (!('output' in result)) throw new Error('Missing bundle')
  return result.output.find(item => item.type === 'chunk')!.code
}
type Node = { nodeId: number; nodeName: string; nodeValue?: string; children?: Node[]; shadowRoots?: Node[] }
const all = (node: Node): Node[] => [node, ...(node.children ?? []).flatMap(all), ...(node.shadowRoots ?? []).flatMap(all)]
const text = (node: Node): string => (node.nodeValue ?? '') + (node.children ?? []).map(text).join('')
async function find(cdp: CDPSession, label: string, tag = 'BUTTON') {
  const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
  return all(root).find(node => node.nodeName === tag && text(node) === label)
}
async function click(page: Page, cdp: CDPSession, label: string, tag = 'BUTTON') {
  await expect.poll(async () => !!await find(cdp, label, tag)).toBe(true)
  const node = (await find(cdp, label, tag))!
  await cdp.send('DOM.scrollIntoViewIfNeeded', { nodeId: node.nodeId })
  const { model } = await cdp.send('DOM.getBoxModel', { nodeId: node.nodeId })
  const b = model.border
  await page.mouse.click((b[0] + b[2] + b[4] + b[6]) / 4, (b[1] + b[3] + b[5] + b[7]) / 4)
}
async function resolve(page: Page) { await page.evaluate(() => document.dispatchEvent(new Event('synthetic-reply-resolve'))) }
test.beforeAll(async () => {
  ;[fixture, editorBundle, extensionBundle] = await Promise.all([
    readFile(fileURLToPath(new URL('./fixture.html', import.meta.url)), 'utf8'), bundle('./lexicalEditor.ts'), bundle('./replyHarness.ts'),
  ])
  fixture = fixture.replace('<footer>', '<div data-testid="conversation-panel-messages"><div style="align-items:flex-start"><div data-testid="msg-container"><div class="copyable-text" data-pre-plain-text="Synthetic"><span data-testid="selectable-text">Can I have a sample?</span></div></div></div></div><footer>')
})
test.beforeEach(async ({ page }, info) => {
  await page.route('**/*', route => route.request().url() === url ? route.fulfill({ contentType: 'text/html', body: fixture }) : route.abort())
  await page.goto(url); await page.addScriptTag({ content: editorBundle })
  if (info.title.includes('detected language')) await page.evaluate(() => { document.documentElement.dataset.deferIncoming = 'true' })
  if (info.title.includes('inquiry')) await page.evaluate(() => { document.documentElement.dataset.memoryEnabled = 'true' })
  const cdp = await page.context().newCDPSession(page)
  const { frameTree } = await cdp.send('Page.getFrameTree')
  const { executionContextId } = await cdp.send('Page.createIsolatedWorld', { frameId: frameTree.frame.id, worldName: 'reply-synthetic' })
  const result = await cdp.send('Runtime.evaluate', { expression: extensionBundle, contextId: executionContextId })
  expect(result.exceptionDetails).toBeUndefined()
  await expect.poll(async () => !!await find(cdp, '话术')).toBe(true)
  await page.getByRole('textbox', { name: 'Synthetic composer' }).fill('原草稿')
})
test('full content integration fills and restores real Lexical draft, never sends', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  await resolve(page)
  await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(true)
  await page.screenshot({ path: '../../tmp/whatsapp-composer-browser/reply-tabs-desktop.png' })
  await click(page, cdp, '填入输入框')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', 'What sample size do you need?')
  await click(page, cdp, '恢复原草稿')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', '原草稿')
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
})

test('inquiry records persist a fresh snapshot and show internal handoff without sending', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  await resolve(page)
  await expect(page.locator('html')).toHaveAttribute('data-memory-committed', '1')
  await click(page, cdp, '询盘与接管')
  const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
  expect(all(root).map(text).join(' ')).toContain('Customer asks for a sample')
  const refresh = (await find(cdp, '刷新记录'))!
  await cdp.send('DOM.scrollIntoViewIfNeeded', { nodeId: refresh.nodeId })
  await page.screenshot({ path: '../../tmp/whatsapp-composer-browser/inquiry-preview.png' })
  await click(page, cdp, '接管摘要（仅内部）', 'SUMMARY')
  await click(page, cdp, '暂停生成，由我接管')
  await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(false)
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
})

test('inquiry does not save a late response after a new customer message', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  await page.evaluate(() => {
    const bubble = document.querySelector('[data-testid="msg-container"]')!
    const row = bubble.parentElement!.cloneNode(true) as Element
    row.querySelector('[data-testid="selectable-text"]')!.textContent = 'Actually, please wait.'
    bubble.parentElement!.after(row)
  })
  await resolve(page)
  await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(false)
  await expect(page.locator('html')).not.toHaveAttribute('data-memory-committed', '1')
})

test('inquiry disconnects when a same-title container replaces every message row', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  await resolve(page)
  await expect(page.locator('html')).toHaveAttribute('data-memory-committed', '1')
  await page.evaluate(() => {
    const row = document.querySelector('[data-testid="msg-container"]')!.parentElement!
    const replacement = row.cloneNode(true) as Element
    replacement.querySelector('[data-testid="selectable-text"]')!.textContent = 'Different synthetic inquiry'
    row.replaceWith(replacement)
    delete document.documentElement.dataset.memoryCommitted
  })
  await click(page, cdp, '话术')
  await resolve(page)
  await expect(page.locator('html')).toHaveAttribute('data-memory-committed', '1')
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
})
test('reverted genuine draft edit invalidates pending response', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  const editor = page.getByRole('textbox', { name: 'Synthetic composer' })
  await editor.press('End'); await page.keyboard.insertText('!'); await page.keyboard.press('Backspace')
  await resolve(page)
  await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(false)
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', '原草稿')
})
test('new incoming message invalidates pending reply without harming translation', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  await page.evaluate(() => {
    const bubble = document.querySelector('[data-testid="msg-container"]')!
    const row = bubble.parentElement!.cloneNode(true) as Element
    row.querySelector('[data-testid="selectable-text"]')!.textContent = 'New synthetic question'
    bubble.parentElement!.after(row)
  })
  await resolve(page)
  await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(false)
  await click(page, cdp, '翻译'); await click(page, cdp, '替换到输入框')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', 'Synthetic translated draft')
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
})
for (const ready of [false, true]) test(`detected language change invalidates ${ready ? 'completed' : 'pending'} reply`, async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await expect(page.locator('html')).toHaveAttribute('data-incoming-requested', 'true')
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  if (ready) {
    await resolve(page)
    await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(true)
  }
  // Resolve the already-loaded message's translation without any chat DOM edit.
  await page.evaluate(() => document.dispatchEvent(new Event('synthetic-incoming-resolve')))
  await expect(page.locator('html')).toHaveAttribute('data-detected-language', 'fr')
  if (!ready) await resolve(page)
  await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(false)
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', '原草稿')
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
})
for (const action of ['close', 'context'] as const) test(`pending restore cannot write after ${action}`, async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  await resolve(page); await click(page, cdp, '填入输入框')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', 'What sample size do you need?')
  await page.evaluate(() => { document.documentElement.dataset.pauseComposerFrames = 'true' })
  await click(page, cdp, '恢复原草稿')
  await expect(page.locator('html')).toHaveAttribute('data-composer-frame-pending', 'true')
  if (action === 'close') await click(page, cdp, '关闭话术')
  else await page.evaluate(() => {
    document.querySelector('[data-testid="selectable-text"]')!.textContent = 'Updated synthetic question'
  })
  await page.evaluate(() => document.dispatchEvent(new Event('synthetic-resume-frames')))
  // Let the actual rAF and the controlled editor reconciliation complete.
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))))
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', 'What sample size do you need?')
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
})
test('server lower capacity stops instead of silently truncating history', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await page.evaluate(() => {
    document.documentElement.dataset.lowerReplyLimit = 'true'
    const first = document.querySelector('[data-testid="msg-container"]')!
    first.querySelector('[data-testid="selectable-text"]')!.textContent = 'a'.repeat(4000)
    const next = first.parentElement!.cloneNode(true) as Element
    next.querySelector('[data-testid="selectable-text"]')!.textContent = 'b'.repeat(4000)
    first.parentElement!.after(next)
  })
  await click(page, cdp, '话术')
  await expect.poll(async () => {
    const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
    return all(root).map(text).join('')
  }).toContain('超过本次服务容量')
  await expect(page.locator('html')).not.toHaveAttribute('data-reply-requested', 'true')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', '原草稿')
})

test('long history loads earlier batches without translation calls and exports the full JSON', async ({ page }) => {
  test.setTimeout(40000)
  const cdp = await page.context().newCDPSession(page)
  await page.evaluate(() => {
    const first = document.querySelector('[data-testid="msg-container"]')!.parentElement!
    const scroll = document.createElement('div')
    scroll.id = 'synthetic-history'; scroll.style.cssText = 'height:240px;overflow-y:auto'
    first.replaceWith(scroll)
    let oldest = 100
    const prepend = () => {
      const end = oldest; oldest = Math.max(0, oldest - 20)
      const items = document.createDocumentFragment()
      for (let i = oldest; i < end; i++) {
        const row = document.createElement('div'); row.style.cssText = 'height:28px;display:flex;align-items:flex-start'
        row.dataset.id = `false_synthetic_${i}`
        const bubble = document.createElement('div'); bubble.dataset.testid = 'msg-container'
        const meta = document.createElement('div'); meta.className = 'copyable-text'; meta.dataset.prePlainText = '[10:00, 2026-09-11] Synthetic:'
        const span = document.createElement('span'); span.dataset.testid = 'selectable-text'; span.textContent = `Synthetic history ${i}`
        meta.append(span); bubble.append(meta); row.append(bubble); items.append(row)
      }
      const before = scroll.scrollHeight; scroll.prepend(items); scroll.scrollTop += scroll.scrollHeight - before
    }
    prepend(); scroll.scrollTop = scroll.scrollHeight
    scroll.addEventListener('scroll', () => { if (scroll.scrollTop < 100 && oldest) prepend() })
  })
  // Let translation of the initially loaded batch finish before measuring history loads.
  await expect(page.locator('html')).toHaveAttribute('data-translation-calls', '20')
  await page.evaluate(() => { const scroll = document.querySelector('#synthetic-history')!; scroll.scrollTop = scroll.scrollHeight })
  await click(page, cdp, '话术')
  const translationsAtStart = await page.locator('html').getAttribute('data-translation-calls')
  await expect(page.locator('html')).toHaveAttribute('data-reply-messages', '100', { timeout: 25000 })
  expect(await page.locator('html').getAttribute('data-translation-calls')).toBe(translationsAtStart)
  await resolve(page)
  await page.evaluate(() => {
    const scroll = document.querySelector('#synthetic-history')!
    scroll.addEventListener('scroll', () => { document.documentElement.dataset.repeatHistoryScroll = 'true' })
  })
  await click(page, cdp, '重新生成话术')
  await expect(page.locator('html')).toHaveAttribute('data-reply-calls', '2', { timeout: 3000 })
  await expect(page.locator('html')).not.toHaveAttribute('data-repeat-history-scroll', 'true')
  await expect(page.locator('html')).toHaveAttribute('data-reply-messages', '100')
  await resolve(page)
  await click(page, cdp, '填入输入框')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', 'What sample size do you need?')
  const download = page.waitForEvent('download')
  await click(page, cdp, '聊天上下文')
  await click(page, cdp, '下载聊天 JSON')
  const file = await download
  const path = await file.path()
  const exported = JSON.parse(await readFile(path!, 'utf8'))
  expect(exported.messages).toHaveLength(100)
  expect(exported.messages[0].text).toBe('Synthetic history 0')
  expect(JSON.stringify(exported)).not.toContain('false_synthetic')
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
  await page.screenshot({ path: '../../tmp/whatsapp-composer-browser/full-history.png' })
})

test('reply tabs remain usable on narrow screens and with the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 820 })
  const cdp = await page.context().newCDPSession(page)
  await click(page, cdp, '话术'); await resolve(page)
  await expect.poll(async () => !!await find(cdp, '填入输入框')).toBe(true)
  await page.screenshot({ path: '../../tmp/whatsapp-composer-browser/reply-tabs-narrow.png' })
  const tab = (await find(cdp, '建议回复'))!
  await cdp.send('DOM.focus', { nodeId: tab.nodeId })
  await page.keyboard.press('ArrowRight')
  const contextTab = (await find(cdp, '聊天上下文'))!
  const { attributes } = await cdp.send('DOM.getAttributes', { nodeId: contextTab.nodeId })
  expect(attributes).toContain('true')
  await click(page, cdp, '建议回复')
  await click(page, cdp, '填入输入框')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', 'What sample size do you need?')
})

test('auto takeover sends two ordered synthetic messages and stops with its toggle', async ({ page }) => {
  test.setTimeout(30000)
  const cdp = await page.context().newCDPSession(page)
  await page.getByRole('textbox', { name: 'Synthetic composer' }).fill('')
  await page.evaluate(() => { document.documentElement.dataset.autoHarness = 'true'; document.querySelector('#send')!.setAttribute('data-testid', 'compose-btn-send') })
  await click(page, cdp, '自动接管')
  await expect(page.locator('html')).toHaveAttribute('data-auto-sent', '2', { timeout: 15000 })
  const sent = await page.locator('[data-id^="true_synthetic_sent_"]').allTextContents()
  expect(sent).toEqual(['Hi! Happy to help 🙂', 'Which sample size works for you?'])
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', '')
  await page.screenshot({ path: '../../tmp/whatsapp-composer-browser/auto-takeover.png' })
  await click(page, cdp, '停止接管')
  await expect.poll(async () => !!await find(cdp, '自动接管')).toBe(true)
})
test('manual input stops auto takeover before sending', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  const composer = page.getByRole('textbox', { name: 'Synthetic composer' })
  await composer.fill('')
  await page.evaluate(() => document.querySelector('#send')!.setAttribute('data-testid', 'compose-btn-send'))
  await click(page, cdp, '自动接管')
  await composer.fill('I will handle this myself')
  await expect.poll(async () => !!await find(cdp, '自动接管')).toBe(true)
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
})

test('manual mode cancels an auto activation still awaiting disclosure', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await page.getByRole('textbox', { name: 'Synthetic composer' }).fill('')
  await page.evaluate(() => { document.documentElement.dataset.deferAutoDisclosure = 'true' })
  await click(page, cdp, '自动接管')
  await click(page, cdp, '话术')
  await page.evaluate(() => document.dispatchEvent(new Event('synthetic-auto-disclosure')))
  await expect.poll(async () => !!await find(cdp, '自动接管')).toBe(true)
  expect(await find(cdp, '停止接管')).toBeUndefined()
})

test('auto takeover cannot start while another instance owns the browser lock', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await page.getByRole('textbox', { name: 'Synthetic composer' }).fill('')
  await page.evaluate(() => { void navigator.locks.request('leshine-whatsapp-auto-takeover', async () => {
    document.documentElement.dataset.syntheticLock = 'true'
    await new Promise(resolve => document.addEventListener('synthetic-release-lock', resolve, { once: true }))
  }) })
  await expect(page.locator('html')).toHaveAttribute('data-synthetic-lock', 'true')
  await click(page, cdp, '自动接管')
  await expect.poll(async () => { const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true }); return all(root).map(text).join(' ') }).toContain('另一个窗口正在自动接管')
  await expect(page.locator('html')).not.toHaveAttribute('data-reply-requested', 'true')
  await page.evaluate(() => document.dispatchEvent(new Event('synthetic-release-lock')))
})
