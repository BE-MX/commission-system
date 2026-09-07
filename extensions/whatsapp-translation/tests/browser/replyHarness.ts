import type { RuntimeRequest, RuntimeResponse } from '../../src/shared/contracts'
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
    } }
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
        },
      }), { once: true }))
    }
    return undefined
  },
} } })
void import('../../src/content/index')
