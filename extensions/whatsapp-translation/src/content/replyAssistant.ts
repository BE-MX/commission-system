import type { ReplyContext, ReplyContextLimits } from '@/whatsapp/replyContext'
import { maskContacts } from '@/whatsapp/replyContext'
import type { ReplyCapabilities, ReplyRequest, ReplyResponse, ReplyStyle, TargetLanguage } from '@/shared/contracts'
import { boundedReplyCapabilities, replyFitsCapabilities, validReplyResponse } from '@/shared/replyValidation'

export type ReplyOptions = { limit: 'default' | 20 | 40; includeDraft: boolean; language: 'auto' | TargetLanguage; goal: string }
export type ReplyState = { open: boolean; busy: boolean; context?: ReplyContext; capabilities?: ReplyCapabilities; result?: ReplyResponse; error?: string; canRestore: boolean }
export function createReplyAssistant(adapter: {
  inspectChat: () => { kind: string }
  collectReplyContext: (limit: 20 | 40, limits: ReplyContextLimits) => ReplyContext
  readComposer: () => string
  replaceComposer: (text: string, current: () => boolean) => Promise<boolean>
}, bridge: { capabilities: () => Promise<unknown>; suggest: (request: ReplyRequest) => Promise<ReplyResponse> }, fallback: () => TargetLanguage, changed: (state: ReplyState) => void) {
  let epoch = crypto.randomUUID()
  let contextVersion = 0
  let draftVersion = 0
  let operation = 0
  let state: ReplyState = { open: false, busy: false, canRestore: false }
  let draft = ''
  let request: ReplyRequest | undefined
  let restore: { original: string; text: string; version: number } | undefined
  const paint = () => changed({ ...state, canRestore: !!restore && restore.version === draftVersion && adapter.readComposer() === restore.text })
  function invalidate(error = 'reply_stale') {
    operation += 1
    request = undefined
    state = { ...state, busy: false, result: undefined, error: state.open ? error : undefined }
    paint()
  }
  return {
    getState: () => state,
    getRevision: () => operation,
    async open() {
      const current = operation
      state.open = true
      paint()
      try {
        const caps = boundedReplyCapabilities(await bridge.capabilities())
        if (current !== operation || !state.open) return
        state.capabilities = caps
        state.context = adapter.collectReplyContext(caps.default_messages > 20 ? 40 : 20, { maxMessages: caps.default_messages, maxChars: caps.max_context_chars })
      } catch (error) {
        if (current !== operation) return
        state.context = undefined
        state.error = error instanceof Error ? error.message : 'reply_failed'
      }
      if (current === operation) paint()
    },
    close() { state.open = false; invalidate(); state.context = undefined },
    cancel() { invalidate('reply_cancelled') },
    optionsChanged() { invalidate() },
    draftChanged() { draftVersion += 1; restore = undefined; invalidate() },
    contextChanged() { contextVersion += 1; invalidate() },
    chatChanged() {
      epoch = crypto.randomUUID(); contextVersion = 0; draftVersion = 0; restore = undefined
      state = { open: false, busy: false, canRestore: false }; invalidate()
    },
    async generate(options: ReplyOptions, style: ReplyStyle = 'default') {
      const current = ++operation
      state = { ...state, open: true, busy: true, context: undefined, result: undefined, error: undefined }
      paint()
      try {
        if (adapter.inspectChat().kind !== 'direct') throw new Error('chat_unsupported')
        const caps = boundedReplyCapabilities(await bridge.capabilities())
        if (current !== operation) return
        state.capabilities = caps
        const count = options.limit === 'default' ? caps.default_messages : options.limit
        const requested = options.limit === 'default' ? (count > 20 ? 40 : 20) : options.limit
        const context = adapter.collectReplyContext(requested, { maxMessages: Math.min(count, caps.max_messages), maxChars: caps.max_context_chars })
        state.context = context
        if (!context.messages.length) throw new Error('reply_empty_context')
        draft = adapter.readComposer()
        const draftIntent = options.includeDraft ? maskContacts(draft) : ''
        const goal = maskContacts(options.goal)
        if (options.includeDraft && Math.max(draft.length, draftIntent.length) > caps.max_draft_chars) throw new Error('reply_draft_too_long')
        if (Math.max(options.goal.length, goal.length) > caps.max_goal_chars) throw new Error('reply_goal_too_long')
        const frozen: ReplyRequest = {
          request_id: crypto.randomUUID(), conversation_epoch: epoch, context_version: contextVersion, draft_version: draftVersion,
          messages: context.messages, context_scope: context.context_scope,
          draft_intent: draftIntent, target_language: options.language,
          fallback_language: fallback(), goal, style,
        }
        request = frozen
        if (!replyFitsCapabilities(frozen, caps)) throw new Error('reply_context_too_large')
        paint()
        const result = await bridge.suggest(frozen)
        if (current !== operation) return
        if (adapter.inspectChat().kind !== 'direct') { this.chatChanged(); return }
        if (adapter.readComposer() !== draft) { this.draftChanged(); return }
        if (!validReplyResponse(result, frozen)) throw new Error('reply_invalid_response')
        state.result = result
      } catch (error) {
        if (current !== operation) return
        state.error = error instanceof Error ? error.message : 'reply_failed'
      } finally {
        if (current === operation) { state.busy = false; paint() }
      }
    },
    async fill() {
      const candidate = state.result
      const frozen = request
      const current = operation
      if (!candidate || candidate.status !== 'ready' || !frozen || adapter.readComposer() !== draft) return false
      const isCurrent = () => operation === current && state.result === candidate && request === frozen
      const original = draft
      const success = await adapter.replaceComposer(candidate.reply_text, isCurrent)
      if (success && isCurrent()) {
        restore = { original, text: adapter.readComposer(), version: draftVersion }
        invalidate('reply_filled')
      } else if (isCurrent()) { state.error = 'composer_write_failed'; paint() }
      return success
    },
    async restore() {
      const point = restore
      const current = operation
      if (!point || point.version !== draftVersion || adapter.readComposer() !== point.text) return false
      const isCurrent = () => operation === current && restore === point && point.version === draftVersion
      const success = await adapter.replaceComposer(point.original, isCurrent)
      if (!isCurrent()) return false
      if (success) { restore = undefined; invalidate('reply_restored') }
      else { state.error = 'composer_write_failed'; paint() }
      return success
    },
  }
}
