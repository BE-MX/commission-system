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
})
