const STORAGE_ACCESS = 'TRUSTED_CONTEXTS'

export type LocalState = {
  chatKeySalt: string
  chatLanguages: Record<string, string>
  defaultTargetLanguage: string
  deviceToken?: string
  enabled: boolean
  pendingDeviceCode?: string
  pendingDeviceToken?: string
}

export const storage = {
  get: async <TKey extends keyof LocalState>(key: TKey): Promise<LocalState[TKey] | undefined> => {
    const values = await chrome.storage.local.get(key)
    return values[key] as LocalState[TKey] | undefined
  },
  remove: async (keys: Array<keyof LocalState>): Promise<void> => {
    await chrome.storage.local.remove(keys)
  },
  set: async (values: Partial<LocalState>): Promise<void> => {
    await chrome.storage.local.set(values)
  },
}

export async function ensureTrustedStorageAccess(): Promise<void> {
  await chrome.storage.local.setAccessLevel({ accessLevel: STORAGE_ACCESS })
}

export async function clearDeviceTokens(): Promise<void> {
  await storage.remove(['deviceToken', 'pendingDeviceCode', 'pendingDeviceToken'])
}

export async function chatKey(normalizedTitle: string, salt: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${salt}:${normalizedTitle}`))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}
