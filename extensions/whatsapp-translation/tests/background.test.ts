import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReplyRequest } from '@/shared/contracts'

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
  const payload: ReplyRequest = {
    request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63', conversation_epoch: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de64',
    context_version: 1, draft_version: 2, messages: [{ role: 'customer', text: 'Synthetic question' }],
    context_scope: { requested_limit: 20, truncated: false, omitted_media: false, latest_visible: false },
    draft_intent: '', target_language: 'auto', fallback_language: 'en', goal: '', style: 'default',
  }
  const sender = { id: 'extension-id', url: 'https://web.whatsapp.com/' }
  async function dispatch(request: unknown, origin = sender): Promise<unknown> {
    return new Promise(resolve => { messageListener?.(request, origin, resolve) })
  }
  it('requires the WhatsApp sender and disclosure before any reply text request', async () => {
    store.set('deviceToken', 'synthetic-token')
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/suggest', payload }, { ...sender, url: 'https://example.test/' })).toEqual({ type: 'error', message: 'unsupported_request' })
    expect(await dispatch({ type: 'reply/suggest', payload })).toEqual({ type: 'error', message: 'reply_disclosure_required' })
    expect(fetch).not.toHaveBeenCalled()
    await dispatch({ type: 'reply/disclosure', acknowledged: true })
    expect(store.get('replyDisclosureAcknowledged')).toBe(true)
    expect([...store.keys()].sort()).toEqual(['deviceToken', 'replyDisclosureAcknowledged'])
  })
  it('fails closed on old capabilities without sending text, keeping translation separate', async () => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 200, message: 'ok', data: { directions: ['incoming', 'outgoing'] } })))
    vi.stubGlobal('fetch', fetch)
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/suggest', payload })).toEqual({ type: 'error', message: 'reply_unavailable' })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][0]).toContain('/capabilities')
    expect(fetch.mock.calls[0][1].body).toBeUndefined()
  })
  it('rejects malformed reply context before network and sanitizes unexpected API codes', async () => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 500, message: 'private detail', data: { error_code: 'Synthetic raw private body' } }), { status: 500 }))
    vi.stubGlobal('fetch', fetch)
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/suggest', payload: { ...payload, messages: [{ role: 'unknown', text: 'x' }] } })).toEqual({ type: 'error', message: 'reply_invalid_request' })
    expect(fetch).not.toHaveBeenCalled()
    expect(await dispatch({ type: 'reply/suggest', payload })).toEqual({ type: 'error', message: 'reply_failed' })
  })
  it('rechecks a lower live server limit before POSTing any text', async () => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 200, message: 'ok', data: { reply: {
      available: true, max_messages: 40, default_messages: 20, max_context_chars: 6000,
      max_draft_chars: 1000, max_goal_chars: 100, timeout_seconds: 30,
    } } })))
    vi.stubGlobal('fetch', fetch)
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/suggest', payload: { ...payload, messages: [{ role: 'customer', text: 'x'.repeat(8000) }] } })).toEqual({ type: 'error', message: 'reply_context_too_large' })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][0]).toContain('/capabilities')
    expect(fetch.mock.calls[0][1].body).toBeUndefined()
  })
  it.each(['messages', 'draft', 'goal'] as const)('rejects requests exceeding the current server %s bound before POST', async field => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 200, message: 'ok', data: { reply: {
      available: true, max_messages: 1, default_messages: 1, max_context_chars: 6000,
      max_draft_chars: 1, max_goal_chars: 1, timeout_seconds: 30,
    } } })))
    vi.stubGlobal('fetch', fetch); await import('@/background/index')
    const input = { ...payload, ...(field === 'messages' ? { messages: [...payload.messages, ...payload.messages] } : field === 'draft' ? { draft_intent: 'xx' } : { goal: 'xx' }) }
    expect(await dispatch({ type: 'reply/suggest', payload: input })).toEqual({ type: 'error', message: field === 'messages' ? 'reply_context_too_large' : field === 'draft' ? 'reply_draft_too_long' : 'reply_goal_too_long' })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][1].body).toBeUndefined()
  })
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
