// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { IncomingBridgeError, createIncomingTranslator } from '@/content/incomingTranslator'
import type { IncomingBridge, IncomingRenderer } from '@/content/incomingTranslator'
import { mountTranslation } from '@/content/render'
import { TARGET_LANGUAGES } from '@/shared/contracts'

const adapter = {
  inspectChat: vi.fn(),
  listUntranslatedIncomingMessages: vi.fn(),
}
const bridge = {
  translate: vi.fn(),
} as IncomingBridge & { translate: ReturnType<typeof vi.fn> }
const renderer = {
  mountTranslation: vi.fn(),
} as IncomingRenderer & { mountTranslation: ReturnType<typeof vi.fn> }

function incomingMessage(text: string, localKey: string) {
  const element = document.createElement('div')
  element.textContent = text
  return { element, localKey, text }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  document.body.replaceChildren()
  adapter.inspectChat.mockReturnValue({ kind: 'direct' })
  adapter.listUntranslatedIncomingMessages.mockResolvedValue([])
})

afterEach(() => {
  vi.useRealTimers()
})

describe('incoming translator', () => {
  it('offers every detected customer language as an outgoing target', () => {
    expect(TARGET_LANGUAGES).toEqual(['zh-CN', 'en', 'es', 'fr', 'ar', 'ja', 'de', 'nl', 'sv'])
  })

  it('debounces mutations and translates one batch', async () => {
    const controller = createIncomingTranslator(adapter, bridge, renderer)
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([incomingMessage('Hello', 'key-1')])
    bridge.translate.mockResolvedValue({ translation: 'Translated' })

    controller.notifyMutation()
    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(299)
    expect(bridge.translate).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)

    expect(bridge.translate).toHaveBeenCalledTimes(1)
    expect(bridge.translate).toHaveBeenCalledWith(expect.objectContaining({
      direction: 'incoming',
      request_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
      source_language: 'auto',
      target_language: 'zh-CN',
      text: 'Hello',
    }))
    expect(renderer.mountTranslation).toHaveBeenCalledWith(expect.anything(), {
      kind: 'success',
      translation: 'Translated',
    }, expect.anything())
  })

  it('does not postpone a scheduled scan while mutations continue', async () => {
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(100)
    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(199)
    expect(adapter.listUntranslatedIncomingMessages).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)

    expect(adapter.listUntranslatedIncomingMessages).toHaveBeenCalledTimes(1)
  })

  it('runs at most three translations and exposes a manual action for queued messages', async () => {
    const messages = Array.from({ length: 4 }, (_, index) => incomingMessage(`Text ${index + 1}`, `key-${index + 1}`))
    adapter.listUntranslatedIncomingMessages.mockResolvedValue(messages)
    bridge.translate.mockImplementation(() => new Promise(() => {}))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    expect(bridge.translate).toHaveBeenCalledTimes(3)

    await vi.advanceTimersByTimeAsync(1_000)
    const pendingCall = renderer.mountTranslation.mock.calls.find(([, state]) => state.kind === 'pending')
    expect(pendingCall?.[0]).toBe(messages[3].element)
    expect(pendingCall?.[2]).toBeTypeOf('function')
  })

  it('promotes the manually requested message to the next free worker slot', async () => {
    const messages = Array.from({ length: 5 }, (_, index) => incomingMessage(`Text ${index + 1}`, `key-${index + 1}`))
    const pendingResolvers: Array<(value: { translation: string }) => void> = []
    adapter.listUntranslatedIncomingMessages.mockResolvedValue(messages)
    bridge.translate.mockImplementation(() => new Promise(resolve => pendingResolvers.push(resolve)))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    await vi.advanceTimersByTimeAsync(1_000)
    const fifthPending = renderer.mountTranslation.mock.calls.find(([element, state]) => (
      element === messages[4].element && state.kind === 'pending'
    ))
    fifthPending?.[2]?.()
    pendingResolvers[0]({ translation: 'Done' })
    await vi.advanceTimersByTimeAsync(0)

    expect(bridge.translate).toHaveBeenCalledTimes(4)
    expect(bridge.translate.mock.calls[3][0].text).toBe('Text 5')
  })

  it('coalesces duplicate scans for the same local message key', async () => {
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([incomingMessage('Hello', 'key-1')])
    bridge.translate.mockImplementation(() => new Promise(() => {}))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)

    expect(bridge.translate).toHaveBeenCalledTimes(1)
  })

  it('ignores a response from the previous chat generation', async () => {
    let resolveOld: ((value: { translation: string }) => void) | undefined
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([incomingMessage('Old chat', 'old-key')])
    bridge.translate.mockImplementationOnce(() => new Promise(resolve => {
      resolveOld = resolve
    }))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    controller.chatChanged()
    resolveOld?.({ translation: 'Old translation' })
    await Promise.resolve()

    expect(renderer.mountTranslation).not.toHaveBeenCalledWith(expect.anything(), {
      kind: 'success',
      translation: 'Old translation',
    }, expect.anything())
  })

  it('translates every visible direct message', async () => {
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([
      incomingMessage('First', 'key-1'),
      incomingMessage('Second', 'key-2'),
    ])
    bridge.translate.mockImplementation(async request => ({ translation: `Translated ${request.text}` }))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)

    expect(bridge.translate).toHaveBeenCalledTimes(2)
    expect(renderer.mountTranslation.mock.calls.filter(([, state]) => state.kind === 'success')).toHaveLength(2)
  })

  it('makes no API call for group or unknown chats', async () => {
    for (const kind of ['group', 'unknown', 'no_chat'] as const) {
      vi.clearAllMocks()
      adapter.inspectChat.mockReturnValue({ kind })
      const controller = createIncomingTranslator(adapter, bridge, renderer)
      controller.notifyMutation()
      await vi.advanceTimersByTimeAsync(300)
      expect(bridge.translate).not.toHaveBeenCalled()
    }
  })

  it('stops translating after revoked authentication', async () => {
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([incomingMessage('Hello', 'key-1')])
    bridge.translate.mockRejectedValueOnce(new IncomingBridgeError('device_revoked', 'revoked'))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    expect(renderer.mountTranslation).toHaveBeenCalledWith(expect.anything(), { code: 'device_revoked', kind: 'blocked' }, undefined)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(1_000)
    expect(bridge.translate).toHaveBeenCalledTimes(1)
  })

  it('settles every in-flight task on a global stop and retries them after resume', async () => {
    const messages = Array.from({ length: 3 }, (_, index) => incomingMessage(`Text ${index + 1}`, `key-${index + 1}`))
    const resolveCalls: Array<(value: { translation: string }) => void> = []
    const rejectCalls: Array<(error: unknown) => void> = []
    adapter.listUntranslatedIncomingMessages.mockResolvedValue(messages)
    bridge.translate.mockImplementation(() => new Promise((resolve, reject) => {
      resolveCalls.push(resolve)
      rejectCalls.push(reject)
    }))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    rejectCalls[0](new IncomingBridgeError('device_revoked', 'revoked'))
    await vi.advanceTimersByTimeAsync(0)

    for (const message of messages) {
      expect(renderer.mountTranslation).toHaveBeenCalledWith(
        message.element,
        { code: 'device_revoked', kind: 'blocked' },
        undefined,
      )
    }

    resolveCalls[1]({ translation: 'Stale translation' })
    resolveCalls[2]({ translation: 'Stale translation' })
    await vi.advanceTimersByTimeAsync(0)
    controller.resume()
    await vi.advanceTimersByTimeAsync(0)

    expect(bridge.translate).toHaveBeenCalledTimes(6)
    for (const resolve of resolveCalls.slice(3)) resolve({ translation: 'Recovered translation' })
    await vi.advanceTimersByTimeAsync(0)
    expect(renderer.mountTranslation.mock.calls.filter(([, state]) => (
      state.kind === 'success' && state.translation === 'Recovered translation'
    ))).toHaveLength(3)
  })

  it('pauses after a rate limit response and retries after the window', async () => {
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([incomingMessage('Hello', 'key-1')])
    bridge.translate
      .mockRejectedValueOnce(new IncomingBridgeError('rate_limited', 'limited', 5_000))
      .mockResolvedValueOnce({ translation: 'Translated' })
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    expect(bridge.translate).toHaveBeenCalledTimes(1)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    expect(bridge.translate).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(5_000)
    expect(bridge.translate).toHaveBeenCalledTimes(2)
  })

  it('shows a retryable state after a 20-second timeout', async () => {
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([incomingMessage('Hello', 'key-1')])
    bridge.translate.mockImplementation(() => new Promise(() => {}))
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    await vi.advanceTimersByTimeAsync(20_000)
    const [, state, onRetry] = renderer.mountTranslation.mock.calls.at(-1)!
    expect(state).toEqual({ code: 'request_timeout', kind: 'retryable_error' })
    expect(onRetry).toBeTypeOf('function')
  })

  it('supports click-to-retry after a retryable network error', async () => {
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([incomingMessage('Hello', 'key-1')])
    bridge.translate
      .mockRejectedValueOnce(new IncomingBridgeError('network_error', 'network'))
      .mockResolvedValueOnce({ translation: 'Translated' })
    const controller = createIncomingTranslator(adapter, bridge, renderer)

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    const [, state, onRetry] = renderer.mountTranslation.mock.calls.at(-1)!
    expect(state.kind).toBe('retryable_error')
    onRetry?.()
    await vi.advanceTimersByTimeAsync(300)

    expect(bridge.translate).toHaveBeenCalledTimes(2)
    expect(bridge.translate.mock.calls[1][0].request_id).toBe(bridge.translate.mock.calls[0][0].request_id)
    expect(renderer.mountTranslation).toHaveBeenLastCalledWith(expect.anything(), {
      kind: 'success',
      translation: 'Translated',
    }, expect.anything())
  })
})

