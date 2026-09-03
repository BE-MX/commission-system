import type { ParsedMessage } from '@/whatsapp/messageParser'

export type IncomingRenderState = {
  kind: 'loading' | 'success' | 'retryable_error' | 'blocked'
  retryAfterMs?: number
  translation?: string
}

export type IncomingRenderer = {
  mountTranslation: (
    target: Element,
    state: IncomingRenderState,
    onRetry?: () => void,
  ) => void
}

export type IncomingBridgeRequest = {
  direction: 'incoming'
  request_id: string
  source_language: 'auto'
  target_language: string
  text: string
}

export type IncomingBridge = {
  translate: (request: IncomingBridgeRequest) => Promise<{ translation: string }>
}

export class IncomingBridgeError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly retryAfterMs?: number,
  ) {
    super(message)
    this.name = 'IncomingBridgeError'
  }
}

const DEBOUNCE_MS = 300
const DEFAULT_RATE_LIMIT_MS = 60_000
const REQUEST_TIMEOUT_MS = 20_000
const REVOKED_CODES = new Set(['device_expired', 'device_revoked', 'invalid_bearer'])

function withTimeout<TValue>(promise: Promise<TValue>): Promise<TValue> {
  let timer: ReturnType<typeof setTimeout> | undefined
  return Promise.race([
    promise,
    new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new IncomingBridgeError('request_timeout', 'request_timeout')), REQUEST_TIMEOUT_MS)
    }),
  ]).finally(() => clearTimeout(timer))
}

export function createIncomingTranslator(
  adapter: {
    inspectChat: () => { kind: string }
    listUntranslatedIncomingMessages: () => Promise<ParsedMessage[]>
  },
  bridge: IncomingBridge,
  renderer: IncomingRenderer,
) {
  let chatGeneration = 0
  let mutationTimer: ReturnType<typeof setTimeout> | undefined
  let pausedUntil = 0
  let stopped = false

  function clearTimer(): void {
    if (mutationTimer) clearTimeout(mutationTimer)
  }

  function schedule(delayMs: number): void {
    clearTimer()
    mutationTimer = setTimeout(() => {
      void runBatch(chatGeneration)
    }, delayMs)
  }

  async function runBatch(batchGeneration: number): Promise<void> {
    if (stopped || batchGeneration !== chatGeneration) return
    if (adapter.inspectChat().kind !== 'direct') return

    const messages = await adapter.listUntranslatedIncomingMessages()
    for (const message of messages) {
      if (stopped || batchGeneration !== chatGeneration) return

      renderer.mountTranslation(message.element, { kind: 'loading' })
      try {
        const response = await withTimeout(bridge.translate({
          direction: 'incoming',
          request_id: crypto.randomUUID(),
          source_language: 'auto',
          target_language: 'zh-CN',
          text: message.text,
        }))
        if (stopped || batchGeneration !== chatGeneration) return
        renderer.mountTranslation(message.element, {
          kind: 'success',
          translation: response.translation,
        }, retry)
      } catch (error) {
        if (stopped || batchGeneration !== chatGeneration) return
        const code = error instanceof IncomingBridgeError ? error.code : 'unexpected_error'

        if (code === 'request_timeout') {
          renderer.mountTranslation(message.element, { kind: 'blocked' }, undefined)
          continue
        }
        if (REVOKED_CODES.has(code)) {
          stopped = true
          renderer.mountTranslation(message.element, { kind: 'blocked' }, undefined)
          return
        }
        if (code === 'rate_limited') {
          const retryAfterMs = error instanceof IncomingBridgeError && error.retryAfterMs
            ? error.retryAfterMs
            : DEFAULT_RATE_LIMIT_MS
          pausedUntil = Date.now() + retryAfterMs
          renderer.mountTranslation(message.element, {
            kind: 'retryable_error',
            retryAfterMs,
          }, retry)
          continue
        }

        renderer.mountTranslation(message.element, { kind: 'retryable_error' }, retry)
      }
    }
  }

  function retry(): void {
    if (stopped) return
    const now = Date.now()
    schedule(Math.max(DEBOUNCE_MS, pausedUntil - now))
  }

  return {
    chatChanged(): void {
      chatGeneration += 1
      clearTimer()
    },
    notifyMutation(): void {
      if (stopped) return
      const now = Date.now()
      schedule(pausedUntil > now ? pausedUntil - now : DEBOUNCE_MS)
    },
  }
}
