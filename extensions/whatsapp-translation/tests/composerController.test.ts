// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createComposerController } from '@/content/composerController'
import { createOutgoingComposer } from '@/content/outgoingComposer'
import { createToolbarView } from '@/content/toolbarView'
import { adapterFor } from '@/whatsapp/adapter'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { installControlledComposer } from './support/controlledComposer'

const document = new JSDOM(readFileSync('tests/fixtures/direct.html', 'utf8')).window.document
const adapter = adapterFor(document)
const bridge = { translate: vi.fn() }

function makeController() {
  const host = document.createElement('div')
  const shadow = host.attachShadow({ mode: 'open' })
  const view = createToolbarView(shadow, {
    onCancelPreview: () => {},
    onLanguageChange: () => {},
    onReplace: () => {},
    onRestore: () => {},
    onRetry: () => {},
    onTranslate: () => {},
  })
  const composer = createOutgoingComposer(adapter, bridge)
  const controller = createComposerController(composer, view, { save: vi.fn() })

  async function triggerTranslate() {
    controller.onTranslate()
    await vi.waitFor(() => expect(adapter.readComposer()).toBe('Current draft'))
  }
  return { composer, controller, shadow, triggerTranslate }
}

beforeEach(async () => {
  bridge.translate.mockReset().mockResolvedValue({
    translation: 'Please confirm the lead time.',
    backTranslation: '请确认交期。',
    sourceLanguage: 'zh-CN',
  })
  const composer = document.querySelector('footer div') as HTMLElement
  installControlledComposer(document, composer)
  await adapter.replaceComposer('请确认交期')
})

describe('composer controller + toolbar', () => {
  it('keeps the draft editor focused when a mouse activates a toolbar action', () => {
    const host = document.createElement('div')
    document.body.append(host)
    const shadow = host.attachShadow({ mode: 'closed' })
    const onReplace = vi.fn()
    const view = createToolbarView(shadow, {
      onCancelPreview: vi.fn(),
      onLanguageChange: vi.fn(),
      onReplace,
      onRestore: vi.fn(),
      onRetry: vi.fn(),
      onTranslate: vi.fn(),
    })
    view.render({
      canRestore: false,
      preview: { original: 'Draft', composerVersion: 'Draft', translated: 'Translation', targetLanguage: 'en' },
      status: { kind: 'idle' },
      targetLanguage: 'en',
    })
    const editor = document.querySelector('footer div') as HTMLElement
    editor.focus()
    const replace = [...shadow.querySelectorAll('button')].find(button => button.textContent === '替换到输入框')!
    const mouseDown = new document.defaultView!.MouseEvent('mousedown', { button: 0, bubbles: true, cancelable: true })
    // Model the browser default: an uncancelled mouse-down focuses the button.
    if (replace.dispatchEvent(mouseDown)) replace.focus()
    replace.click()

    expect(document.activeElement === editor).toBe(true)
    expect(onReplace).toHaveBeenCalledOnce()
    host.remove()
  })

  it('shows a busy state then a preview card with back-translation', async () => {
    const { controller, shadow } = makeController()
    controller.reset()
    controller.onTranslate()
    expect(shadow.textContent).toContain('翻译中…')

    await vi.waitFor(() => {
      expect(shadow.textContent).toContain('请确认交期。')
    })
    expect(shadow.textContent).toContain('替换到输入框')
    expect(shadow.textContent).toContain('原文')
    expect(shadow.textContent).toContain('回译')
  })

  it('reports a stable error message for an empty composer', async () => {
    await adapter.replaceComposer('')
    const { controller, shadow } = makeController()
    controller.reset()
    controller.onTranslate()
    await vi.waitFor(() => {
      expect(shadow.textContent).toContain('输入框为空')
    })
  })

  it('shows a retry affordance for a network error', async () => {
    bridge.translate.mockRejectedValueOnce(new Error('network_error'))
    const { controller, shadow } = makeController()
    controller.reset()
    controller.onTranslate()
    await vi.waitFor(() => {
      expect(shadow.textContent).toContain('网络暂时中断，请检查网络后重试')
    })
    expect(shadow.textContent).toContain('重试')
  })

  it('reveals the default target language from the composer', async () => {
    const { composer, controller, shadow } = makeController()
    composer.setTargetLanguage('es')
    controller.reset()
    expect(shadow.textContent).toContain('Español')
  })

  it('shows replacement progress and preserves the preview when the editor rejects the write', async () => {
    let resolveReplace: ((value: boolean) => void) | undefined
    const composer = {
      canRestore: () => false,
      clearPreview: vi.fn(),
      getPreview: () => ({
        composerVersion: 'Original',
        original: 'Original',
        targetLanguage: 'en',
        translated: 'Translated',
      }),
      getTargetLanguage: () => 'en',
      previewIsFresh: () => true,
      replaceWithPreview: () => new Promise<boolean>(resolve => { resolveReplace = resolve }),
      restoreOriginal: vi.fn(),
      setTargetLanguage: vi.fn(),
      translateForPreview: vi.fn(),
    }
    const view = { render: vi.fn() }
    const controller = createComposerController(composer, view, { save: vi.fn() })

    const replacing = controller.onReplace()
    expect(view.render.mock.calls.at(-1)?.[0].status).toEqual({ kind: 'replacing' })
    resolveReplace?.(false)
    await replacing

    expect(view.render.mock.calls.at(-1)?.[0].status).toEqual({ kind: 'error', code: 'composer_write_failed' })
    expect(view.render.mock.calls.at(-1)?.[0].preview?.translated).toBe('Translated')
  })

  it('keeps the restore action available when the editor rejects restoration', async () => {
    let canRestore = true
    const composer = {
      canRestore: () => canRestore,
      clearPreview: vi.fn(),
      getPreview: () => undefined,
      getTargetLanguage: () => 'en',
      previewIsFresh: () => false,
      replaceWithPreview: vi.fn(),
      restoreOriginal: vi.fn().mockResolvedValue(false),
      setTargetLanguage: vi.fn(),
      translateForPreview: vi.fn(),
    }
    const view = { render: vi.fn() }
    const controller = createComposerController(composer, view, { save: vi.fn() })

    await controller.onRestore()

    expect(view.render.mock.calls.at(-1)?.[0]).toMatchObject({
      canRestore: true,
      status: { kind: 'restore_failed' },
    })

    const host = document.createElement('div')
    const shadow = host.attachShadow({ mode: 'open' })
    const toolbar = createToolbarView(shadow, {
      onCancelPreview: vi.fn(),
      onLanguageChange: vi.fn(),
      onReplace: vi.fn(),
      onRestore: vi.fn(),
      onRetry: vi.fn(),
      onTranslate: vi.fn(),
    })
    toolbar.render(view.render.mock.calls.at(-1)![0])
    expect(shadow.textContent).toContain('未能恢复中文，请重试')
    expect(shadow.textContent).toContain('重试恢复')

    canRestore = false
    controller.onComposerInput()
    expect(view.render.mock.calls.at(-1)?.[0].status).toEqual({ kind: 'idle' })
  })
})
