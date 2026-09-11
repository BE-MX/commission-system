import { expect, it, vi } from 'vitest'
import { createReplyAssistant } from '@/content/replyAssistant'
import type { ReplyOptions } from '@/content/replyAssistant'
import type { ReplyRequest, ReplyResponse } from '@/shared/contracts'

const options: ReplyOptions = { limit: 20, includeDraft: true, language: 'auto', goal: '' }
const capabilities = { available: true, history_enabled: true, max_messages: 40, default_messages: 20, max_context_chars: 12000, max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 30 }
function setup() {
  let text = '原草稿'
  let resolve!: (result: ReplyResponse) => void
  let payload!: ReplyRequest
  const bridge = { capabilities: vi.fn(async () => capabilities), suggest: vi.fn((request: ReplyRequest) => {
    payload = request
    return new Promise<ReplyResponse>(done => { resolve = done })
  }) }
  const adapter = {
    inspectChat: () => ({ kind: 'direct' }), readComposer: () => text,
    collectReplyContext: vi.fn(() => ({ messages: [{ role: 'customer' as const, text: 'Can I have a sample?' }], context_scope: { requested_limit: 20 as const, truncated: false, omitted_media: false, latest_visible: false }, loadedCount: 1, skippedUnknown: false, range: '1–1' })),
    replaceComposer: vi.fn(async (value: string, current: () => boolean) => { if (!current()) return false; text = value; return true }),
  }
  const assistant = createReplyAssistant(adapter, bridge, () => 'en', vi.fn())
  const response = (): ReplyResponse => ({ ...payload, status: 'ready', reply_language: 'en', reply_text: 'What size would you prefer?', meaning_zh: '您想要什么尺寸？', rationale_zh: '先确认需求', sources: [], claims: [], risk_flags: [], missing_information: [] })
  return { assistant, adapter, bridge, response, started: () => vi.waitFor(() => expect(bridge.suggest).toHaveBeenCalled()), getPayload: () => payload, resolve: (overrides: Partial<ReplyResponse> = {}) => resolve({ ...response(), ...overrides }), edit: (value: string) => { text = value; assistant.draftChanged() } }
}
it.each(['draft', 'context', 'chat', 'cancel', 'close', 'options'] as const)('rejects late result after %s changes', async kind => {
  const s = setup(); const pending = s.assistant.generate(options)
  await s.started()
  if (kind === 'draft') { s.edit('changed'); s.edit('原草稿') }
  if (kind === 'context') s.assistant.contextChanged()
  if (kind === 'chat') s.assistant.chatChanged()
  if (kind === 'cancel') s.assistant.cancel()
  if (kind === 'close') s.assistant.close()
  if (kind === 'options') s.assistant.optionsChanged()
  s.resolve(); await pending
  expect(s.assistant.getState().result).toBeUndefined()
  expect(await s.assistant.fill()).toBe(false)
  expect(s.adapter.replaceComposer).not.toHaveBeenCalled()
})
it('only fills reply_text after preview and restores once while untouched', async () => {
  const s = setup(); const pending = s.assistant.generate(options)
  await s.started()
  expect(s.adapter.replaceComposer).not.toHaveBeenCalled()
  s.resolve(); await pending
  expect(await s.assistant.fill()).toBe(true)
  expect(s.adapter.readComposer()).toBe('What size would you prefer?')
  expect(await s.assistant.restore()).toBe(true)
  expect(s.adapter.readComposer()).toBe('原草稿')
  expect(await s.assistant.restore()).toBe(false)
})
it('a reversed user edit permanently invalidates restore', async () => {
  const s = setup(); const pending = s.assistant.generate(options); await s.started(); s.resolve(); await pending; await s.assistant.fill()
  s.edit('temporary'); s.edit('What size would you prefer?')
  expect(await s.assistant.restore()).toBe(false)
})
it('freezes language, versions, draft intent and explicit style per request without automatic requests', async () => {
  const s = setup(); s.assistant.open(); expect(s.bridge.suggest).not.toHaveBeenCalled()
  const pending = s.assistant.generate({ ...options, includeDraft: false, language: 'fr', goal: 'Ask size' }, 'softer')
  await s.started()
  expect(s.getPayload()).toMatchObject({ target_language: 'fr', fallback_language: 'en', style: 'softer', draft_intent: '', goal: 'Ask size', context_version: 0, draft_version: 0 })
  s.resolve(); await pending
  expect(s.bridge.suggest).toHaveBeenCalledTimes(1)
})
it('renews the random conversation epoch after switching chats', async () => {
  const s = setup(); const first = s.assistant.generate(options); await s.started(); const previous = s.getPayload().conversation_epoch
  s.resolve(); await first; s.assistant.chatChanged()
  const second = s.assistant.generate(options)
  await vi.waitFor(() => expect(s.bridge.suggest).toHaveBeenCalledTimes(2))
  expect(s.getPayload().conversation_epoch).not.toBe(previous)
  s.resolve(); await second
})
it.each(['needs_confirmation', 'insufficient_context'] as const)('does not fill %s results', async status => {
  const s = setup(); const pending = s.assistant.generate(options); await s.started(); s.resolve({ status }); await pending
  expect(await s.assistant.fill()).toBe(false)
  expect(s.adapter.readComposer()).toBe('原草稿')
})
it('rejects a response whose request metadata does not match', async () => {
  const s = setup(); const pending = s.assistant.generate(options); await s.started(); s.resolve({ draft_version: 999 }); await pending
  expect(s.assistant.getState().error).toBe('reply_invalid_response')
  expect(s.assistant.getState().result).toBeUndefined()
})
it.each(['close', 'cancel', 'optionsChanged', 'contextChanged'] as const)('cancels a pending restore on %s without overwriting the newer state', async action => {
  const s = setup(); const generated = s.assistant.generate(options); await s.started(); s.resolve(); await generated; await s.assistant.fill()
  let finish!: () => void
  const write = s.adapter.replaceComposer.getMockImplementation()!
  s.adapter.replaceComposer.mockImplementationOnce(async (value, isCurrent) => {
    await new Promise<void>(resolve => { finish = resolve })
    return write(value, isCurrent)
  })
  const pending = s.assistant.restore()
  s.assistant[action]()
  const previousState = { ...s.assistant.getState() }
  finish()
  expect(await pending).toBe(false)
  expect(s.adapter.readComposer()).toBe('What size would you prefer?')
  expect(s.assistant.getState()).toEqual(previousState)
  // A later explicit restore remains safe if the user has not edited the draft.
  await s.assistant.open()
  expect(await s.assistant.restore()).toBe(true)
  expect(s.adapter.readComposer()).toBe('原草稿')
})
it('awaits valid capabilities before reading any context and honors server default/count/char limits', async () => {
  const s = setup()
  let resolveCaps!: (value: typeof capabilities) => void
  s.bridge.capabilities.mockImplementationOnce(() => new Promise(resolve => { resolveCaps = resolve }))
  const pending = s.assistant.generate({ ...options, limit: 'default' })
  expect(s.adapter.collectReplyContext).not.toHaveBeenCalled()
  resolveCaps({ ...capabilities, default_messages: 10, max_messages: 15, max_context_chars: 6000 })
  await s.started()
  expect(s.adapter.collectReplyContext).toHaveBeenCalledWith(15, { maxMessages: 15, maxChars: 6000 })
  s.resolve(); await pending
})
it.each([
  { ...capabilities, max_context_chars: 0 },
  { ...capabilities, max_draft_chars: -1 },
  { ...capabilities, default_messages: 41 },
])('invalid server capabilities prevent context reads and suggestions', async caps => {
  const s = setup(); s.bridge.capabilities.mockResolvedValue(caps)
  await s.assistant.generate(options)
  expect(s.adapter.collectReplyContext).not.toHaveBeenCalled()
  expect(s.bridge.suggest).not.toHaveBeenCalled()
  expect(s.assistant.getState().error).toBe('reply_configuration_invalid')
})
it('cancellation during capability lookup prevents subsequent capture and generation', async () => {
  const s = setup(); let resolveCaps!: (value: typeof capabilities) => void
  s.bridge.capabilities.mockImplementationOnce(() => new Promise(resolve => { resolveCaps = resolve }))
  const pending = s.assistant.generate(options); s.assistant.close(); resolveCaps(capabilities); await pending
  expect(s.adapter.collectReplyContext).not.toHaveBeenCalled()
  expect(s.bridge.suggest).not.toHaveBeenCalled()
})
it.each(['draft', 'goal'] as const)('enforces the lowered server %s maximum before suggest', async field => {
  const s = setup(); s.bridge.capabilities.mockResolvedValue({ ...capabilities, max_draft_chars: 2, max_goal_chars: 2 })
  await s.assistant.generate({ ...options, includeDraft: field === 'draft', goal: field === 'goal' ? 'long goal' : '' })
  expect(s.assistant.getState().error).toBe(field === 'draft' ? 'reply_draft_too_long' : 'reply_goal_too_long')
  expect(s.bridge.suggest).not.toHaveBeenCalled()
})
