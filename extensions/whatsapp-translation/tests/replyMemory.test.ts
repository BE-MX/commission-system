import { describe, expect, it, vi } from 'vitest'
import { createReplyAssistant } from '@/content/replyAssistant'
import { createMemoryView, renderHandoff } from '@/content/replyMemoryView'
import type { ReplyRequest, ReplyResponse } from '@/shared/contracts'
import { validMemoryCommand, validMemoryResult } from '@/shared/replyMemory'
import type { MemoryCommand, MemoryResult, ReplyInquiry } from '@/shared/replyMemory'
import { JSDOM } from 'jsdom'

const caps = { available: true, max_messages: 40, default_messages: 20, max_context_chars: 12000, max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 30, memory_enabled: true, memory_retention_days: 30 }
const options = { limit: 'default' as const, includeDraft: true, language: 'auto' as const, goal: '' }
const now = '2026-09-08T21:00:00'
const entry = () => ({ id: crypto.randomUUID(), kind: 'need' as const, status: 'tentative' as const, summary: '20 units initially', human_note: '', updated_at: now,
  evidence: [{ request_id: crypto.randomUUID(), message_index: 0, role: 'customer' as const, quote: '20 units', observed_at: now }] })
const inquiry = (id: string = crypto.randomUUID()): ReplyInquiry => ({ id, label: 'Synthetic inquiry', revision: 0, entries: [], created_at: now, updated_at: now, expires_at: '2026-10-08T21:00:00' })
const handoff = { needs: ['20 units initially'], open_requests: ['Catalog'], commitments: [], next_step: 'Provide a relevant catalog', completion_signal: 'Customer selects models', limitations: 'No tasks were executed.' }

function setup() {
  let finish!: (result: ReplyResponse) => void
  let payload!: ReplyRequest
  const records = new Map<string, ReplyInquiry>()
  const bridge = {
    capabilities: vi.fn(async () => caps),
    suggest: vi.fn((request: ReplyRequest) => { payload = request; return new Promise<ReplyResponse>(resolve => { finish = resolve }) }),
    memory: vi.fn(async (command: MemoryCommand): Promise<MemoryResult> => {
      if (command.operation === 'list') return { inquiries: [...records.values()].map(r => ({ ...r, entries: [] })) }
      const id = command.conversation_id!
      if (command.operation === 'create') { const record = records.get(id) ?? inquiry(id); records.set(id, record); return { inquiry: structuredClone(record) } }
      if (command.operation === 'delete') { records.delete(id); return { deleted: true } }
      const record = records.get(id)!
      if (command.operation === 'commit') { record.revision += 1; record.entries = [entry()] }
      if (command.operation === 'correct') { record.revision += 1; record.entries[0].human_note = command.note! }
      return { inquiry: structuredClone(record) }
    }),
  }
  const adapter = {
    inspectChat: () => ({ kind: 'direct' }), readComposer: () => 'unsent intent', replaceComposer: vi.fn(async () => true),
    collectReplyContext: () => ({ messages: [{ role: 'customer' as const, text: 'I would like 20 units.' }], context_scope: { requested_limit: 20 as const, truncated: false, omitted_media: false, latest_visible: false }, loadedCount: 1, skippedUnknown: false, range: '1–1' }),
  }
  const assistant = createReplyAssistant(adapter, bridge, () => 'en', vi.fn())
  return {
    assistant, bridge, records,
    started: () => vi.waitFor(() => expect(bridge.suggest).toHaveBeenCalled()),
    resolve: () => finish({ ...payload, status: 'ready', reply_language: 'en', reply_text: 'Understood, 20 units initially.', meaning_zh: '暂定20件。', rationale_zh: '先选品', sources: [], claims: [], risk_flags: [], missing_information: [], memory_update: [entry()], handoff }),
  }
}

