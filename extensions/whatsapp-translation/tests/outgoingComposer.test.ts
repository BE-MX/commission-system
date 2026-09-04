// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { adapterFor } from '@/whatsapp/adapter'
import { createOutgoingComposer } from '@/content/outgoingComposer'

const document = new JSDOM(readFileSync('tests/fixtures/direct.html', 'utf8')).window.document
const adapter = adapterFor(document)
const bridge = { translate: vi.fn() }

beforeEach(() => {
  bridge.translate.mockReset().mockResolvedValue({ translation: 'Please confirm the lead time.' })
})

describe('outgoing composer', () => {
  it('previews and replaces without invoking any send control', async () => {
    const sendButton = document.createElement('button')
    sendButton.click = vi.fn()
    const form = document.createElement('form')
    form.dispatchEvent = vi.fn()
    const composer = createOutgoingComposer(adapter, bridge)

    const preview = await composer.translateForPreview()
    expect(adapter.readComposer()).toBe('Current draft')
    expect(preview).toEqual({
      composerVersion: 'Current draft',
      original: 'Current draft',
      targetLanguage: 'zh-CN',
      translated: 'Please confirm the lead time.',
    })

    expect(await composer.replaceWithPreview()).toBe(true)
    expect(adapter.readComposer()).toBe('Please confirm the lead time.')
    expect(sendButton.click).not.toHaveBeenCalled()
    expect(form.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'submit' }))
  })

  it('rejects empty and over-limit text without calling Ark', async () => {
    const emptyComposer = createOutgoingComposer(adapter, bridge)
    await adapter.replaceComposer('')
    await expect(emptyComposer.translateForPreview()).rejects.toThrow('empty_composer')

    await adapter.replaceComposer('a'.repeat(4_001))
    await expect(emptyComposer.translateForPreview()).rejects.toThrow('text_too_long')
    expect(bridge.translate).not.toHaveBeenCalled()
  })

  it('is disabled for unsupported chats', async () => {
    const unsupportedAdapter = {
      ...adapter,
      inspectChat: vi.fn(() => ({ kind: 'group' })),
      readComposer: () => 'Unsupported draft',
      replaceComposer: async () => false,
    }
    const unsupported = createOutgoingComposer(unsupportedAdapter, bridge)

    await expect(unsupported.translateForPreview()).rejects.toThrow('chat_unsupported')
    expect(bridge.translate).not.toHaveBeenCalled()
  })

  it('preserves composer text when translation fails', async () => {
    await adapter.replaceComposer('Translation failure text')
    bridge.translate.mockRejectedValueOnce(new Error('network_error'))
    const failing = createOutgoingComposer(adapter, bridge)

    await expect(failing.translateForPreview()).rejects.toThrow('network_error')
    expect(adapter.readComposer()).toBe('Translation failure text')
    expect(failing.getPreview()).toBeUndefined()
  })

  it('rejects stale replacement after the user edits the composer', async () => {
    const editingComposer = createOutgoingComposer(adapter, bridge)
    await adapter.replaceComposer('Original draft')
    await editingComposer.translateForPreview()
    await adapter.replaceComposer('Edited draft')

    expect(await editingComposer.replaceWithPreview()).toBe(false)
    expect(adapter.readComposer()).toBe('Edited draft')
  })

  it('reports failure when the draft changes before translation replacement', async () => {
    await adapter.replaceComposer('Original draft')
    let resolveTranslation: ((value: { translation: string }) => void) | undefined
    bridge.translate.mockImplementationOnce(() => new Promise((resolve) => {
      resolveTranslation = resolve
    }))
    const composer = createOutgoingComposer(adapter, bridge)

    const task = composer.translateAndReplace()
    await Promise.resolve()
    await adapter.replaceComposer('Edited draft')
    resolveTranslation?.({ translation: 'Translated draft' })

    await expect(task).rejects.toThrow('composer_changed')
    expect(adapter.readComposer()).toBe('Edited draft')
  })

  it('does not replace a different chat after an in-flight translation', async () => {
    const racingComposer = createOutgoingComposer(adapter, bridge)
    await racingComposer.translateForPreview()
    racingComposer.invalidateChat()
    await adapter.replaceComposer('Other chat draft')

    expect(await racingComposer.replaceWithPreview()).toBe(false)
    expect(adapter.readComposer()).toBe('Other chat draft')
  })

  it('invalidates a preview when the selected chat language changes', async () => {
    const languageComposer = createOutgoingComposer(adapter, bridge)
    await languageComposer.translateForPreview()
    languageComposer.setTargetLanguage('en')

    expect(languageComposer.getPreview()).toBeUndefined()
  })

  it('supports Alt+T as the preview shortcut', async () => {
    const shortcutComposer = createOutgoingComposer(adapter, bridge)
    const handler = vi.fn()
    shortcutComposer.bindShortcut(document, handler)

    document.dispatchEvent(new KeyboardEvent('keydown', { altKey: true, key: 'T' }))
    expect(handler).toHaveBeenCalledTimes(1)
  })
})

describe('preview restore', () => {
  it('replaces the composer and lets the user restore the Chinese original', async () => {
    await adapter.replaceComposer('请确认交期')
    const composer = createOutgoingComposer(adapter, bridge)
    bridge.translate.mockResolvedValue({ translation: 'Please confirm the lead time.', backTranslation: '请确认交期。', sourceLanguage: 'zh-CN' })

    const preview = await composer.translateForPreview()
    expect(preview).toEqual({
      backTranslation: '请确认交期。',
      composerVersion: '请确认交期',
      original: '请确认交期',
      targetLanguage: 'zh-CN',
      translated: 'Please confirm the lead time.',
    })
    expect(composer.canRestore()).toBe(false)

    await composer.replaceWithPreview()
    expect(adapter.readComposer()).toBe('Please confirm the lead time.')
    expect(composer.canRestore()).toBe(true)

    await composer.restoreOriginal()
    expect(adapter.readComposer()).toBe('请确认交期')
    expect(composer.canRestore()).toBe(false)
  })

  it('revokes the restore once the user edits the replaced text', async () => {
    await adapter.replaceComposer('请确认交期')
    const composer = createOutgoingComposer(adapter, bridge)
    await composer.translateForPreview()
    await composer.replaceWithPreview()

    await adapter.replaceComposer('Please confirm the lead time. Actually,')
    expect(composer.canRestore()).toBe(false)
    await expect(composer.restoreOriginal()).resolves.toBe(false)
    expect(adapter.readComposer()).toBe('Please confirm the lead time. Actually,')
  })

  it('returns undefined preview once the composer text diverges', async () => {
    await adapter.replaceComposer('请确认交期')
    const composer = createOutgoingComposer(adapter, bridge)
    await composer.translateForPreview()
    expect(composer.getPreview()).toEqual(expect.objectContaining({ original: '请确认交期' }))

    await adapter.replaceComposer('请确认交期和数量')
    expect(composer.getPreview()).toBeUndefined()
  })

  it('does not replace in a different chat after the language changed', async () => {
    await adapter.replaceComposer('请确认交期')
    const composer = createOutgoingComposer(adapter, bridge)
    await composer.translateForPreview()
    composer.setTargetLanguage('en')
    composer.invalidateChat()
    await adapter.replaceComposer('Other draft')

    expect(await composer.replaceWithPreview()).toBe(false)
  })
})
