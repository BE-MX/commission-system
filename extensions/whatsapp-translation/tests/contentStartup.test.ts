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

it.each([
  ['个人主页详情', null],
  ['个人主页详情', '早上7:14'],
  ['个人主页详情', '7:14 AM'],
  ['Profile details', '7:14 AM'],
])('mounts the toolbar and automatically translates %s with timestamp %s', async (label, localizedTime) => {
  vi.useFakeTimers()
  page = new JSDOM(readFileSync(new URL('./fixtures/direct-nested-text.html', import.meta.url), 'utf8'), {
    url: 'https://web.whatsapp.com/',
  })
  page.window.document.querySelector('[aria-label="个人主页详情"]')!.setAttribute('aria-label', label!)
  if (localizedTime) {
    for (const message of page.window.document.querySelectorAll('[data-testid="msg-container"]')) {
      message.querySelector('[data-testid="msg-meta"]')!.textContent = localizedTime
      const hidden = page.window.document.createElement('span')
      hidden.setAttribute('aria-hidden', 'true')
      hidden.textContent = localizedTime
      message.querySelector('.copyable-text')!.append(hidden)
    }
  }
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
    expect(page!.window.document.querySelector('[data-ark-outgoing-control="1"]')).not.toBeNull()
  })
})
