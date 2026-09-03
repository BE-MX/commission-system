import {
  ArkApiError,
  createPairing,
  exchangePairing,
  getSession,
} from '@/background/apiClient'
import type { PairingState, PairingStatusResponse, SessionResponse, StartPairingRequest } from '@/shared/contracts'
import { clearDeviceTokens, storage } from '@/shared/storage'

export type PairingResult = {
  device_id?: number
  expires_at?: string
  status: PairingState['status']
}

export type StartPairingInput = {
  browserName: string
  browserVersion: string
  deviceName: string
  extensionVersion: string
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let output = ''
  for (const byte of bytes) output += String.fromCharCode(byte)
  return btoa(output).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

function bytesToHex(bytes: Uint8Array): string {
  return [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return bytesToHex(new Uint8Array(digest))
}

function isApprovedAuthorizeUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.origin === 'https://leshine.work' && url.pathname === '/whatsapp-translation/authorize'
  } catch {
    return false
  }
}

function assertApprovedAuthorizeUrl(value: string): string {
  if (!isApprovedAuthorizeUrl(value)) throw new Error('invalid_authorize_url')
  return value
}

function isRevokedErrorCode(code: string): boolean {
  return ['device_revoked', 'device_expired', 'invalid_bearer'].includes(code)
}

export async function startPairing(input: StartPairingInput): Promise<PairingState> {
  const tokenBytes = new Uint8Array(32)
  crypto.getRandomValues(tokenBytes)
  const token = bytesToBase64Url(tokenBytes)
  const tokenHash = await sha256Hex(token)
  const saltBytes = new Uint8Array(16)
  crypto.getRandomValues(saltBytes)

  const request: StartPairingRequest = {
    browser_name: input.browserName,
    browser_version: input.browserVersion,
    device_name: input.deviceName,
    extension_version: input.extensionVersion,
    proposed_token_hash: tokenHash,
  }
  const response = await createPairing(request)
  const authorizeUrl = assertApprovedAuthorizeUrl(response.authorize_url)

  await clearDeviceTokens()
  await storage.set({
    chatKeySalt: bytesToHex(saltBytes),
    pendingDeviceCode: response.device_code,
    pendingDeviceToken: token,
  })
  void chrome.tabs?.create({ url: authorizeUrl })

  return {
    authorizeUrl,
    deviceCode: response.device_code,
    status: 'pending',
  }
}

async function promotePendingToken(token: string): Promise<void> {
  await storage.set({ deviceToken: token })
  await storage.remove(['pendingDeviceCode', 'pendingDeviceToken'])
}

export async function finishPairing(
  deviceCode: string,
  options: { attempts?: number; intervalMs?: number; wait?: (ms: number) => Promise<void> } = {},
): Promise<PairingResult> {
  const activeToken = await storage.get('deviceToken')
  if (activeToken) return { status: 'ready' }

  const pendingToken = await storage.get('pendingDeviceToken')
  if (!pendingToken || await storage.get('pendingDeviceCode') !== deviceCode) {
    throw new Error('pending_pairing_not_found')
  }

  const attempts = options.attempts ?? 30
  const intervalMs = options.intervalMs ?? 2_000
  const wait = options.wait ?? (ms => new Promise(resolve => setTimeout(resolve, ms)))

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const response: PairingStatusResponse = await exchangePairing(deviceCode)
    if (response.status === 'ready') {
      await promotePendingToken(pendingToken)
      return { device_id: response.device_id, expires_at: response.expires_at, status: 'ready' }
    }
    if (attempt + 1 < attempts) await wait(intervalMs)
  }
  return { status: 'pending' }
}

export async function refreshSession(extensionVersion: string): Promise<SessionResponse | null> {
  const token = await storage.get('deviceToken')
  if (!token) return null
  try {
    return await getSession(token, extensionVersion)
  } catch (error) {
    if (error instanceof ArkApiError && isRevokedErrorCode(error.code)) {
      await storage.remove(['deviceToken'])
      return null
    }
    throw error
  }
}