describe('translation renderer', () => {
  it('mounts extension-owned text in a closed shadow host', () => {
    const source = document.createElement('div')
    const shadow = mountTranslation(source, { kind: 'success', translation: 'Translated preview' })

    const host = source.querySelector('[data-ark-translation-host="1"]')
    expect(host).not.toBeNull()
    expect(host?.shadowRoot).toBeNull()
    expect(shadow.textContent).toContain('Translated preview')
    expect(source.innerHTML).not.toContain('Translated preview')
  })

  it('reports only the newest eligible incoming language', async () => {
    const first = incomingMessage('First synthetic message', 'key-1')
    const latest = incomingMessage('Letzte synthetische Nachricht', 'key-2')
    const onDetectedLanguage = vi.fn()
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([first, latest])
    bridge.translate.mockImplementation(async request => ({
      sourceLanguage: request.text.startsWith('First') ? 'en' : 'de',
      translation: 'Synthetic translation',
    }))
    const controller = createIncomingTranslator(adapter, bridge, renderer, { onDetectedLanguage })

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)

    expect(onDetectedLanguage).toHaveBeenCalledTimes(1)
    expect(onDetectedLanguage).toHaveBeenCalledWith(latest, 'de')
  })

  it('never rolls the reply language back when an older failed message is rescanned', async () => {
    const first = incomingMessage('First synthetic message', 'key-1')
    const latest = incomingMessage('Letzte synthetische Nachricht', 'key-2')
    const onDetectedLanguage = vi.fn()
    adapter.listUntranslatedIncomingMessages
      .mockResolvedValueOnce([first, latest])
      .mockResolvedValueOnce([first])
    let firstAttempts = 0
    bridge.translate.mockImplementation(async request => {
      if (request.text.startsWith('First')) {
        firstAttempts += 1
        if (firstAttempts === 1) throw new IncomingBridgeError('network_error', 'network')
        return { sourceLanguage: 'en', translation: 'First translation' }
      }
      return { sourceLanguage: 'de', translation: 'Latest translation' }
    })
    const controller = createIncomingTranslator(adapter, bridge, renderer, { onDetectedLanguage })

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    const retry = renderer.mountTranslation.mock.calls.find(([element, state]) => (
      element === first.element && state.kind === 'retryable_error'
    ))?.[2]
    expect(onDetectedLanguage).toHaveBeenCalledOnce()
    expect(onDetectedLanguage).toHaveBeenLastCalledWith(latest, 'de')

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)
    retry?.()
    await vi.advanceTimersByTimeAsync(0)

    expect(onDetectedLanguage).toHaveBeenCalledOnce()
  })

  it('does not change reply language from ambiguous short messages', async () => {
    const onDetectedLanguage = vi.fn()
    adapter.listUntranslatedIncomingMessages.mockResolvedValue([
      incomingMessage('OK', 'key-1'),
      incomingMessage('👍 100', 'key-2'),
    ])
    bridge.translate.mockResolvedValue({ sourceLanguage: 'en', translation: 'Synthetic translation' })
    const controller = createIncomingTranslator(adapter, bridge, renderer, { onDetectedLanguage })

    controller.notifyMutation()
    await vi.advanceTimersByTimeAsync(300)

    expect(onDetectedLanguage).not.toHaveBeenCalled()
  })

  it('renders a manual translate action for a pending message', () => {
    const source = document.createElement('div')
    const onTranslate = vi.fn()
    const shadow = mountTranslation(source, { kind: 'pending' }, onTranslate)

    const button = shadow.querySelector('button') as HTMLButtonElement
    expect(button.textContent).toBe('译此消息')
    button.click()
    expect(onTranslate).toHaveBeenCalledTimes(1)
  })
})
