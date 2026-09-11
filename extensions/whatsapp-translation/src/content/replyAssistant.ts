import type { ReplyContext, ReplyContextLimits } from '@/whatsapp/replyContext'
import { maskContacts } from '@/whatsapp/replyContext'
import type { ReplyCapabilities, ReplyRequest, ReplyResponse, ReplyStyle, TargetLanguage } from '@/shared/contracts'
import { boundedReplyCapabilities, replyFitsCapabilities, validReplyResponse } from '@/shared/replyValidation'
import { validMemoryResult } from '@/shared/replyMemory'
import type { MemoryCommand, MemoryResult, ReplyInquiry } from '@/shared/replyMemory'

export type ReplyOptions = { limit: 'default' | 20 | 40; includeDraft: boolean; language: 'auto' | TargetLanguage; goal: string }
export type ReplyState = {
  open: boolean; busy: boolean; context?: ReplyContext; capabilities?: ReplyCapabilities; result?: ReplyResponse; error?: string; canRestore: boolean
  inquiry?: ReplyInquiry; inquiries?: ReplyInquiry[]; previewInquiry?: ReplyInquiry
  memoryBusy?: boolean; memoryNotice?: string; memoryError?: string; memoryEnabled?: boolean; paused?: boolean
  handoffResult?: Pick<ReplyResponse, 'action' | 'handoff'>
}
export function createReplyAssistant(adapter: {
  inspectChat: () => { kind: string }
  collectReplyContext: (limit: 20 | 40, limits: ReplyContextLimits) => ReplyContext
  readComposer: () => string
  replaceComposer: (text: string, current: () => boolean) => Promise<boolean>
}, bridge: { capabilities: () => Promise<unknown>; suggest: (request: ReplyRequest) => Promise<ReplyResponse>; memory?: (command: MemoryCommand) => Promise<MemoryResult> }, fallback: () => TargetLanguage, changed: (state: ReplyState) => void) {
  let epoch = crypto.randomUUID()
  let contextVersion = 0
  let draftVersion = 0
  let operation = 0
  let state: ReplyState = { open: false, busy: false, canRestore: false }
  let draft = ''
  let request: ReplyRequest | undefined
  let restore: { original: string; text: string; version: number } | undefined
  let createId = crypto.randomUUID()
  const paint = () => changed({ ...state, canRestore: !!restore && restore.version === draftVersion && adapter.readComposer() === restore.text })
  function invalidate(error = 'reply_stale') {
    operation += 1
    request = undefined
    state = { ...state, busy: false, result: undefined, error: state.open ? error : undefined }
    paint()
  }
  async function memory(command: MemoryCommand) {
    if (!bridge.memory || adapter.inspectChat().kind !== 'direct') throw new Error('reply_memory_disabled')
    const result = await bridge.memory(command)
    if (!validMemoryResult(result, command)) throw new Error('reply_invalid_response')
    return result
  }
  async function manageMemory(command: MemoryCommand, apply: (result: MemoryResult) => void) {
    if (state.busy || state.memoryBusy) return
    invalidate()
    const current = operation
    const savedEpoch = epoch
    const originalInquiry = state.inquiry?.id
    state.memoryBusy = true; state.memoryError = undefined; paint()
    try {
      const result = await memory(command)
      const isWrite = ['create', 'correct', 'delete'].includes(command.operation)
      if (current === operation || (isWrite && savedEpoch === epoch && state.inquiry?.id === originalInquiry)) apply(result)
    } catch (error) {
      if (savedEpoch === epoch) state.memoryError = error instanceof Error ? error.message : 'reply_failed'
    } finally {
      if (savedEpoch === epoch) { state.memoryBusy = false; paint() }
    }
  }
  async function saveCandidate(candidate: ReplyResponse, current: number) {
    if (!candidate.memory_conversation_id || current !== operation || state.result !== candidate) return
    const savedEpoch = epoch
    state.memoryBusy = true; state.memoryError = undefined; paint()
    try {
      const result = await memory({ operation: 'commit', conversation_id: candidate.memory_conversation_id,
        revision: candidate.memory_revision, request_id: candidate.request_id })
      // A commit already dispatched saves the valid observed snapshot. New text
      // invalidates the reply but need not undo those observations or its revision.
      if (savedEpoch === epoch && state.inquiry?.id === candidate.memory_conversation_id) {
        state.inquiry = result.inquiry; state.memoryNotice = '已保存本次聊天复盘；草稿未记为已发送。'
      }
    } catch (error) {
      if (savedEpoch === epoch) state.memoryError = error instanceof Error ? error.message : 'reply_failed'
    } finally {
      if (savedEpoch === epoch) { state.memoryBusy = false; paint() }
    }
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
      createId = crypto.randomUUID()
      state = { open: false, busy: false, canRestore: false }; invalidate()
    },
    listInquiries() { return manageMemory({ operation: 'list' }, result => { state.inquiries = result.inquiries; state.previewInquiry = undefined }) },
    previewInquiry(id: string) { return manageMemory({ operation: 'read', conversation_id: id }, result => { state.previewInquiry = result.inquiry }) },
    usePreview() {
      if (!state.previewInquiry || state.busy || state.memoryBusy) return
      invalidate(); state.inquiry = state.previewInquiry; state.previewInquiry = undefined; state.inquiries = undefined
      state.memoryEnabled = true; state.memoryNotice = '已使用所选询盘记录，请核对是否属于当前客户。'; paint()
    },
    newInquiry(label = '') {
      if (state.busy || state.memoryBusy) return
      createId = crypto.randomUUID()
      return manageMemory({ operation: 'create', conversation_id: createId, label: maskContacts(label) }, result => {
        state.inquiry = result.inquiry; state.previewInquiry = undefined; state.inquiries = undefined
        state.memoryEnabled = true; state.memoryNotice = '已新建独立询盘记录。'
      })
    },
    setMemoryEnabled(enabled: boolean) {
      if (state.busy || state.memoryBusy) return
      invalidate(); state.memoryEnabled = enabled; state.inquiry = undefined; state.previewInquiry = undefined
      state.inquiries = undefined; createId = crypto.randomUUID(); state.memoryNotice = enabled ? '下次生成将创建新记录，可先选择已有记录。' : '仅使用本次片段，不保存复盘。'; paint()
    },
    refreshMemory() {
      if (!state.inquiry) return
      return manageMemory({ operation: 'read', conversation_id: state.inquiry.id }, result => { state.inquiry = result.inquiry; state.memoryError = undefined })
    },
    deleteMemory() {
      if (!state.inquiry) return
      return manageMemory({ operation: 'delete', conversation_id: state.inquiry.id, revision: state.inquiry.revision }, () => {
        state.inquiry = undefined; state.previewInquiry = undefined; state.inquiries = undefined
        state.memoryEnabled = false; createId = crypto.randomUUID(); state.memoryNotice = '已删除记录，后续生成不会恢复或自动保存它。'
      })
    },
    correctMemory(entryId: string, status: MemoryCommand['status'], note: string) {
      if (!state.inquiry) return
      return manageMemory({ operation: 'correct', conversation_id: state.inquiry.id, revision: state.inquiry.revision,
        entry_id: entryId, status, note: maskContacts(note) }, result => { state.inquiry = result.inquiry; state.memoryNotice = '人工修正已保存。' })
    },
    saveMemory() { if (state.result && !state.memoryBusy) return saveCandidate(state.result, operation) },
    setPaused(paused: boolean) { const result = state.result; invalidate(); state.paused = paused; state.handoffResult = paused ? result : undefined; state.memoryNotice = paused ? '已暂停话术生成，请由业务员接管。' : '已恢复话术辅助。'; paint() },
    async generate(options: ReplyOptions, style: ReplyStyle = 'default') {
      if (state.memoryBusy) return
      if (state.paused) { state.error = 'reply_paused'; paint(); return }
      const current = ++operation
      state = { ...state, open: true, busy: true, context: undefined, result: undefined, error: undefined }
      paint()
      try {
        if (adapter.inspectChat().kind !== 'direct') throw new Error('chat_unsupported')
        const caps = boundedReplyCapabilities(await bridge.capabilities())
        if (current !== operation) return
        state.capabilities = caps
        if (caps.memory_enabled && bridge.memory && state.memoryEnabled !== false && !state.inquiry) {
          const created = await memory({ operation: 'create', conversation_id: createId })
          if (current !== operation) return
          state.inquiry = created.inquiry
        }
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
          ...(state.inquiry ? { memory_conversation_id: state.inquiry.id, memory_revision: state.inquiry.revision } : {}),
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
        await saveCandidate(result, current)
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
