import { TARGET_LANGUAGES } from '@/shared/contracts'
import type { ReplyCapabilities, ReplyRequest, ReplyResponse } from '@/shared/contracts'

/** Server configuration may narrow these local safety ceilings, never widen them. */
export function boundedReplyCapabilities(value: unknown): ReplyCapabilities {
  if (!value || typeof value !== 'object' || (value as ReplyCapabilities).available !== true) throw new Error('reply_unavailable')
  const p = value as ReplyCapabilities
  const positive = [p.max_messages, p.default_messages, p.max_context_chars, p.timeout_seconds]
  const optional = [p.max_draft_chars, p.max_goal_chars]
  if (positive.some(n => !Number.isSafeInteger(n) || n < 1) || optional.some(n => !Number.isSafeInteger(n) || n < 0)
    || p.default_messages > p.max_messages) throw new Error('reply_configuration_invalid')
  return {
    available: true, max_messages: Math.min(40, p.max_messages), default_messages: Math.min(40, p.default_messages),
    max_context_chars: Math.min(12000, p.max_context_chars), max_draft_chars: Math.min(2000, p.max_draft_chars),
    max_goal_chars: Math.min(500, p.max_goal_chars), timeout_seconds: Math.min(35, p.timeout_seconds),
  }
}

export function replyFitsCapabilities(p: ReplyRequest, caps: ReplyCapabilities): boolean {
  return p.messages.length <= caps.max_messages && p.messages.reduce((sum, message) => sum + message.text.length, 0) <= caps.max_context_chars
    && p.draft_intent.length <= caps.max_draft_chars && p.goal.length <= caps.max_goal_chars
}

const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/iu
const isText = (value: unknown, max: number) => typeof value === 'string' && value.length <= max
const language = (value: unknown) => (TARGET_LANGUAGES as readonly unknown[]).includes(value)
export function validReplyRequest(value: unknown): value is ReplyRequest {
  if (!value || typeof value !== 'object') return false
  const p = value as ReplyRequest
  return typeof p.request_id === 'string' && uuid.test(p.request_id)
    && typeof p.conversation_epoch === 'string' && uuid.test(p.conversation_epoch)
    && Number.isInteger(p.context_version) && p.context_version >= 0
    && Number.isInteger(p.draft_version) && p.draft_version >= 0
    && Array.isArray(p.messages) && p.messages.length > 0 && p.messages.length <= 40
    && p.messages.every(m => m && ['customer', 'salesperson'].includes(m.role) && isText(m.text, 12000) && m.text.trim())
    && p.messages.reduce((n, m) => n + m.text.length, 0) <= 12000
    && !!p.context_scope && [20, 40].includes(p.context_scope.requested_limit)
    && p.messages.length <= p.context_scope.requested_limit
    && ['truncated', 'omitted_media', 'latest_visible'].every(key => typeof p.context_scope[key as keyof typeof p.context_scope] === 'boolean')
    && isText(p.draft_intent, 2000) && isText(p.goal, 500)
    && (p.target_language === 'auto' || language(p.target_language)) && language(p.fallback_language)
    && ['default', 'shorter', 'softer', 'alternative'].includes(p.style)
}
export function validReplyResponse(value: unknown, request: ReplyRequest): value is ReplyResponse {
  if (!value || typeof value !== 'object') return false
  const p = value as ReplyResponse
  return p.request_id === request.request_id && p.conversation_epoch === request.conversation_epoch
    && p.context_version === request.context_version && p.draft_version === request.draft_version
    && ['ready', 'needs_confirmation', 'insufficient_context'].includes(p.status) && language(p.reply_language)
    && isText(p.reply_text, 12000) && (p.status !== 'ready' || !!p.reply_text.trim())
    && isText(p.meaning_zh, 12000) && isText(p.rationale_zh, 4000)
    && Array.isArray(p.sources) && p.sources.length <= 30
    && p.sources.every(s => s && [s.document_id, s.revision_id, s.version_no].every(n => Number.isInteger(n) && n > 0) && isText(s.title, 500) && isText(s.section, 500))
    && Array.isArray(p.claims) && p.claims.length <= 50
    && p.claims.every(c => c && isText(c.text, 4000) && isText(c.quote, 4000) && Number.isInteger(c.source_index) && c.source_index >= 0 && c.source_index < p.sources.length)
    && [p.risk_flags, p.missing_information].every(items => Array.isArray(items) && items.length <= 50 && items.every(t => isText(t, 2000)))
}
