import { beforeEach, describe, expect, it, vi } from 'vitest'

import { chatKey, clearDeviceTokens, ensureTrustedStorageAccess, storage } from '@/shared/storage'

const store = new Map<string, unknown>()
const setAccessLevel = vi.fn()

beforeEach(() => {
  store.clear()
  setAccessLevel.mockClear()
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
        setAccessLevel,
      },
    },
  })
})

describe('trusted local storage', () => {
  it('restricts storage to trusted contexts', async () => {
    await ensureTrustedStorageAccess()
    expect(setAccessLevel).toHaveBeenCalledWith({ accessLevel: 'TRUSTED_CONTEXTS' })
  })

  it('persists typed local state and removes device tokens on revoke', async () => {
    await storage.set({ deviceToken: 'a'.repeat(43), pendingDeviceToken: 'b'.repeat(43) })
    await expect(storage.get('deviceToken')).resolves.toBe('a'.repeat(43))
    await clearDeviceTokens()
    await expect(storage.get('deviceToken')).resolves.toBeUndefined()
    await expect(storage.get('pendingDeviceToken')).resolves.toBeUndefined()
  })

  it('derives stable, non-reversible per-chat keys', async () => {
    const first = await chatKey('conversation title', 'salt')
    const second = await chatKey('conversation title', 'salt')
    const other = await chatKey('conversation title', 'different-salt')

    expect(first).toBe(second)
    expect(first).toMatch(/^[0-9a-f]{64}$/)
    expect(first).not.toBe(other)
    expect(first).not.toContain('conversation')
  })
})
