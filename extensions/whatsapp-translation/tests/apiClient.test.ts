import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '@/background/apiClient'
import type { ReplyRequest } from '@/shared/contracts'

const fetchMock = vi.fn()
const getPlatformInfo = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  getPlatformInfo.mockReset().mockImplementation(callback => callback({ os: 'win', arch: 'x86-64', nacl_arch: 'x86-64' }))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('chrome', { runtime: { getPlatformInfo } })
})

afterEach(() => { vi.useRealTimers() })

describe('Ark API client', () => {
  const replyPayload: ReplyRequest = {
    request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63', conversation_epoch: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de64',
    context_version: 1, draft_version: 2, messages: [{ role: 'customer', text: 'Synthetic question' }],
    context_scope: { requested_limit: 20, truncated: false, omitted_media: false, latest_visible: false },
    draft_intent: '', target_language: 'auto', fallback_language: 'en', goal: '', style: 'default',
  }
  it('sends reply POST no-store and never retries transport errors', async () => {
    fetchMock.mockRejectedValue(new TypeError('Synthetic private transport detail'))
    await expect(apiClient.suggestReply('token', '1.2.6', replyPayload)).rejects.toMatchObject({ code: 'network_error', message: 'request failed' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://leshine.cloud/api/whatsapp-translation/reply-suggestions')
    expect(init).toMatchObject({ cache: 'no-store', method: 'POST', body: JSON.stringify(replyPayload) })
  })
  it('aborts reply at 185 seconds with no automatic retry and clears keepalive', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const outcome = apiClient.suggestReply('token', '1.2.6', replyPayload).catch(error => error)
    await vi.advanceTimersByTimeAsync(185_000)
    expect(await outcome).toMatchObject({ code: 'request_timeout' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })
  it('unwraps the numeric Ark envelope and sends device credentials only on device routes', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      code: 200,
      data: { device_id: 7 },
      message: 'ok',
    }), { status: 200 }))

    await expect(apiClient.getSession('token', '1.0.0')).resolves.toEqual({ device_id: 7 })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://leshine.cloud/api/whatsapp-translation/session')
    expect(init.headers.Authorization).toBe('Bearer token')
    expect(init.headers['X-Ark-Extension-Version']).toBe('1.0.0')
  })

  it('maps stable backend error codes without exposing body details', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      code: 429,
      data: { error_code: 'rate_limited' },
      message: 'limited',
    }), { status: 429 }))

    await expect(apiClient.exchangePairing('device-code')).rejects.toMatchObject({ code: 'rate_limited' })
  })

  it('aborts requests after 20 seconds', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementation((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))

    const request = apiClient.getSession('token', '1.0.0')
    const expectation = expect(request).rejects.toThrow('request_timeout')
    await vi.advanceTimersByTimeAsync(20_000)
    await expectation
    expect(getPlatformInfo).not.toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('retries one translation transport failure with the identical request id', async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError('connection reset'))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 200,
        data: {
          detected_source_language: 'en',
          model_log_id: 7,
          request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
          translated_text: '合成译文',
        },
        message: 'ok',
      }), { status: 200 }))

    await expect(apiClient.translate('token', '1.2.0', {
      direction: 'incoming',
      request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
      source_language: 'auto',
      target_language: 'zh-CN',
      text: 'Synthetic text',
    })).resolves.toMatchObject({ translated_text: '合成译文' })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][0]).toBe('https://leshine.cloud/api/whatsapp-translation/translate')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).request_id).toBe(JSON.parse(fetchMock.mock.calls[1][1].body).request_id)
  })

  it('retries an unstructured gateway failure but not a stable quota error', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response('gateway unavailable', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 200,
        data: {
          detected_source_language: 'en',
          model_log_id: 8,
          request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
          translated_text: '合成译文',
        },
        message: 'ok',
      }), { status: 200 }))
    const payload = {
      direction: 'incoming' as const,
      request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
      source_language: 'auto',
      target_language: 'zh-CN',
      text: 'Synthetic text',
    }

    await expect(apiClient.translate('token', '1.2.0', payload)).resolves.toMatchObject({ translated_text: '合成译文' })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    fetchMock.mockReset().mockResolvedValue(new Response(JSON.stringify({
      code: 429,
      data: { error_code: 'daily_quota_exceeded' },
      message: 'quota',
    }), { status: 429 }))
    await expect(apiClient.translate('token', '1.2.0', payload)).rejects.toMatchObject({ code: 'daily_quota_exceeded' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('retries a structured transient gateway response', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 503,
        data: { error_code: 'ai_unavailable' },
        message: 'temporarily unavailable',
      }), { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 200,
        data: {
          detected_source_language: 'de',
          model_log_id: 9,
          request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
          translated_text: '合成译文',
        },
        message: 'ok',
      }), { status: 200 }))

    await expect(apiClient.translate('token', '1.2.0', {
      direction: 'incoming',
      request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
      source_language: 'auto',
      target_language: 'zh-CN',
      text: 'Synthetic text',
    })).resolves.toMatchObject({ translated_text: '合成译文' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('bounds both translation transport attempts to one 45-second budget', async () => {
    vi.useFakeTimers()
    fetchMock
      .mockImplementationOnce(() => new Promise((_resolve, reject) => {
        setTimeout(() => reject(new TypeError('connection reset')), 5_000)
      }))
      .mockImplementationOnce((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }))

    const request = apiClient.translate('token', '1.2.0', {
      direction: 'incoming',
      request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
      source_language: 'auto',
      target_language: 'zh-CN',
      text: 'Synthetic text',
    })
    const outcome = request.catch(error => error)
    await vi.advanceTimersByTimeAsync(44_999)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(await outcome).toMatchObject({ code: 'request_timeout' })
    expect(getPlatformInfo).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
    vi.useRealTimers()
  })

  it.each(['incoming', 'outgoing'] as const)('waits for a 41-second %s translation response', async direction => {
    vi.useFakeTimers()
    fetchMock.mockImplementation((_url: string, init: RequestInit) => new Promise((resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      setTimeout(() => resolve(new Response(JSON.stringify({
        code: 200, message: 'ok', data: {
          detected_source_language: 'en', model_log_id: 10,
          request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63', translated_text: 'Synthetic translation',
        },
      }), { status: 200 })), 41_000)
    }))
    const result = apiClient.translate('token', '1.2.2', {
      direction, request_id: '4f1d9b4f-0cd1-4cdf-bf9a-2e13e2e0de63',
      source_language: 'auto', target_language: 'zh-CN', text: 'Synthetic text',
    })
    const outcome = result.then(data => ({ data }), error => ({ error }))
    await vi.advanceTimersByTimeAsync(41_000)
    expect(await outcome).toMatchObject({ data: { translated_text: 'Synthetic translation' } })
    expect(getPlatformInfo).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
    vi.useRealTimers()
  })
})
