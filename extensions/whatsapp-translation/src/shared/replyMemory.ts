/** Inquiry IDs are random record handles, never WhatsApp contact identifiers. */
export type InquiryEntry = {
  id: string
  kind: 'need' | 'question' | 'request' | 'commitment'
  status: 'confirmed' | 'tentative' | 'open' | 'answered' | 'mentioned' | 'reported_done' | 'cancelled' | 'human_confirmed' | 'human_completed' | 'pending'
  summary: string
  evidence: { request_id: string; message_index: number; role: 'customer' | 'salesperson'; quote: string; observed_at: string }[]
  updated_at: string
  human_note: string
}
export type ReplyInquiry = {
  id: string; label: string; revision: number; entries: InquiryEntry[]
  created_at: string; updated_at: string; expires_at: string
}
export type MemoryCommand = {
  operation: 'list' | 'create' | 'read' | 'commit' | 'correct' | 'delete'
  conversation_id?: string; revision?: number; request_id?: string; entry_id?: string
  label?: string; note?: string; status?: 'cancelled' | 'human_confirmed' | 'human_completed' | 'pending'
}
export type MemoryResult = { inquiry?: ReplyInquiry; inquiries?: ReplyInquiry[]; deleted?: boolean }
export type ReplyAction = {
  kind: 'answer' | 'clarify' | 'provide_asset' | 'request_quote' | 'handoff' | 'close'
  focus: string; question: string; owner: 'customer' | 'salesperson' | 'none'; completion_signal: string
}
export type HandoffSummary = {
  needs: string[]; open_requests: string[]; commitments: { summary: string; status: string }[]
  next_step: string; completion_signal: string; limitations: string
}
export const MEMORY_STATUS: Record<InquiryEntry['status'], string> = {
  confirmed: '客户确认', tentative: '初步意向', open: '待回应', answered: '对话已回应',
  mentioned: '卖方提及，执行待核实', reported_done: '卖方声称完成', cancelled: '已取消',
  human_confirmed: '人工核实', human_completed: '人工标记完成', pending: '人工标记待办',
}
export const MEMORY_KIND: Record<InquiryEntry['kind'], string> = { need: '需求', question: '已问问题', request: '客户请求', commitment: '承诺台账' }
export const ACTION_LABEL: Record<ReplyAction['kind'], string> = { answer: '回应问题', clarify: '补充确认', provide_asset: '提供资料', request_quote: '准备核价', handoff: '人工接管', close: '结束沟通' }

const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/iu
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.length <= max
const date = (v: unknown) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/u.test(v)
export function validMemoryCommand(value: unknown): value is MemoryCommand {
  if (!value || typeof value !== 'object') return false
  const p = value as MemoryCommand
  return ['list', 'create', 'read', 'commit', 'correct', 'delete'].includes(p.operation)
    && (p.operation === 'list' || (typeof p.conversation_id === 'string' && uuid.test(p.conversation_id)))
    && (p.revision === undefined || (Number.isSafeInteger(p.revision) && p.revision >= 0))
    && (p.operation !== 'commit' || (typeof p.request_id === 'string' && uuid.test(p.request_id)))
    && (p.label === undefined || text(p.label, 80)) && (p.note === undefined || text(p.note, 240))
    && (p.operation !== 'correct' || (typeof p.entry_id === 'string' && uuid.test(p.entry_id)
      && !!p.note?.trim() && ['cancelled', 'human_confirmed', 'human_completed', 'pending'].includes(p.status ?? '')))
}
export function validEntries(value: unknown): value is InquiryEntry[] {
  return Array.isArray(value) && value.length <= 80 && value.every(e => e && uuid.test(e.id)
    && Object.hasOwn(MEMORY_KIND, e.kind) && Object.hasOwn(MEMORY_STATUS, e.status)
    && text(e.summary, 240) && text(e.human_note, 240) && date(e.updated_at)
    && Array.isArray(e.evidence) && e.evidence.length > 0 && e.evidence.length <= 3
    && e.evidence.every((s: InquiryEntry['evidence'][number]) => s && uuid.test(s.request_id)
      && Number.isInteger(s.message_index) && s.message_index >= 0 && s.message_index <= 39
      && ['customer', 'salesperson'].includes(s.role) && text(s.quote, 240) && date(s.observed_at)))
}
export function validInquiry(v: unknown): v is ReplyInquiry {
  if (!v || typeof v !== 'object') return false
  const p = v as ReplyInquiry
  return uuid.test(p.id) && text(p.label, 80) && Number.isSafeInteger(p.revision) && p.revision >= 0
    && date(p.created_at) && date(p.updated_at) && date(p.expires_at) && validEntries(p.entries)
}
export function validMemoryResult(value: unknown, command: MemoryCommand): value is MemoryResult {
  if (!value || typeof value !== 'object') return false
  const p = value as MemoryResult
  if (command.operation === 'list') return Array.isArray(p.inquiries) && p.inquiries.length <= 100 && p.inquiries.every(validInquiry)
  if (command.operation === 'delete') return p.deleted === true
  return validInquiry(p.inquiry) && p.inquiry.id === command.conversation_id
}
export function validAction(value: unknown): value is ReplyAction {
  if (!value || typeof value !== 'object') return false
  const p = value as ReplyAction
  return Object.hasOwn(ACTION_LABEL, p.kind) && text(p.focus, 240) && text(p.question, 240)
    && text(p.completion_signal, 240) && ['customer', 'salesperson', 'none'].includes(p.owner)
}
export function validHandoff(value: unknown): value is HandoffSummary {
  if (!value || typeof value !== 'object') return false
  const p = value as HandoffSummary
  return [p.needs, p.open_requests].every(a => Array.isArray(a) && a.length <= 80 && a.every(t => text(t, 240)))
    && Array.isArray(p.commitments) && p.commitments.length <= 80 && p.commitments.every(c => c && text(c.summary, 240) && Object.hasOwn(MEMORY_STATUS, c.status))
    && text(p.next_step, 240) && text(p.completion_signal, 240) && text(p.limitations, 240)
}
