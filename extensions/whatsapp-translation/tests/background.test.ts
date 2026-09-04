import { beforeEach, describe, expect, it, vi } from 'vitest'

type MessageListener = (
  request: unknown,
  sender: { id?: string; url?: string },
  sendResponse: (response: unknown) => void,
) => boolean

let messageListener: MessageListener | undefined
const store = new Map<string, unknown>()
const setAccessLevel = vi.fn()

beforeEach(() => {
  store.clear()
  setAccessLevel.mockClear()
  vi.resetModules()
  vi.stubGlobal('chrome', {
    runtime: {
      getManifest: () => ({ version: '1.0.0' }),
      id: 'extension-id',
      onMessage: {
        addListener: (listener: MessageListener) => {
          messageListener = listener
        },
      },
    },
    storage: {
      local: {
        get: async (keys: string | string[] | Record<string, unknown>) => {
          if (typeof keys === 'string') return { [keys]: store.get(keys) }
          if (Array.isArray(keys)) return Object.fromEntries(keys.map(key => [key, store.get(key)]))
          return Object.fromEntries(Object.keys(keys).map(key => [key, store.get(key)]))
        },
        remove: async (keys: string | string[]) => {
          for (const key of Array.isArray(keys) ? keys : [keys]) store.delete(key)
        },
        set: async (values: Record<string, unknown>) => {
          for (const [key, value] of Object.entries(values)) store.set(key, value)
        },
        setAccessLevel,
      },
    },
  })
})

describe('background message dispatcher', () => {
  it('rejects messages from another extension and unknown requests', async () => {
    await import('@/background/index')
    const sendResponse = vi.fn()

    messageListener?.({ type: 'preferences/get' }, { id: 'other-extension' }, sendResponse)
    messageListener?.({ type: 'unknown' }, { id: 'extension-id' }, sendResponse)

    expect(sendResponse).toHaveBeenCalledWith({ type: 'error', message: 'unsupported_request' })
  })

  it('defaults the outgoing language to English', async () => {
    await import('@/background/index')
    const sendResponse = vi.fn()

    messageListener?.(
      { type: 'preferences/get' },
      { id: 'extension-id', url: 'chrome-extension://extension-id/src/popup/index.html' },
      sendResponse,
    )

    await vi.waitFor(() => {
      expect(sendResponse).toHaveBeenCalledWith({
        enabled: true,
        targetLanguage: 'en',
        type: 'preferences/get',
      })
    })
  })

  it('fails closed incoming translation when the popup disabled it', async () => {
    store.set('enabled', false)
    await import('@/background/index')
    const sendResponse = vi.fn()

    messageListener?.(
      {
        type: 'translation/incoming',
        request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
        source_language: 'auto',
        target_language: 'zh-CN',
        text: 'hello',
      },
      { id: 'extension-id' },
      sendResponse,
    )

    await vi.waitFor(() => {
      expect(sendResponse).toHaveBeenCalledWith({ type: 'error', message: 'translation_disabled' })
    })
  })

  it('handles popup preferences from the trusted popup URL', async () => {
    await import('@/background/index')
    const sendResponse = vi.fn()

    messageListener?.(
      { type: 'preferences/get' },
      { id: 'extension-id', url: 'chrome-extension://extension-id/src/popup/index.html' },
      sendResponse,
    )

    await vi.waitFor(() => {
      expect(sendResponse).toHaveBeenCalledWith({
        enabled: true,
        targetLanguage: 'en',
        type: 'preferences/get',
      })
    })
  })
})
