import type { ApiEnvelope, CapabilitiesResponse, PairingStatusResponse, SessionResponse, StartPairingRequest, StartPairingResponse, TranslationRequest, TranslationResponse } from '@/shared/contracts'

const BASE_URL = 'https://leshine.work/api/whatsapp-translation'
const REQUEST_TIMEOUT_MS = 20_000

export class ArkApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status?: number,
  ) {
    super(message)
    this.name = 'ArkApiError'
  }
}

async function requestOnce<TData>(path: string, init: RequestInit = {}, timeoutMs = REQUEST_TIMEOUT_MS): Promise<TData> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
    })
    let payload: Partial<ApiEnvelope<TData> & { data?: { error_code?: string } }>
    try {
      payload = (await response.json()) as Partial<ApiEnvelope<TData> & { data?: { error_code?: string } }>
    } catch {
      const gatewayFailure = [502, 503, 504].includes(response.status)
      throw new ArkApiError(gatewayFailure ? 'backend_unavailable' : 'request_failed', 'request failed', response.status)
    }
    if (!response.ok || payload.code !== 200 || payload.data === undefined) {
      const reportedCode = payload.data && 'error_code' in payload.data && payload.data.error_code
        ? payload.data.error_code
        : 'request_failed'
      const errorCode = [502, 503, 504].includes(response.status) && reportedCode === 'request_failed'
        ? 'backend_unavailable'
        : reportedCode
      throw new ArkApiError(errorCode, 'request failed', response.status)
    }
    return payload.data
  } catch (error) {
    if (error instanceof ArkApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ArkApiError('request_timeout', 'request_timeout')
    }
    throw new ArkApiError('network_error', 'request failed')
  } finally {
    clearTimeout(timer)
  }
}

function isTransientTransportError(error: unknown): boolean {
  return error instanceof ArkApiError
    && (error.code === 'network_error' || error.code === 'backend_unavailable' || error.code === 'ai_unavailable')
}

async function request<TData>(path: string, init: RequestInit = {}, retryTransport = false): Promise<TData> {
  const startedAt = Date.now()
  try {
    return await requestOnce<TData>(path, init)
  } catch (error) {
    if (!retryTransport || !isTransientTransportError(error)) throw error
    const remainingMs = REQUEST_TIMEOUT_MS - (Date.now() - startedAt)
    if (remainingMs <= 0) throw error
    return await requestOnce<TData>(path, init, remainingMs)
  }
}

function headers(token?: string, extensionVersion?: string): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(extensionVersion ? { 'X-Ark-Extension-Version': extensionVersion } : {}),
  }
}

export function createPairing(payload: StartPairingRequest): Promise<StartPairingResponse> {
  return request('/pairings', { body: JSON.stringify(payload), headers: headers(), method: 'POST' })
}

export function exchangePairing(deviceCode: string): Promise<PairingStatusResponse> {
  return request('/pairings/exchange', {
    body: JSON.stringify({ device_code: deviceCode }),
    headers: headers(),
    method: 'POST',
  })
}

export function getSession(token: string, extensionVersion: string): Promise<SessionResponse> {
  return request('/session', { headers: headers(token, extensionVersion) })
}

export function getCapabilities(token: string, extensionVersion: string): Promise<CapabilitiesResponse> {
  return request('/capabilities', { headers: headers(token, extensionVersion) })
}

export function translate(
  token: string,
  extensionVersion: string,
  payload: TranslationRequest,
): Promise<TranslationResponse> {
  return request('/translate', {
    body: JSON.stringify(payload),
    headers: headers(token, extensionVersion),
    method: 'POST',
  }, true)
}

export const apiClient = {
  createPairing,
  exchangePairing,
  getCapabilities,
  getSession,
  translate,
}
