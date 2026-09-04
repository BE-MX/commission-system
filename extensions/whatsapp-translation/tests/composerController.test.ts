// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createComposerController } from '@/content/composerController'
import { createOutgoingComposer } from '@/content/outgoingComposer'
import { createToolbarView } from '@/content/toolbarView'
import { adapterFor } from '@/whatsapp/adapter'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

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
  await adapter.replaceComposer('请确认交期')
})

describe('composer controller + toolbar', () => {
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
      expect(shadow.textContent).toContain('连接方舟失败')
    })
    expect(shadow.textContent).toContain('重试')
  })

  it('reveals the default target language from the composer', async () => {
    const { composer, controller, shadow } = makeController()
    composer.setTargetLanguage('es')
    controller.reset()
    expect(shadow.textContent).toContain('Español')
  })
})
