import { afterEach, expect, it, vi } from 'vitest'
import type { ReplyContext } from '@/whatsapp/replyContext'
import { createAutoReply, type AutoSnapshot } from '@/content/autoReply'
import type { ReplyRequest, ReplyResponse } from '@/shared/contracts'
const caps = { available: true, history_enabled: true, auto_reply_enabled: true, max_messages: 2000, default_messages: 2000, max_context_chars: 120000, max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 120 }
afterEach(() => vi.useRealTimers())
function setup() {
  vi.useFakeTimers()
  const snapshot: AutoSnapshot = { identity: ['chat'], incoming: 'c1', tail: 'c1', role: 'customer', draft: '' }
  const response = (p: ReplyRequest): ReplyResponse => ({ ...p, status: 'ready', auto_action: 'reply', reply_segments: ['Hi!', 'Which size?'], reply_text: 'Hi! Which size?', reply_language: 'en', meaning_zh: '测试', rationale_zh: '确认尺寸', sources: [], claims: [], risk_flags: [], missing_information: [] })
  const suggest = vi.fn(async (p: ReplyRequest) => response(p))
  const send = vi.fn(async (_text: string, current: () => boolean) => { if (!current()) return false; snapshot.tail += '-sent'; snapshot.role = 'salesperson'; return true })
  const collect = vi.fn(async (): Promise<ReplyContext> => ({ messages: [{ role: 'customer' as const, text: 'Hello' }], loadedCount: 1, skippedUnknown: false, range: '1', context_scope: { requested_limit: 2000, truncated: false, omitted_media: false, latest_visible: true } }))
  const capabilities = vi.fn(async () => caps)
  const auto = createAutoReply({ snapshot: () => snapshot, collect, send }, { capabilities, suggest }, () => ({ language: 'auto', fallback: 'en', goal: 'Learn sample needs' }), vi.fn())
  return { auto, snapshot, send, suggest, response, capabilities, collect }
}
it('stays off until enabled, sends ordered short segments once, and then waits', async () => {
  const s = setup(); await vi.advanceTimersByTimeAsync(10000); expect(s.send).not.toHaveBeenCalled()
  s.auto.start(); await vi.advanceTimersByTimeAsync(7500)
  expect(s.send.mock.calls.map(c => c[0])).toEqual(['Hi!', 'Which size?'])
  expect(s.suggest.mock.calls[0][0]).toMatchObject({ mode: 'auto', goal: 'Learn sample needs' })
  await vi.advanceTimersByTimeAsync(20000); expect(s.suggest).toHaveBeenCalledTimes(1)
  s.auto.stop()
})
it('drops the remaining segment when a new customer message arrives', async () => {
  const s = setup(); s.auto.start(); await vi.advanceTimersByTimeAsync(4700)
  expect(s.send).toHaveBeenCalledTimes(1)
  s.snapshot.incoming = 'c2'; s.snapshot.tail = 'c2'; s.snapshot.role = 'customer'
  await vi.advanceTimersByTimeAsync(2400)
  expect(s.send).toHaveBeenCalledTimes(1); s.auto.stop()
})
it.each(['stop', 'chat', 'draft'])('cannot send after %s', async kind => {
  const s = setup(); s.auto.start(); await vi.advanceTimersByTimeAsync(3200)
  if (kind === 'stop') s.auto.stop()
  if (kind === 'chat') s.snapshot.identity = ['another']
  if (kind === 'draft') { s.snapshot.draft = 'Human draft'; s.auto.stop('人工输入') }
  await vi.advanceTimersByTimeAsync(10000); expect(s.send).not.toHaveBeenCalled()
})
it('never retries an uncertain send outcome', async () => {
  const s = setup(); s.send.mockResolvedValue(false); s.auto.start()
  await vi.advanceTimersByTimeAsync(20000)
  expect(s.send).toHaveBeenCalledTimes(1); expect(s.auto.getState().active).toBe(false)
})
it('retains all generated parts and zero submissions when the first send control is unavailable', async () => {
  const s = setup(); const parts = ['Synthetic process answer.', 'Synthetic coating answer.', 'Please confirm the specification.']
  s.suggest.mockImplementation(async p => ({ ...s.response(p), reply_segments: parts }))
  s.send.mockRejectedValue(new Error('reply_send_control_unavailable'))
  s.auto.start(); await vi.advanceTimersByTimeAsync(10000)
  expect(s.send).toHaveBeenCalledTimes(1)
  expect(s.auto.getState()).toMatchObject({ active: false, segments: parts, sentCount: 0 })
})
it('sends three topic answers in order and records every local submission', async () => {
  const s = setup(); const parts = ['Synthetic process answer.', 'Synthetic coating answer.', 'Please confirm the specification.']
  s.suggest.mockImplementation(async p => ({ ...s.response(p), reply_segments: parts }))
  s.auto.start(); await vi.advanceTimersByTimeAsync(12000)
  expect(s.send.mock.calls.map(call => call[0])).toEqual(parts)
  expect(s.auto.getState()).toMatchObject({ active: true, segments: parts, sentCount: 3 }); s.auto.stop()
})
it.each(['wait', 'handoff'] as const)('does not send model action %s', async action => {
  const s = setup(); s.suggest.mockImplementation(async p => ({ ...s.response(p), auto_action: action, reply_segments: [] }))
  s.auto.start(); await vi.advanceTimersByTimeAsync(10000)
  expect(s.send).not.toHaveBeenCalled(); expect(s.suggest).toHaveBeenCalledTimes(1); s.auto.stop()
})
it('does not enable over a human draft', () => {
  const s = setup(); s.snapshot.draft = 'Human'; s.auto.start(); expect(s.auto.getState().active).toBe(false)
})
it('passes historical unknown placeholders to the agent when the latest customer message is readable', async () => {
  const s = setup(); const context = await s.collect()
  s.collect.mockResolvedValue({ ...context, skippedUnknown: true, messages: [{ role: 'customer', kind: 'unknown', text: '[未识别的消息结构]' }, ...context.messages] })
  s.auto.start(); await vi.advanceTimersByTimeAsync(10000)
  expect(s.suggest).toHaveBeenCalledTimes(1); expect(s.send).toHaveBeenCalledTimes(2)
  expect(s.suggest.mock.calls[0][0].messages[0].kind).toBe('unknown'); s.auto.stop()
})
it.each(['unknown', 'media'] as const)('still stops for an unreadable latest %s message', async kind => {
  const s = setup(); const context = await s.collect()
  s.collect.mockResolvedValue({ ...context, messages: [{ role: 'customer', kind, text: '[未读取内容]' }] })
  s.auto.start(); await vi.advanceTimersByTimeAsync(10000)
  expect(s.send).not.toHaveBeenCalled(); expect(s.suggest).not.toHaveBeenCalled()
  expect(s.auto.getState().note).toContain('最新消息')
})
it('does not generate if some messages have no identifiable sender', async () => {
  const s = setup(); const context = await s.collect()
  s.collect.mockResolvedValue({ ...context, skippedUnknown: true, unrepresentedMessages: true })
  s.auto.start(); await vi.advanceTimersByTimeAsync(10000)
  expect(s.suggest).not.toHaveBeenCalled(); expect(s.send).not.toHaveBeenCalled()
  expect(s.auto.getState().note).toContain('发送方')
})
it('stops before generation when backend auto support is missing', async () => {
  const s = setup(); s.capabilities.mockResolvedValue({ ...caps, auto_reply_enabled: false }); s.auto.start()
  await vi.advanceTimersByTimeAsync(8000); expect(s.suggest).not.toHaveBeenCalled(); expect(s.auto.getState().active).toBe(false)
})

