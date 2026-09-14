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
      getPlatformInfo: (callback?: () => void) => callback?.(),
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
  it('preserves history support from the API through background and content validation', async () => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    const reply = { available: true, history_enabled: true, max_messages: 2000, default_messages: 2000,
      max_context_chars: 120000, max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 120 }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 200, message: 'ok', data: { reply } }))))
    await import('@/background/index')
    const result = await dispatch({ type: 'reply/capabilities' }) as { reply: unknown }
    const { boundedReplyCapabilities } = await import('@/shared/replyValidation')
    expect(boundedReplyCapabilities(result.reply)).toMatchObject(reply)
  })
  it.each([undefined, false])('still rejects a backend without history support (%s)', async history_enabled => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 200, message: 'ok', data: { reply: {
      available: true, history_enabled, max_messages: 2000, default_messages: 2000,
      max_context_chars: 120000, max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 120,
    } } }))))
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/capabilities' })).toEqual({ type: 'error', message: 'reply_backend_update_required' })
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
  it('rejects an unsupported detected language before any network call', async () => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/suggest', payload: { ...payload, detected_language: 'klingon' } })).toEqual({ type: 'error', message: 'reply_invalid_request' })
    expect(fetch).not.toHaveBeenCalled()
  })
  it('rechecks a lower live server limit before POSTing any text', async () => {
    store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 200, message: 'ok', data: { reply: {
      available: true, history_enabled: true, max_messages: 40, default_messages: 20, max_context_chars: 6000,
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
      available: true, history_enabled: true, max_messages: 1, default_messages: 1, max_context_chars: 6000,
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

describe('chat inquiry bindings', () => {
  const sender = { id: 'extension-id', url: 'https://web.whatsapp.com/' }
  const inquiryId = '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63'
  async function dispatch(request: unknown, origin = sender): Promise<unknown> {
    return new Promise(resolve => { messageListener?.(request, origin, resolve) })
  }
  it('stores bindings under salted hashes and reads them back', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/memory-binding/set', chatTitle: 'Alice Example', inquiryId })).toEqual({ type: 'reply/memory-binding/set' })
    expect(await dispatch({ type: 'reply/memory-binding/get', chatTitle: 'Alice Example' })).toEqual({ type: 'reply/memory-binding/get', inquiryId })
    const bindings = store.get('chatInquiries') as Record<string, string>
    expect(Object.values(bindings)).toEqual([inquiryId])
    expect(Object.keys(bindings)[0]).toMatch(/^[0-9a-f]{64}$/)
    expect(JSON.stringify(bindings)).not.toContain('Alice')
    expect(await dispatch({ type: 'reply/memory-binding/get', chatTitle: 'Someone Else' })).toEqual({ type: 'reply/memory-binding/get', inquiryId: null })
  })
  it('clears a binding and rejects malformed inquiry ids', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    await import('@/background/index')
    await dispatch({ type: 'reply/memory-binding/set', chatTitle: 'Alice Example', inquiryId })
    expect(await dispatch({ type: 'reply/memory-binding/set', chatTitle: 'Alice Example', inquiryId: null })).toEqual({ type: 'reply/memory-binding/set' })
    expect(await dispatch({ type: 'reply/memory-binding/get', chatTitle: 'Alice Example' })).toEqual({ type: 'reply/memory-binding/get', inquiryId: null })
    expect(store.get('chatInquiries')).toEqual({})
    expect(await dispatch({ type: 'reply/memory-binding/set', chatTitle: 'Alice Example', inquiryId: 'not-a-uuid' })).toEqual({ type: 'error', message: 'reply_invalid_request' })
  })
  it('evicts the oldest binding beyond 200 entries but never on update', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    const seeded: Record<string, string> = {}
    for (let i = 0; i < 200; i++) seeded[`hash-${String(i).padStart(3, '0')}`] = `inquiry-${i}`
    store.set('chatInquiries', seeded)
    await import('@/background/index')
    await dispatch({ type: 'reply/memory-binding/set', chatTitle: 'New Chat', inquiryId })
    let bindings = store.get('chatInquiries') as Record<string, string>
    expect(Object.keys(bindings)).toHaveLength(200)
    expect(bindings['hash-000']).toBeUndefined()
    expect(bindings['hash-001']).toBe('inquiry-1')
    const { chatKey } = await import('@/shared/storage')
    const key = await chatKey('New Chat', 'synthetic-salt')
    expect(bindings[key]).toBe(inquiryId)
    await dispatch({ type: 'reply/memory-binding/set', chatTitle: 'New Chat', inquiryId: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de64' })
    bindings = store.get('chatInquiries') as Record<string, string>
    expect(Object.keys(bindings)).toHaveLength(200)
    expect(bindings['hash-001']).toBe('inquiry-1')
    expect(bindings[key]).toBe('4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de64')
  })
  it('requires the WhatsApp sender', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/memory-binding/get', chatTitle: 'Alice Example' }, { id: 'extension-id', url: 'https://example.test/' }))
      .toEqual({ type: 'error', message: 'unsupported_request' })
  })
})

describe('auto takeover policy', () => {
  const sender = { id: 'extension-id', url: 'https://web.whatsapp.com/' }
  async function dispatch(request: unknown, origin = sender): Promise<unknown> {
    return new Promise(resolve => { messageListener?.(request, origin, resolve) })
  }
  it('defaults to unrestricted for any chat', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/auto-policy/get', chatTitle: 'Alice Example' }))
      .toEqual({ type: 'reply/auto-policy/get', blocked: false, allowlisted: false, allowlistEnabled: false, schedule: null })
  })
  it('stores list entries under salted hashes and toggles them per chat', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/auto-policy/set-chat', chatTitle: 'Alice Example', list: 'block', value: true })).toEqual({ type: 'reply/auto-policy/set-chat' })
    expect(await dispatch({ type: 'reply/auto-policy/get', chatTitle: 'Alice Example' })).toMatchObject({ blocked: true, allowlisted: false })
    expect(await dispatch({ type: 'reply/auto-policy/get', chatTitle: 'Someone Else' })).toMatchObject({ blocked: false })
    const blocklist = store.get('autoReplyBlocklist') as Record<string, boolean>
    expect(Object.keys(blocklist)[0]).toMatch(/^[0-9a-f]{64}$/)
    expect(JSON.stringify(blocklist)).not.toContain('Alice')
    expect(await dispatch({ type: 'reply/auto-policy/set-chat', chatTitle: 'Alice Example', list: 'block', value: false })).toEqual({ type: 'reply/auto-policy/set-chat' })
    expect(await dispatch({ type: 'reply/auto-policy/get', chatTitle: 'Alice Example' })).toMatchObject({ blocked: false })
    expect(await dispatch({ type: 'reply/auto-policy/set-chat', chatTitle: 'Alice Example', list: 'both', value: true })).toEqual({ type: 'error', message: 'reply_invalid_request' })
  })
  it('evicts the oldest policy entry beyond 500 per list but never on update', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    const seeded: Record<string, boolean> = {}
    for (let i = 0; i < 500; i++) seeded[`hash-${String(i).padStart(3, '0')}`] = true
    store.set('autoReplyAllowlist', seeded)
    await import('@/background/index')
    await dispatch({ type: 'reply/auto-policy/set-chat', chatTitle: 'New Chat', list: 'allow', value: true })
    let allowlist = store.get('autoReplyAllowlist') as Record<string, boolean>
    expect(Object.keys(allowlist)).toHaveLength(500)
    expect(allowlist['hash-000']).toBeUndefined()
    expect(allowlist['hash-001']).toBe(true)
    await dispatch({ type: 'reply/auto-policy/set-chat', chatTitle: 'New Chat', list: 'allow', value: true })
    allowlist = store.get('autoReplyAllowlist') as Record<string, boolean>
    expect(Object.keys(allowlist)).toHaveLength(500)
    expect(allowlist['hash-001']).toBe(true)
  })
  it('toggles allowlist mode and validates the schedule', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/auto-policy/set-allowlist-enabled', enabled: true })).toEqual({ type: 'reply/auto-policy/set-allowlist-enabled' })
    expect(await dispatch({ type: 'reply/auto-policy/get', chatTitle: 'Alice Example' })).toMatchObject({ allowlistEnabled: true })
    const schedule = { start: '09:00', end: '18:30', days: [1, 2, 3, 4, 5] }
    expect(await dispatch({ type: 'reply/auto-policy/set-schedule', schedule })).toEqual({ type: 'reply/auto-policy/set-schedule' })
    expect(await dispatch({ type: 'reply/auto-policy/get', chatTitle: 'Alice Example' })).toMatchObject({ schedule })
    expect(await dispatch({ type: 'reply/auto-policy/set-schedule', schedule: null })).toEqual({ type: 'reply/auto-policy/set-schedule' })
    for (const bad of [{ start: '25:00', end: '18:00', days: [1] }, { start: '09:00', end: '18:00', days: [7] },
      { start: '09:00', end: '18:00', days: [] }, { start: '9:00', end: '18:00', days: [1] }, 'open']) {
      expect(await dispatch({ type: 'reply/auto-policy/set-schedule', schedule: bad })).toEqual({ type: 'error', message: 'reply_invalid_request' })
    }
    expect(await dispatch({ type: 'reply/auto-policy/set-allowlist-enabled', enabled: 'yes' })).toEqual({ type: 'error', message: 'reply_invalid_request' })
  })
  it('requires the WhatsApp sender', async () => {
    store.set('chatKeySalt', 'synthetic-salt')
    await import('@/background/index')
    expect(await dispatch({ type: 'reply/auto-policy/get', chatTitle: 'Alice Example' }, { id: 'extension-id', url: 'https://example.test/' }))
      .toEqual({ type: 'error', message: 'unsupported_request' })
  })
})

