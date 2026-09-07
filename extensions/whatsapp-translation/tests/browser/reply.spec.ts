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
async function find(cdp: CDPSession, label: string) {
  const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
  return all(root).find(node => node.nodeName === 'BUTTON' && text(node) === label)
}
async function click(page: Page, cdp: CDPSession, label: string) {
  await expect.poll(async () => !!await find(cdp, label)).toBe(true)
  const node = (await find(cdp, label))!
  const { model } = await cdp.send('DOM.getBoxModel', { nodeId: node.nodeId })
  const b = model.border
  await page.mouse.click((b[0] + b[2] + b[4] + b[6]) / 4, (b[1] + b[3] + b[5] + b[7]) / 4)
}
async function resolve(page: Page) { await page.evaluate(() => document.dispatchEvent(new Event('synthetic-reply-resolve'))) }
test.beforeAll(async () => {
  ;[fixture, editorBundle, extensionBundle] = await Promise.all([
    readFile(fileURLToPath(new URL('./fixture.html', import.meta.url)), 'utf8'), bundle('./lexicalEditor.ts'), bundle('./replyHarness.ts'),
  ])
  fixture = fixture.replace('<footer>', '<div style="align-items:flex-start"><div data-testid="msg-container"><div class="copyable-text" data-pre-plain-text="Synthetic"><span data-testid="selectable-text">Can I have a sample?</span></div></div></div><footer>')
})
test.beforeEach(async ({ page }, info) => {
  await page.route('**/*', route => route.request().url() === url ? route.fulfill({ contentType: 'text/html', body: fixture }) : route.abort())
  await page.goto(url); await page.addScriptTag({ content: editorBundle })
  if (info.title.includes('detected language')) await page.evaluate(() => { document.documentElement.dataset.deferIncoming = 'true' })
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
  await resolve(page); await click(page, cdp, '填入输入框')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', 'What sample size do you need?')
  await click(page, cdp, '恢复原草稿')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', '原草稿')
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
test('server lower 6000-character capability trims the captured request before generation', async ({ page }) => {
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
  await expect(page.locator('html')).toHaveAttribute('data-reply-requested', 'true')
  await expect(page.locator('html')).toHaveAttribute('data-reply-characters', '4000')
  await expect(page.locator('html')).toHaveAttribute('data-reply-messages', '1')
  await expect(page.locator('html')).toHaveAttribute('data-reply-truncated', 'true')
  const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
  expect(all(root).map(text).join('')).toContain('上限 6000 字符')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', '原草稿')
})
