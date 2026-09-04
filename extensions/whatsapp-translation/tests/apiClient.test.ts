import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '@/background/apiClient'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

describe('Ark API client', () => {
  it('unwraps the numeric Ark envelope and sends device credentials only on device routes', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      code: 200,
      data: { device_id: 7 },
      message: 'ok',
    }), { status: 200 }))

    await expect(apiClient.getSession('token', '1.0.0')).resolves.toEqual({ device_id: 7 })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://leshine.work/api/whatsapp-translation/session')
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
})
