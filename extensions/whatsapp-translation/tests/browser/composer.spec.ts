import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { CDPSession, Page } from '@playwright/test'
import { build } from 'vite'
import { aliases, buildTarget } from '../../vite.config'

const original = '请确认样品已准备好。'
const translated = 'Your sample is ready.'
const fixtureURL = 'http://127.0.0.1:4179/composer-regression'
let fixture: string
let editorBundle: string
let extensionBundle: string

async function bundle(entry: string): Promise<string> {
  const output = await build({
    configFile: false,
    logLevel: 'silent',
    resolve: { alias: aliases },
    build: {
      target: buildTarget,
      write: false,
      minify: false,
      lib: { entry: fileURLToPath(new URL(entry, import.meta.url)), formats: ['iife'], name: 'RegressionHarness' },
    },
  })
  const result = Array.isArray(output) ? output[0] : output
  if (!('output' in result)) throw new Error('Unexpected Vite bundle result')
  const chunk = result.output.find(item => item.type === 'chunk')
  if (!chunk || chunk.type !== 'chunk') throw new Error('Vite did not emit a script chunk')
  return chunk.code
}

type PiercedNode = {
  nodeId: number
  nodeName: string
  nodeValue?: string
  attributes?: string[]
  children?: PiercedNode[]
  shadowRoots?: PiercedNode[]
}

function nodes(root: PiercedNode): PiercedNode[] {
  return [root, ...(root.children ?? []).flatMap(nodes), ...(root.shadowRoots ?? []).flatMap(nodes)]
}

function textOf(node: PiercedNode): string {
  return `${node.nodeValue ?? ''}${(node.children ?? []).map(textOf).join('')}`
}

async function findButton(cdp: CDPSession, label: string): Promise<PiercedNode | undefined> {
  const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
  return nodes(root).find(node => node.nodeName === 'BUTTON' && textOf(node) === label)
}

async function buttonCenter(cdp: CDPSession, label: string): Promise<{ x: number; y: number }> {
  await expect.poll(async () => Boolean(await findButton(cdp, label)), { message: `Button ${label} should appear` }).toBe(true)
  const button = await findButton(cdp, label)
  return nodeCenter(cdp, button!)
}

async function nodeCenter(cdp: CDPSession, node: PiercedNode): Promise<{ x: number; y: number }> {
  const { model } = await cdp.send('DOM.getBoxModel', { nodeId: node.nodeId })
  const [x1, y1, x2, y2, x3, y3, x4, y4] = model.border
  return { x: (x1 + x2 + x3 + x4) / 4, y: (y1 + y2 + y3 + y4) / 4 }
}

async function clickButton(page: Page, cdp: CDPSession, label: string): Promise<void> {
  const { x, y } = await buttonCenter(cdp, label)
  await page.mouse.click(x, y, { delay: 60 })
}

async function clickWithoutLosingEditorFocus(page: Page, cdp: CDPSession, label: string): Promise<void> {
  const { x, y } = await buttonCenter(cdp, label)
  await page.mouse.move(x, y)
  await page.mouse.down()
  try {
    // Assert before mouseup/click: refocusing inside the click handler is too late
    // to prevent the native blur that starts controlled-editor selection races.
    await expect(page.getByRole('textbox', { name: 'Synthetic composer' })).toBeFocused()
  } finally {
    await page.mouse.up()
  }
}

async function expectComposer(page: Page, text: string): Promise<void> {
  await expect(page.getByRole('textbox', { name: 'Synthetic composer' })).toHaveText(text)
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', text)
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
}

async function expectDraftAcceptsEdits(page: Page, text: string): Promise<void> {
  // A subsequent genuine edit detects a DOM-only write that Lexical would undo.
  // Run this after the restore assertion: editing invalidates the restore affordance.
  await page.getByRole('textbox', { name: 'Synthetic composer' }).press('End')
  await page.keyboard.insertText('!')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', `${text}!`)
  await page.keyboard.press('Backspace')
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', text)
  await expect(page.locator('html')).not.toHaveAttribute('data-send-clicked', 'true')
}

test.beforeAll(async () => {
  ;[fixture, editorBundle, extensionBundle] = await Promise.all([
    readFile(fileURLToPath(new URL('./fixture.html', import.meta.url)), 'utf8'),
    bundle('./lexicalEditor.ts'),
    bundle('./extensionHarness.ts'),
  ])
})

