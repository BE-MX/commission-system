import { apiClient, ArkApiError } from '@/background/apiClient'
import { TranslationCache } from '@/background/cache'
import { finishPairing, refreshSession, startPairing } from '@/background/auth'
import type { Capabilities, PairingState, RuntimeRequest, RuntimeResponse, Session } from '@/shared/contracts'
import { chatKey, ensureTrustedStorageAccess, storage } from '@/shared/storage'

const TARGET_LANGUAGES = new Set(['ar', 'en', 'es', 'fr', 'ja', 'zh-CN'])
const POPUP_REQUEST_TYPES = new Set(['pairing/check', 'pairing/start', 'preferences/get', 'preferences/set', 'session/refresh'])
const translationCache = new TranslationCache<string>()

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

function mapSession(response: NonNullable<Awaited<ReturnType<typeof refreshSession>>>): Session {
  return {
    capabilities: {
      incomingTranslation: true,
      outgoingTranslation: true,
    },
    deviceId: response.device_id,
    expiresAt: response.expires_at,
    minExtensionVersion: '1.0.0',
  }
}

function mapCapabilities(
  response: Awaited<ReturnType<typeof apiClient.getCapabilities>>,
): Capabilities {
  return {
    incomingTranslation: response.directions.includes('incoming'),
    outgoingTranslation: response.directions.includes('outgoing'),
  }
}

async function translateText(
  direction: 'incoming' | 'outgoing',
  text: string,
  sourceLanguage: string,
  targetLanguage: string,
): Promise<string> {
  const cacheKey = await sha256Hex(`${direction}:${sourceLanguage}:${targetLanguage}:${text}`)
  const cached = translationCache.get(cacheKey)
  if (cached) return cached

  const token = await storage.get('deviceToken')
  if (!token) throw new Error('device_token_missing')
  const response = await apiClient.translate(token, chrome.runtime.getManifest().version, {
    direction,
    request_id: crypto.randomUUID(),
    source_language: sourceLanguage,
    target_language: targetLanguage,
    text,
  })
  translationCache.set(cacheKey, response.translated_text)
  return response.translated_text
}

function browserInfo(): { browserName: string; browserVersion: string } {
  const userAgent = navigator.userAgent
  const edgeMatch = userAgent.match(/Edg\/([\d.]+)/)
  const chromeMatch = userAgent.match(/Chrome\/([\d.]+)/)
  return {
    browserName: edgeMatch ? 'Edge' : 'Chrome',
    browserVersion: (edgeMatch ?? chromeMatch)?.[1] ?? '0.0.0.0',
  }
}

async function handleMessage(request: RuntimeRequest): Promise<RuntimeResponse> {
  switch (request.type) {
    case 'pairing/start': {
      const { browserName, browserVersion } = browserInfo()
      const state: PairingState = await startPairing({
        browserName,
        browserVersion,
        deviceName: navigator.platform || 'Desktop',
        extensionVersion: chrome.runtime.getManifest().version,
      })
      return { type: 'pairing/start', state }
    }
    case 'pairing/check': {
      const result = await finishPairing(request.deviceCode)
      const state: PairingState = { authorizeUrl: '', deviceCode: request.deviceCode, status: result.status }
      return { type: 'pairing/check', state }
    }
    case 'session/refresh': {
      const response = await refreshSession(chrome.runtime.getManifest().version)
      if (!response) throw new Error('device_token_missing')
      return { type: 'session/refresh', session: mapSession(response) }
    }
    case 'preferences/get': {
      const [enabled, targetLanguage] = await Promise.all([
        storage.get('enabled'),
        storage.get('defaultTargetLanguage'),
      ])
      return { type: 'preferences/get', enabled: enabled ?? true, targetLanguage: targetLanguage ?? 'zh-CN' }
    }
    case 'preferences/set': {
      if (!TARGET_LANGUAGES.has(request.targetLanguage)) throw new Error('unsupported_language')
      await storage.set({ defaultTargetLanguage: request.targetLanguage, enabled: request.enabled })
      return { type: 'preferences/set' }
    }
    case 'capabilities/get': {
      const token = await storage.get('deviceToken')
      if (!token) throw new Error('device_token_missing')
      const capabilities = await apiClient.getCapabilities(token, chrome.runtime.getManifest().version)
      return { type: 'capabilities/get', capabilities: mapCapabilities(capabilities) }
    }
    case 'chat-language/get': {
      const salt = await storage.get('chatKeySalt')
      if (!salt) throw new Error('device_token_missing')
      const key = await chatKey(request.chatTitle, salt)
      const languages = (await storage.get('chatLanguages')) ?? {}
      return { type: 'chat-language/get', targetLanguage: languages[key] ?? 'zh-CN' }
    }
    case 'chat-language/set': {
      if (!TARGET_LANGUAGES.has(request.targetLanguage)) throw new Error('unsupported_language')
      const salt = await storage.get('chatKeySalt')
      if (!salt) throw new Error('device_token_missing')
      const key = await chatKey(request.chatTitle, salt)
      await storage.set({
        chatLanguages: { ...((await storage.get('chatLanguages')) ?? {}), [key]: request.targetLanguage },
      })
      return { type: 'chat-language/set', targetLanguage: request.targetLanguage }
    }
    case 'translation/incoming': {
      if (!TARGET_LANGUAGES.has(request.targetLanguage)) throw new Error('unsupported_language')
      const translation = await translateText('incoming', request.text, 'auto', request.targetLanguage)
      return { type: 'translation/incoming', translation }
    }
    case 'translation/outgoing': {
      if (!TARGET_LANGUAGES.has(request.targetLanguage)) throw new Error('unsupported_language')
      const translation = await translateText('outgoing', request.text, request.sourceLanguage, request.targetLanguage)
      return { type: 'translation/outgoing', translation }
    }
  }
}

function errorResponse(error: unknown): RuntimeResponse {
  if (error instanceof ArkApiError) return { type: 'error', message: error.code }
  if (error instanceof Error && ['device_token_missing', 'unsupported_language'].includes(error.message)) {
    return { type: 'error', message: error.message }
  }
  return { type: 'error', message: 'unexpected_error' }
}

void ensureTrustedStorageAccess()

chrome.runtime.onMessage.addListener((request: unknown, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || typeof request !== 'object' || request === null) {
    sendResponse({ type: 'error', message: 'unsupported_request' })
    return false
  }

  const typedRequest = request as RuntimeRequest
  if (POPUP_REQUEST_TYPES.has(typedRequest.type) && !sender.url?.endsWith('/src/popup/index.html')) {
    sendResponse({ type: 'error', message: 'unsupported_request' })
    return false
  }

  handleMessage(typedRequest).then(sendResponse).catch((error: unknown) => sendResponse(errorResponse(error)))
  return true
})

