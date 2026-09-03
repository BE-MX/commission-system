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
}

export type RuntimeRequest =
  | { type: 'pairing/start' }
  | { type: 'pairing/check'; deviceCode: string }
  | { type: 'session/refresh' }
  | { type: 'preferences/get' }
  | { type: 'preferences/set'; enabled: boolean; targetLanguage: string }
  | { type: 'capabilities/get' }
  | { type: 'chat-language/get'; chatTitle: string }
  | { type: 'chat-language/set'; chatTitle: string; targetLanguage: string }
  | { type: 'translation/incoming'; request_id: string; source_language: 'auto'; target_language: string; text: string }
  | { type: 'translation/outgoing'; sourceLanguage: string; targetLanguage: string; text: string }

export type RuntimeResponse =
  | { type: 'pairing/start'; state: PairingState }
  | { type: 'pairing/check'; state: PairingState }
  | { type: 'session/refresh'; session: Session }
  | { type: 'preferences/get'; enabled: boolean; targetLanguage: string }
  | { type: 'preferences/set' }
  | { type: 'capabilities/get'; capabilities: Capabilities }
  | { type: 'chat-language/get'; targetLanguage: string }
  | { type: 'chat-language/set'; targetLanguage: string }
  | { type: 'translation/incoming'; translation: string }
  | { type: 'translation/outgoing'; translation: string }
  | { type: 'error'; message: string }

export function mapStartPairing(response: StartPairingResponse): PairingState {
  return {
    deviceCode: response.device_code,
    authorizeUrl: response.authorize_url,
    status: 'pending',
  }
}
