import type { ParsedMessage } from '@/whatsapp/messageParser'

export type IncomingRenderState = {
  code?: string
  kind: 'pending' | 'loading' | 'success' | 'retryable_error' | 'blocked'
  retryAfterMs?: number
  sourceLanguage?: string
  translation?: string
}

export type IncomingRenderer = {
  mountTranslation: (
    target: Element,
    state: IncomingRenderState,
    onAction?: () => void,
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
  translate: (request: IncomingBridgeRequest) => Promise<{ translation: string; sourceLanguage?: string }>
}

export type IncomingTranslatorOptions = {
  onDetectedLanguage?: (message: ParsedMessage, language: string) => void
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

type TaskStatus = 'pending' | 'running' | 'success' | 'retryable_error' | 'blocked'

type IncomingTask = {
  generation: number
  message: ParsedMessage
  pendingTimer?: ReturnType<typeof setTimeout>
  requestId: string
  status: TaskStatus
}

const DEBOUNCE_MS = 300
const DEFAULT_RATE_LIMIT_MS = 60_000
const MANUAL_ACTION_DELAY_MS = 1_000
const MAX_CONCURRENCY = 3
const REQUEST_TIMEOUT_MS = 20_000
const REVOKED_CODES = new Set(['device_expired', 'device_revoked', 'invalid_bearer', 'device_not_found', 'permission_denied', 'user_inactive', 'extension_outdated'])
/** The user turned translation off in the popup: stop quietly, no bubble noise. */
const SILENT_CODES = new Set(['translation_disabled', 'device_token_missing'])

function withTimeout<TValue>(promise: Promise<TValue>): Promise<TValue> {
  let timer: ReturnType<typeof setTimeout> | undefined
  return Promise.race([
    promise,
    new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new IncomingBridgeError('request_timeout', 'request_timeout')), REQUEST_TIMEOUT_MS)
    }),
  ]).finally(() => clearTimeout(timer))
}

export function isLanguageSignal(text: string): boolean {
  return (text.match(/\p{L}/gu)?.length ?? 0) >= 3
}

