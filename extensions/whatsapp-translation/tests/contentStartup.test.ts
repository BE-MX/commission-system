import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { afterEach, expect, it, vi } from 'vitest'

let page: JSDOM | undefined
const observers: MutationObserver[] = []

afterEach(() => {
  for (const observer of observers.splice(0)) observer.disconnect()
  page?.window.close()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.resetModules()
})

it('translates an already loaded chat without waiting for another DOM mutation or focus event', async () => {
  vi.useFakeTimers()
  page = new JSDOM(readFileSync(new URL('./fixtures/direct-nested-text.html', import.meta.url), 'utf8'), {
    url: 'https://web.whatsapp.com/',
  })
  Object.defineProperty(page.window.document, 'readyState', { value: 'complete' })
  vi.stubGlobal('document', page.window.document)
  vi.stubGlobal('window', page.window)
  const NativeObserver = page.window.MutationObserver
  vi.stubGlobal('MutationObserver', class extends NativeObserver {
    constructor(callback: MutationCallback) {
      super(callback)
      observers.push(this)
    }
  })
  const sendMessage = vi.fn(async (request: { type: string }) => {
    if (request.type === 'chat-language/get') return { type: request.type, targetLanguage: 'en' }
    if (request.type === 'translation/incoming') {
      return { type: request.type, sourceLanguage: 'en', translation: 'Synthetic translated reply' }
    }
    return { type: request.type }
  })
  vi.stubGlobal('chrome', { runtime: { sendMessage } })

  await import('@/content/index')

  await vi.waitFor(() => {
    const incomingRequests = sendMessage.mock.calls.filter(([request]) => request.type === 'translation/incoming')
    expect(incomingRequests).toHaveLength(2)
  })
})