it('stays stopped when an uncertain send coincides with a new customer message', async () => {
  const s = setup()
  s.send.mockImplementation(async () => {
    s.snapshot.incoming = 'c2'; s.snapshot.tail = 'c2'
    await new Promise(resolve => setTimeout(resolve, 500)); return false
  })
  s.auto.start(); await vi.advanceTimersByTimeAsync(20000)
  expect(s.send).toHaveBeenCalledTimes(1); expect(s.suggest).toHaveBeenCalledTimes(1)
  expect(s.auto.getState().active).toBe(false)
})

it('refuses to auto reply when the latest boundary was not verified', async () => {
  const s = setup(); const context = await s.collect()
  s.collect.mockResolvedValue({ ...context, context_scope: { ...context.context_scope, latest_visible: false } })
  s.auto.start(); await vi.advanceTimersByTimeAsync(10000)
  expect(s.suggest).not.toHaveBeenCalled(); expect(s.send).not.toHaveBeenCalled(); expect(s.auto.getState().active).toBe(false)
})

it('does not generate from a capture superseded by a seller reply', async () => {
  const s = setup(); const context = await s.collect()
  s.collect.mockImplementation(async () => { s.snapshot.role = 'salesperson'; s.snapshot.tail = 'seller'; return context })
  s.auto.start(); await vi.advanceTimersByTimeAsync(10000)
  expect(s.suggest).not.toHaveBeenCalled(); expect(s.send).not.toHaveBeenCalled(); s.auto.stop()
})