export function createIncomingTranslator(
  adapter: {
    inspectChat: () => { kind: string }
    listUntranslatedIncomingMessages: () => Promise<ParsedMessage[]>
  },
  bridge: IncomingBridge,
  renderer: IncomingRenderer,
  options: IncomingTranslatorOptions = {},
) {
  let chatGeneration = 0
  let newestLanguageKey: string | undefined
  let pausedUntil = 0
  let pauseTimer: ReturnType<typeof setTimeout> | undefined
  let runningCount = 0
  let scanDirty = false
  let scanInProgress = false
  let scanTimer: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  const queue: string[] = []
  const tasks = new Map<string, IncomingTask>()

  function active(task: IncomingTask): boolean {
    return !stopped && task.generation === chatGeneration
  }

  function clearPendingTimer(task: IncomingTask): void {
    if (task.pendingTimer) clearTimeout(task.pendingTimer)
    task.pendingTimer = undefined
  }

  function removeMount(element: Element): void {
    element.querySelector(':scope > [data-ark-translation-host="1"]')?.remove()
  }

  function removeQueuedKey(key: string): void {
    const index = queue.indexOf(key)
    if (index >= 0) queue.splice(index, 1)
  }

  function renderPendingAction(task: IncomingTask): void {
    clearPendingTimer(task)
    task.pendingTimer = setTimeout(() => {
      task.pendingTimer = undefined
      if (!active(task) || task.status !== 'pending') return
      renderer.mountTranslation(task.message.element, { kind: 'pending' }, () => promote(task.message.localKey))
    }, MANUAL_ACTION_DELAY_MS)
  }

  function schedulePause(): void {
    if (pauseTimer) clearTimeout(pauseTimer)
    const delay = Math.max(0, pausedUntil - Date.now())
    pauseTimer = setTimeout(() => {
      pauseTimer = undefined
      pausedUntil = 0
      pump()
    }, delay)
  }

  function markRetryable(task: IncomingTask, code: string, retryAfterMs?: number): void {
    task.status = 'retryable_error'
    renderer.mountTranslation(task.message.element, {
      code,
      kind: 'retryable_error',
      ...(retryAfterMs ? { retryAfterMs } : {}),
    }, retryAfterMs ? undefined : () => retry(task.message.localKey))
  }

  function handleError(task: IncomingTask, error: unknown): void {
    if (!active(task)) return
    const code = error instanceof IncomingBridgeError ? error.code : 'unexpected_error'

    if (SILENT_CODES.has(code)) {
      stopped = true
      tasks.delete(task.message.localKey)
      removeMount(task.message.element)
      return
    }
    if (REVOKED_CODES.has(code) || code === 'daily_quota_exceeded') {
      stopped = true
      task.status = 'blocked'
      renderer.mountTranslation(task.message.element, { code, kind: 'blocked' }, undefined)
      return
    }
    if (code === 'rate_limited') {
      const retryAfterMs = error instanceof IncomingBridgeError && error.retryAfterMs
        ? error.retryAfterMs
        : DEFAULT_RATE_LIMIT_MS
      pausedUntil = Date.now() + retryAfterMs
      task.status = 'pending'
      queue.unshift(task.message.localKey)
      renderer.mountTranslation(task.message.element, {
        code,
        kind: 'retryable_error',
        retryAfterMs,
      }, undefined)
      schedulePause()
      return
    }
    markRetryable(task, code)
  }

  function start(task: IncomingTask): void {
    task.status = 'running'
    clearPendingTimer(task)
    runningCount += 1
    renderer.mountTranslation(task.message.element, { kind: 'loading' })
    const generation = task.generation

    void withTimeout(bridge.translate({
      direction: 'incoming',
      request_id: task.requestId,
      source_language: 'auto',
      target_language: 'zh-CN',
      text: task.message.text,
    })).then((response) => {
      if (!active(task)) return
      task.status = 'success'
      renderer.mountTranslation(task.message.element, {
        kind: 'success',
        sourceLanguage: response.sourceLanguage,
        translation: response.translation,
      }, () => retry(task.message.localKey))
      if (task.message.localKey === newestLanguageKey && response.sourceLanguage) {
        options.onDetectedLanguage?.(task.message, response.sourceLanguage)
      }
    }).catch(error => handleError(task, error)).finally(() => {
      if (generation !== chatGeneration) return
      runningCount = Math.max(0, runningCount - 1)
      pump()
    })
  }

  function pump(): void {
    if (stopped) return
    if (pausedUntil > Date.now()) {
      schedulePause()
      return
    }
    while (runningCount < MAX_CONCURRENCY && queue.length > 0) {
      const key = queue.shift()!
      const task = tasks.get(key)
      if (!task || !active(task) || task.status !== 'pending') continue
      start(task)
    }
  }

  function promote(key: string): void {
    const task = tasks.get(key)
    if (!task || !active(task) || task.status !== 'pending') return
    removeQueuedKey(key)
    queue.unshift(key)
    pump()
  }

  function retry(key: string): void {
    const task = tasks.get(key)
    if (!task || !active(task) || task.status === 'running') return
    task.status = 'pending'
    removeQueuedKey(key)
    queue.unshift(key)
    renderPendingAction(task)
    pump()
  }

  function scheduleScan(delayMs: number): void {
    if (scanTimer || scanInProgress) {
      scanDirty = true
      return
    }
    const generation = chatGeneration
    scanTimer = setTimeout(() => {
      scanTimer = undefined
      void scan(generation)
    }, delayMs)
  }

  async function scan(generation: number): Promise<void> {
    if (stopped || generation !== chatGeneration) return
    if (adapter.inspectChat().kind !== 'direct') return
    scanInProgress = true
    scanDirty = false
    try {
      const messages = await adapter.listUntranslatedIncomingMessages()
      if (stopped || generation !== chatGeneration) return
      for (const message of messages) {
        if (isLanguageSignal(message.text)) newestLanguageKey = message.localKey
        const existing = tasks.get(message.localKey)
        if (existing) {
          existing.message = message
          continue
        }
        const task: IncomingTask = {
          generation,
          message,
          requestId: crypto.randomUUID(),
          status: 'pending',
        }
        tasks.set(message.localKey, task)
        queue.push(message.localKey)
        renderPendingAction(task)
      }
      pump()
    } finally {
      scanInProgress = false
      if (scanDirty && !stopped && generation === chatGeneration) scheduleScan(0)
    }
  }

  return {
    chatChanged(): void {
      chatGeneration += 1
      if (scanTimer) clearTimeout(scanTimer)
      if (pauseTimer) clearTimeout(pauseTimer)
      for (const task of tasks.values()) clearPendingTimer(task)
      newestLanguageKey = undefined
      pausedUntil = 0
      pauseTimer = undefined
      queue.length = 0
      runningCount = 0
      scanDirty = false
      scanInProgress = false
      scanTimer = undefined
      tasks.clear()
    },
    notifyMutation(): void {
      if (stopped) return
      const delay = pausedUntil > Date.now() ? pausedUntil - Date.now() : DEBOUNCE_MS
      scheduleScan(delay)
    },
    /** Re-arm after the popup turns translation back on or the user re-authorizes. */
    resume(): void {
      stopped = false
      pausedUntil = 0
      if (pauseTimer) clearTimeout(pauseTimer)
      pauseTimer = undefined
    },
  }
}
