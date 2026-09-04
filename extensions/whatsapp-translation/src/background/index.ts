import { apiClient, ArkApiError } from '@/background/apiClient'
import { TranslationCache } from '@/background/cache'
import { refreshSession, resumePairing, startPairing } from '@/background/auth'
import type { Capabilities, PairingState, RuntimeRequest, RuntimeResponse, Session, TranslationResult } from '@/shared/contracts'
import { DEFAULT_OUTGOING_LANGUAGE, TARGET_LANGUAGES } from '@/shared/contracts'
import { chatKey, ensureTrustedStorageAccess, storage } from '@/shared/storage'

const POPUP_REQUEST_TYPES = new Set(['pairing/resume', 'pairing/start', 'preferences/set', 'session/refresh'])
const translationCache = new TranslationCache<TranslationResult>()

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
    realName: response.real_name,
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
  requestId?: string,
): Promise<TranslationResult> {
  const cacheKey = await sha256Hex(`${direction}:${sourceLanguage}:${targetLanguage}:${text}`)
  const cached = translationCache.get(cacheKey)
  if (cached) return cached

  const token = await storage.get('deviceToken')
  if (!token) throw new Error('device_token_missing')
  const response = await apiClient.translate(token, chrome.runtime.getManifest().version, {
    direction,
    request_id: requestId ?? crypto.randomUUID(),
    source_language: sourceLanguage,
    target_language: targetLanguage,
    text,
  })
  const result: TranslationResult = {
    backTranslation: response.back_translation ?? undefined,
    sourceLanguage: response.detected_source_language,
    translation: response.translated_text,
  }
  translationCache.set(cacheKey, result)
  return result
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
    case 'pairing/resume': {
      const state = await resumePairing({ attempts: 1 })
      return { type: 'pairing/resume', state }
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
      return { type: 'preferences/get', enabled: enabled ?? true, targetLanguage: targetLanguage ?? DEFAULT_OUTGOING_LANGUAGE }
    }
    case 'preferences/set': {
      if (!(TARGET_LANGUAGES as readonly string[]).includes(request.targetLanguage)) throw new Error('unsupported_language')
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
      const fallback = (await storage.get('defaultTargetLanguage')) ?? DEFAULT_OUTGOING_LANGUAGE
      return { type: 'chat-language/get', targetLanguage: languages[key] ?? fallback }
    }
    case 'chat-language/set': {
      if (!(TARGET_LANGUAGES as readonly string[]).includes(request.targetLanguage)) throw new Error('unsupported_language')
      const salt = await storage.get('chatKeySalt')
      if (!salt) throw new Error('device_token_missing')
      const key = await chatKey(request.chatTitle, salt)
      await storage.set({
        chatLanguages: { ...((await storage.get('chatLanguages')) ?? {}), [key]: request.targetLanguage },
      })
      return { type: 'chat-language/set', targetLanguage: request.targetLanguage }
    }
    case 'translation/incoming': {
      if (!(TARGET_LANGUAGES as readonly string[]).includes(request.target_language)) throw new Error('unsupported_language')
      const enabled = await storage.get('enabled')
      if (enabled === false) throw new Error('translation_disabled')
      const result = await translateText('incoming', request.text, 'auto', request.target_language, request.request_id)
      return { type: 'translation/incoming', sourceLanguage: result.sourceLanguage, translation: result.translation }
    }
    case 'translation/outgoing': {
      if (!(TARGET_LANGUAGES as readonly string[]).includes(request.targetLanguage)) throw new Error('unsupported_language')
      const result = await translateText('outgoing', request.text, request.sourceLanguage, request.targetLanguage)
      return {
        type: 'translation/outgoing',
        backTranslation: result.backTranslation,
        sourceLanguage: result.sourceLanguage,
        translation: result.translation,
      }
    }
  }
}

function errorResponse(error: unknown): RuntimeResponse {
  if (error instanceof ArkApiError) return { type: 'error', message: error.code }
  if (error instanceof Error && ['device_token_missing', 'unsupported_language', 'translation_disabled'].includes(error.message)) {
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