test.beforeEach(async ({ page }) => {
  await page.route('**/*', route => route.request().url() === fixtureURL
    ? route.fulfill({ contentType: 'text/html', body: fixture })
    : route.abort())
  await page.goto(fixtureURL)
  await page.addScriptTag({ content: editorBundle })
  await expect(page.locator('html')).toHaveAttribute('data-lexical-ready', 'true')
  const cdp = await page.context().newCDPSession(page)
  const { frameTree } = await cdp.send('Page.getFrameTree')
  const { executionContextId } = await cdp.send('Page.createIsolatedWorld', {
    frameId: frameTree.frame.id,
    worldName: 'extension-composer-regression',
  })
  const result = await cdp.send('Runtime.evaluate', { expression: extensionBundle, contextId: executionContextId })
  expect(result.exceptionDetails).toBeUndefined()
  await cdp.detach()
  await expect(page.locator('html')).toHaveAttribute('data-extension-ready', 'true')
  await page.getByRole('textbox', { name: 'Synthetic composer' }).click()
  await page.keyboard.insertText(original)
  await expect(page.locator('html')).toHaveAttribute('data-lexical-text', original)
})

test('mouse preview, replacement and restore commit to the real Lexical editor', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await clickButton(page, cdp, '翻译')
  await clickButton(page, cdp, '替换到输入框')
  await expectComposer(page, translated)
  await clickButton(page, cdp, '恢复中文')
  await expectComposer(page, original)
  await expectDraftAcceptsEdits(page, original)
})

test('Alt+T preview and replacement commit while the editor retains focus', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await page.keyboard.press('Alt+t')
  await expect.poll(async () => Boolean(await findButton(cdp, '替换到输入框'))).toBe(true)
  await page.keyboard.press('Alt+t')
  await expectComposer(page, translated)
  await expectDraftAcceptsEdits(page, translated)
})

test('mouse restore works after a keyboard replacement', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await page.keyboard.press('Alt+t')
  await expect.poll(async () => Boolean(await findButton(cdp, '替换到输入框'))).toBe(true)
  await page.keyboard.press('Alt+t')
  await expectComposer(page, translated)
  await clickButton(page, cdp, '恢复中文')
  await expectComposer(page, original)
  await expectDraftAcceptsEdits(page, original)
})

test('primary mousedown on replacement and restore preserves editor focus', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  await page.keyboard.press('Alt+t')
  await clickWithoutLosingEditorFocus(page, cdp, '替换到输入框')
  await expectComposer(page, translated)
  await clickWithoutLosingEditorFocus(page, cdp, '恢复中文')
  await expectComposer(page, original)
  await expectDraftAcceptsEdits(page, original)
})

test('mouse replacement and restore work when focus starts in an external search field', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  const search = page.getByRole('searchbox', { name: 'Synthetic chat search' })
  await search.click()
  await expect(search).toBeFocused()
  await clickButton(page, cdp, '翻译')
  await expect(search).toBeFocused()
  await clickButton(page, cdp, '替换到输入框')
  await expectComposer(page, translated)
  await search.click()
  await expect(search).toBeFocused()
  await clickButton(page, cdp, '恢复中文')
  await expectComposer(page, original)
})

test('the language selector can still receive focus from a real mouse click', async ({ page }) => {
  const cdp = await page.context().newCDPSession(page)
  const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true })
  const select = nodes(root).find(node => {
    const attributes = node.attributes ?? []
    const labelIndex = attributes.indexOf('aria-label')
    return node.nodeName === 'SELECT' && labelIndex >= 0 && attributes[labelIndex + 1] === '发送语言'
  })
  expect(select).toBeDefined()
  const { x, y } = await nodeCenter(cdp, select!)
  await page.mouse.click(x, y, { delay: 60 })
  const { object } = await cdp.send('DOM.resolveNode', { nodeId: select!.nodeId })
  await expect.poll(async () => {
    const { result } = await cdp.send('Runtime.callFunctionOn', {
      objectId: object.objectId,
      functionDeclaration: 'function () { return this.getRootNode().activeElement === this }',
      returnByValue: true,
    })
    return result.value
  }).toBe(true)
  await expect(page.getByRole('textbox', { name: 'Synthetic composer' })).not.toBeFocused()
  await page.keyboard.press('Escape')
  await expectComposer(page, original)
})