describe('inquiry continuity', () => {
  it('saves a current observation snapshot separately and uses its new revision next turn', async () => {
    const s = setup(); const pending = s.assistant.generate(options); await s.started(); s.resolve(); await pending
    expect(s.bridge.memory.mock.calls.map(([c]) => c.operation)).toEqual(['create', 'commit'])
    expect(s.assistant.getState().inquiry?.revision).toBe(1)
    s.assistant.contextChanged()
    const second = s.assistant.generate(options)
    await vi.waitFor(() => expect(s.bridge.suggest).toHaveBeenCalledTimes(2))
    expect(s.bridge.suggest.mock.calls[1][0].memory_revision).toBe(1)
    s.resolve(); await second
    expect(s.bridge.memory.mock.calls.every(([c]) => !('entries' in c))).toBe(true)
  })
  it.each(['cancel', 'contextChanged', 'draftChanged', 'chatChanged', 'close', 'optionsChanged'] as const)('never saves a late response after %s', async action => {
    const s = setup(); const pending = s.assistant.generate(options); await s.started(); s.assistant[action](); s.resolve(); await pending
    expect(s.bridge.memory.mock.calls.map(([c]) => c.operation)).toEqual(['create'])
    expect(s.assistant.getState().result).toBeUndefined()
  })
  it('same-name chat switches always disconnect and create a fresh record', async () => {
    const s = setup(); const first = s.assistant.generate(options); await s.started(); s.resolve(); await first
    const old = s.assistant.getState().inquiry!.id; s.assistant.chatChanged()
    expect(s.assistant.getState().inquiry).toBeUndefined()
    const second = s.assistant.generate(options); await vi.waitFor(() => expect(s.bridge.suggest).toHaveBeenCalledTimes(2)); s.resolve(); await second
    expect(s.assistant.getState().inquiry!.id).not.toBe(old)
  })
  it('requires preview selection before an old record is used', async () => {
    const s = setup(); const old = inquiry(); s.records.set(old.id, old)
    await s.assistant.listInquiries(); expect(s.assistant.getState().inquiry).toBeUndefined()
    await s.assistant.previewInquiry(old.id); expect(s.assistant.getState().inquiry).toBeUndefined()
    s.assistant.usePreview(); expect(s.assistant.getState().inquiry?.id).toBe(old.id)
  })
  it.each(['delete', 'correct'] as const)('reconciles an acknowledged %s when new text arrives in the same chat', async operation => {
    const s = setup(); const first = s.assistant.generate(options); await s.started(); s.resolve(); await first
    const record = s.assistant.getState().inquiry!
    let finish!: (value: MemoryResult) => void
    s.bridge.memory.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const pending = operation === 'delete' ? s.assistant.deleteMemory() : s.assistant.correctMemory(record.entries[0].id, 'human_confirmed', '10 units')
    s.assistant.contextChanged()
    finish(operation === 'delete' ? { deleted: true } : { inquiry: { ...record, revision: 2, entries: [{ ...record.entries[0], human_note: '10 units', status: 'human_confirmed' }] } })
    await pending
    expect(s.assistant.getState().memoryBusy).toBe(false)
    if (operation === 'delete') { expect(s.assistant.getState().inquiry).toBeUndefined(); expect(s.assistant.getState().memoryEnabled).toBe(false) }
    else expect(s.assistant.getState().inquiry?.revision).toBe(2)
  })
  it('does not attach a committed snapshot to another chat', async () => {
    const s = setup(); const first = s.assistant.generate(options); await s.started()
    let finish!: (value: MemoryResult) => void
    s.bridge.memory.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    s.resolve(); await vi.waitFor(() => expect(s.assistant.getState().memoryBusy).toBe(true))
    const old = s.assistant.getState().inquiry!; s.assistant.chatChanged(); finish({ inquiry: { ...old, revision: 1 } }); await first
    expect(s.assistant.getState().inquiry).toBeUndefined()
  })
  it('keeps the handoff summary when pausing and makes no further model call', async () => {
    const s = setup(); const pending = s.assistant.generate(options); await s.started(); s.resolve(); await pending
    s.assistant.setPaused(true); await s.assistant.generate(options)
    expect(s.bridge.suggest).toHaveBeenCalledTimes(1)
    expect(s.assistant.getState().handoffResult?.handoff?.open_requests).toEqual(['Catalog'])
  })
  it('supports stateless mode without creating or saving a record', async () => {
    const s = setup(); s.assistant.setMemoryEnabled(false); const pending = s.assistant.generate(options); await s.started(); s.resolve(); await pending
    expect(s.bridge.memory).not.toHaveBeenCalled()
  })
})

it('validates record ownership echoes and bounds instead of trusting wire shapes', () => {
  const record = inquiry()
  expect(validMemoryCommand({ operation: 'commit', conversation_id: record.id, request_id: 'not-uuid' })).toBe(false)
  expect(validMemoryResult({ inquiry: record }, { operation: 'read', conversation_id: crypto.randomUUID() })).toBe(false)
  expect(validMemoryResult({ inquiry: record }, { operation: 'read', conversation_id: record.id })).toBe(true)
  expect(validMemoryResult({ inquiry: { ...record, entries: [entry(), ...Array(81).fill(entry())] } }, { operation: 'read', conversation_id: record.id })).toBe(false)
})

it('renders human corrections as text and retains takeover details without execution claims', () => {
  const doc = new JSDOM('<main></main>').window.document
  const handlers = { list: vi.fn(), preview: vi.fn(), usePreview: vi.fn(), create: vi.fn(), enabled: vi.fn(), refresh: vi.fn(), remove: vi.fn(), save: vi.fn(), correct: vi.fn(), pause: vi.fn() }
  const view = createMemoryView(doc, handlers)
  const record = { ...inquiry(), entries: [{ ...entry(), status: 'human_confirmed' as const, human_note: '<img src=x onerror=alert(1)> 10 units' }] }
  view.render({ open: true, busy: false, canRestore: false, capabilities: caps, inquiry: record }, code => code)
  expect(view.root.querySelector('img')).toBeNull()
  expect(view.root.textContent).toContain('人工核实：<img')
  const panel = renderHandoff(doc, { open: true, busy: false, canRestore: false, handoffResult: { handoff }, paused: true }, handlers.pause)
  expect(panel.textContent).toContain('Catalog')
  expect(panel.textContent).toContain('恢复话术辅助')
})
