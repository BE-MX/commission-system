export type ApiEnvelope<TData> = {
  code?: string
  data: TData
  message?: string
  request_id?: string
  success: true
}

export type ApiError = {
  code: string
  message: string
  request_id?: string
  success: false
}

export type StartPairingResponse = {
  authorize_url: string
  device_code: string
  expires_in: number
  interval: number
}

export type PairingStatusResponse = {
  status: 'approved' | 'expired' | 'pending'
}

export type SessionResponse = {
  capabilities: string[]
  device_id: number
  expires_at: string
  min_extension_version: string
}

export type PairingState = {
  deviceCode: string
  authorizeUrl: string
  status: 'approved' | 'expired' | 'pending'
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
  | { type: 'translation/incoming'; text: string; targetLanguage: string }
  | { type: 'translation/outgoing'; text: string; sourceLanguage: string; targetLanguage: string }

export type RuntimeResponse =
  | { type: 'pairing/start'; state: PairingState }
  | { type: 'pairing/check'; state: PairingState }
  | { type: 'session/refresh'; session: Session }
  | { type: 'translation/incoming'; translation: string }
  | { type: 'translation/outgoing'; translation: string }

export function mapStartPairing(response: StartPairingResponse): PairingState {
  return {
    deviceCode: response.device_code,
    authorizeUrl: response.authorize_url,
    status: 'pending',
  }
}
