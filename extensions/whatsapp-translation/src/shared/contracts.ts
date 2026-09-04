export type ApiEnvelope<TData> = {
  code: number
  data: TData
  message: string
}

export type ApiError = {
  code: number
  data?: { error_code?: string }
  message: string
}

export type StartPairingRequest = {
  browser_name: string
  browser_version: string
  device_name: string
  extension_version: string
  proposed_token_hash: string
}

export type StartPairingResponse = {
  authorize_url: string
  device_code: string
  expires_at: string
}

export type PairingStatusResponse = {
  device_id?: number
  expires_at?: string
  status: 'pending' | 'ready'
}

export type SessionResponse = {
  device_id: number
  expires_at: string
  is_admin: boolean
  real_name: string
  user_id: number
}

export type CapabilitiesResponse = {
  ai_config_version: number
  daily_input_chars: number
  directions: string[]
  max_text_chars: number
  min_extension_version: string
  rate_per_minute: number
  source_languages: string[]
  target_languages: string[]
}

export type TranslationRequest = {
  direction: 'incoming' | 'outgoing'
  request_id: string
  source_language: string
  target_language: string
  text: string
}

export type TranslationResponse = {
  back_translation?: string | null
  detected_source_language: string
  model_log_id: number
  request_id: string
  translated_text: string
}

export type PairingState = {
  deviceCode: string
  authorizeUrl: string
  status: 'pending' | 'ready'
}

export type Capabilities = {
  incomingTranslation: boolean
  outgoingTranslation: boolean
}

export type Session = {
  capabilities: Capabilities
  deviceId: number
  expiresAt: string
  minExtensionVersion: string
  realName: string
}

export type TranslationResult = {
  backTranslation?: string
  sourceLanguage: string
  translation: string
}

export const TARGET_LANGUAGES = ['zh-CN', 'en', 'es', 'fr', 'ar', 'ja'] as const
export type TargetLanguage = (typeof TARGET_LANGUAGES)[number]
export const DEFAULT_OUTGOING_LANGUAGE: TargetLanguage = 'en'

export const LANGUAGE_LABELS: Record<string, string> = {
  ar: 'العربية',
  de: 'Deutsch',
  en: 'English',
  es: 'Español',
  fr: 'Français',
  ja: '日本語',
  nl: 'Nederlands',
  sv: 'Svenska',
  'zh-CN': '中文',
}

export function languageLabel(code: string): string {
  return LANGUAGE_LABELS[code] ?? code
}

export type RuntimeRequest =
  | { type: 'pairing/start' }
  | { type: 'pairing/resume' }
  | { type: 'session/refresh' }
  | { type: 'preferences/get' }
  | { type: 'preferences/set'; enabled: boolean; targetLanguage: string }
  | { type: 'capabilities/get' }
  | { type: 'chat-language/get'; chatTitle: string }
  | { type: 'chat-language/set'; chatTitle: string; targetLanguage: string }
  | { type: 'translation/incoming'; request_id: string; source_language: 'auto'; target_language: string; text: string }
  | { type: 'translation/outgoing'; request_id: string; sourceLanguage: string; targetLanguage: string; text: string }

export type RuntimeResponse =
  | { type: 'pairing/start'; state: PairingState }
  | { type: 'pairing/resume'; state: PairingState | null }
  | { type: 'session/refresh'; session: Session }
  | { type: 'preferences/get'; enabled: boolean; targetLanguage: string }
  | { type: 'preferences/set' }
  | { type: 'capabilities/get'; capabilities: Capabilities }
  | { type: 'chat-language/get'; targetLanguage: string }
  | { type: 'chat-language/set'; targetLanguage: string }
  | { type: 'translation/incoming'; translation: string; sourceLanguage: string }
  | { type: 'translation/outgoing'; translation: string; sourceLanguage: string; backTranslation?: string }
  | { type: 'error'; message: string }

export function mapStartPairing(response: StartPairingResponse): PairingState {
  return {
    deviceCode: response.device_code,
    authorizeUrl: response.authorize_url,
    status: 'pending',
  }
}
