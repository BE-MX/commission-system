import type { RuntimeRequest, RuntimeResponse } from '../../src/shared/contracts'
import type { ReplyInquiry, InquiryEntry } from '../../src/shared/replyMemory'
const inquiries = new Map<string, ReplyInquiry>()
const syntheticTime = '2026-09-08T21:00:00'
const observedEntry = (): InquiryEntry => ({ id: crypto.randomUUID(), kind: 'request', status: 'open', summary: 'Customer asks for a sample', human_note: '', updated_at: syntheticTime,
  evidence: [{ request_id: crypto.randomUUID(), message_index: 0, role: 'customer', quote: 'sample', observed_at: syntheticTime }] })
const nativeFrame = window.requestAnimationFrame.bind(window)
const frames: FrameRequestCallback[] = []
window.requestAnimationFrame = callback => {
  if (document.documentElement.dataset.pauseComposerFrames === 'true') {
    frames.push(callback)
    document.documentElement.dataset.composerFramePending = 'true'
    return 0
  }
  return nativeFrame(callback)
}
document.addEventListener('synthetic-resume-frames', () => {
  document.documentElement.dataset.pauseComposerFrames = 'false'
  for (const frame of frames.splice(0)) nativeFrame(frame)
})
// Synthetic, isolated-world runtime only. All network is blocked by the browser test.
Object.assign(globalThis, { chrome: { runtime: {
  async sendMessage(request: RuntimeRequest): Promise<RuntimeResponse | undefined> {
    if (request.type === 'chat-language/get') return { type: request.type, targetLanguage: 'en' }
    if (request.type === 'chat-language/set') {
      document.documentElement.dataset.detectedLanguage = request.targetLanguage
      return { type: request.type, targetLanguage: request.targetLanguage }
    }
    if (request.type === 'reply/disclosure') return { type: request.type, acknowledged: true }
    if (request.type === 'reply/capabilities') return { type: request.type, reply: {
      available: true, max_messages: 40, default_messages: 20,
      max_context_chars: document.documentElement.dataset.lowerReplyLimit === 'true' ? 6000 : 12000,
      max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 30,
      memory_enabled: document.documentElement.dataset.memoryEnabled === 'true', memory_retention_days: 30,
    } }
    if (request.type === 'reply/memory') {
      const p = request.payload
      if (p.operation === 'list') return { type: request.type, result: { inquiries: [...inquiries.values()] } }
      if (p.operation === 'create') {
        const row: ReplyInquiry = { id: p.conversation_id!, label: 'Synthetic inquiry', revision: 0, entries: [], created_at: syntheticTime, updated_at: syntheticTime, expires_at: '2026-10-08T21:00:00' }
        inquiries.set(row.id, row)
      }
      if (p.operation === 'commit') {
        const row = inquiries.get(p.conversation_id!)!; row.revision += 1; row.entries = [observedEntry()]
        document.documentElement.dataset.memoryCommitted = String(row.revision)
      }
      if (p.operation === 'delete') { inquiries.delete(p.conversation_id!); return { type: request.type, result: { deleted: true } } }
      return { type: request.type, result: { inquiry: structuredClone(inquiries.get(p.conversation_id!)!) } }
    }
    if (request.type === 'translation/incoming') {
      if (document.documentElement.dataset.deferIncoming === 'true') {
        document.documentElement.dataset.incomingRequested = 'true'
        return new Promise(resolve => document.addEventListener('synthetic-incoming-resolve', () => resolve({
          type: 'translation/incoming', sourceLanguage: 'fr', translation: '合成消息翻译',
        }), { once: true }))
      }
      return { type: request.type, sourceLanguage: 'en', translation: '合成消息翻译' }
    }
    if (request.type === 'translation/outgoing') return { type: request.type, sourceLanguage: 'zh-CN', translation: 'Synthetic translated draft' }
    if (request.type === 'reply/suggest') {
      document.documentElement.dataset.replyRequested = 'true'
      const p = request.payload
      document.documentElement.dataset.replyCharacters = String(p.messages.reduce((sum, message) => sum + message.text.length, 0))
      document.documentElement.dataset.replyMessages = String(p.messages.length)
      document.documentElement.dataset.replyTruncated = String(p.context_scope.truncated)
      return new Promise(resolve => document.addEventListener('synthetic-reply-resolve', () => resolve({
        type: 'reply/suggest', result: {
          ...p, status: 'ready', reply_language: 'en', reply_text: 'What sample size do you need?',
          meaning_zh: '您需要什么尺寸的样品？', rationale_zh: '确认需求。', sources: [], claims: [], risk_flags: [], missing_information: [],
          ...(p.memory_conversation_id ? { memory_update: [observedEntry()], handoff: {
            needs: [], open_requests: ['Customer asks for a sample'], commitments: [], next_step: 'Clarify the sample specification', completion_signal: 'Customer chooses specification', limitations: 'No business action executed.',
          } } : {}),
        },
      }), { once: true }))
    }
    return undefined
  },
} } })
void import('../../src/content/index')