describe('reply suggest timeout', () => {
  const sender = { id: 'extension-id', url: 'https://web.whatsapp.com/' }
  const payload: ReplyRequest = {
    request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63', conversation_epoch: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de64',
    context_version: 1, draft_version: 2, messages: [{ role: 'customer', text: 'Synthetic question' }],
    context_scope: { requested_limit: 20, truncated: false, omitted_media: false, latest_visible: false },
    draft_intent: '', target_language: 'auto', fallback_language: 'en', goal: '', style: 'default',
  }
  async function dispatch(request: unknown): Promise<unknown> {
    return new Promise(resolve => { messageListener?.(request, sender, resolve) })
  }
  it('times the suggest request out at the capability timeout_seconds', async () => {
    vi.useFakeTimers()
    try {
      store.set('deviceToken', 'synthetic-token'); store.set('replyDisclosureAcknowledged', true)
      const fetch = vi.fn((url: string, init?: RequestInit) => {
        if (String(url).includes('/capabilities')) {
          return Promise.resolve(new Response(JSON.stringify({ code: 200, message: 'ok', data: { reply: {
            available: true, history_enabled: true, max_messages: 2000, default_messages: 2000,
            max_context_chars: 120000, max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 60,
          } } })))
        }
        return new Promise((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
      })
      vi.stubGlobal('fetch', fetch)
      await import('@/background/index')
      let settled = false
      const outcome = dispatch({ type: 'reply/suggest', payload }).then(response => { settled = true; return response })
      await vi.advanceTimersByTimeAsync(59_999)
      expect(settled).toBe(false)
      await vi.advanceTimersByTimeAsync(1)
      expect(await outcome).toEqual({ type: 'error', message: 'request_timeout' })
      expect(fetch).toHaveBeenCalledTimes(2)
      expect(fetch.mock.calls[1][0]).toContain('/reply-suggestions')
    } finally { vi.useRealTimers() }
  })
})
