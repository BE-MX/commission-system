// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { adapterFor } from '@/whatsapp/adapter'
import { createOutgoingComposer } from '@/content/outgoingComposer'
import { resolveTargetLanguage, updateTargetLanguage } from '@/content/chatLanguage'

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

describe('per-chat language', () => {
  it('reads and writes language through background without a readable title', async () => {
    const background = {
      getLanguage: vi.fn().mockResolvedValue('zh-CN'),
      setLanguage: vi.fn().mockResolvedValue('en'),
    }

    await expect(resolveTargetLanguage(background, 'conversation title')).resolves.toBe('zh-CN')
    await expect(updateTargetLanguage(background, 'conversation title', 'en')).resolves.toBe('en')
    expect(background.getLanguage).toHaveBeenCalledWith('conversation title')
    expect(background.setLanguage).toHaveBeenCalledWith('conversation title', 'en')
  })
})
