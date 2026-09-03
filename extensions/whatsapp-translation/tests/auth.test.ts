import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as apiClient from '@/background/apiClient'
import { finishPairing, refreshSession, resumePairing, startPairing } from '@/background/auth'
import { storage } from '@/shared/storage'

const deviceInfo = {
  browserName: 'Chrome',
  browserVersion: '140.0.0.0',
  deviceName: 'Windows',
  extensionVersion: '1.0.0',
}

const store = new Map<string, unknown>()
const fetchMock = vi.fn()

beforeEach(async () => {
  store.clear()
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('chrome', {
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
      },
    },
  })
})

describe('extension pairing', () => {
  it('keeps the raw token local until exchange reports ready', async () => {
    const createPairing = vi.spyOn(apiClient, 'createPairing').mockResolvedValue({
      authorize_url: 'https://leshine.work/whatsapp-translation/authorize#code',
      device_code: 'device-code',
      expires_at: '2027-03-02T10:00:00',
    })

    await startPairing(deviceInfo)
    const pendingToken = await storage.get('pendingDeviceToken')

    expect(pendingToken).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(createPairing).toHaveBeenCalledWith(expect.objectContaining({
      proposed_token_hash: expect.stringMatching(/^[0-9a-f]{64}$/),
    }))
    expect(JSON.stringify(createPairing.mock.calls)).not.toContain(pendingToken)
    expect(await storage.get('pendingDeviceCode')).toBe('device-code')
    expect(await storage.get('chatKeySalt')).toMatch(/^[0-9a-f]{32}$/)
  })

  it('clears stale local credentials before a new pairing is created', async () => {
    await storage.set({
      deviceToken: 'stale-token',
      pendingDeviceCode: 'old-device-code',
      pendingDeviceToken: 'old-pending-token',
    })
    const createPairing = vi.spyOn(apiClient, 'createPairing').mockResolvedValue({
      authorize_url: 'https://leshine.work/whatsapp-translation/authorize#new-code',
      device_code: 'new-device-code',
      expires_at: '2027-03-02T10:00:00',
    })

    await startPairing(deviceInfo)

    expect(createPairing).toHaveBeenCalledTimes(1)
    expect(await storage.get('deviceToken')).toBeUndefined()
    expect(await storage.get('pendingDeviceCode')).toBe('new-device-code')
    expect(await storage.get('pendingDeviceToken')).toMatch(/^[A-Za-z0-9_-]{43}$/)
  })

  it('rejects authorize URLs outside the approved route', async () => {
    vi.spyOn(apiClient, 'createPairing').mockResolvedValue({
      authorize_url: 'https://example.com/whatsapp-translation/authorize#code',
      device_code: 'device-code',
      expires_at: '2027-03-02T10:00:00',
    })

    await expect(startPairing(deviceInfo)).rejects.toThrow('invalid_authorize_url')
  })

  it('retains pending token across exchange retries and promotes it on ready', async () => {
    await storage.set({ pendingDeviceToken: 'pending-token', pendingDeviceCode: 'device-code' })
    const exchangePairing = vi.spyOn(apiClient, 'exchangePairing')
      .mockResolvedValueOnce({ status: 'pending' })
      .mockResolvedValueOnce({ device_id: 7, expires_at: '2027-03-02T10:00:00', status: 'ready' })

    await finishPairing('device-code', { wait: async () => {} })

    expect(exchangePairing).toHaveBeenCalledTimes(2)
    expect(await storage.get('deviceToken')).toBe('pending-token')
    expect(await storage.get('pendingDeviceToken')).toBeUndefined()
  })

  it('resumes a stored pairing without relying on popup memory', async () => {
    await storage.set({ pendingDeviceToken: 'pending-token', pendingDeviceCode: 'device-code' })
    vi.spyOn(apiClient, 'exchangePairing').mockResolvedValue({
      device_id: 7,
      expires_at: '2027-03-02T10:00:00',
      status: 'ready',
    })

    const state = await resumePairing({ attempts: 1 })

    expect(state).toEqual({ authorizeUrl: '', deviceCode: 'device-code', status: 'ready' })
    expect(await storage.get('deviceToken')).toBe('pending-token')
  })

  it('clears an expired stored pairing so authorization can restart', async () => {
    await storage.set({ pendingDeviceToken: 'pending-token', pendingDeviceCode: 'expired-code' })
    vi.spyOn(apiClient, 'exchangePairing').mockRejectedValue(
      new apiClient.ArkApiError('pairing_expired', 'expired'),
    )

    await expect(resumePairing({ attempts: 1 })).resolves.toBeNull()
    expect(await storage.get('pendingDeviceCode')).toBeUndefined()
    expect(await storage.get('pendingDeviceToken')).toBeUndefined()
  })

  it('does not replace an already active token from repeated ready responses', async () => {
    await storage.set({ deviceToken: 'active-token', pendingDeviceCode: 'device-code' })
    const exchangePairing = vi.spyOn(apiClient, 'exchangePairing')

    await finishPairing('device-code', { wait: async () => {} })

    expect(exchangePairing).not.toHaveBeenCalled()
    expect(await storage.get('deviceToken')).toBe('active-token')
  })

  it('clears local credentials when the server revokes the device', async () => {
    await storage.set({ deviceToken: 'active-token' })
    vi.spyOn(apiClient, 'getSession').mockRejectedValue(new apiClient.ArkApiError('device_revoked', 'revoked'))

    await expect(refreshSession('1.0.0')).resolves.toBeNull()
    expect(await storage.get('deviceToken')).toBeUndefined()
  })
})
