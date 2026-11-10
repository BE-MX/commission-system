export { newRequestKey as requestKey } from '../../utils/requestKey.js'

export const REASON_FILTERS = [
  { value: 'R1_UNREPLIED', label: '待回复' },
  { value: 'R7_AWAITING_CUSTOMER', label: '等客户回' },
  { value: 'R2_FOLLOWUP_DUE', label: '跟进到期' },
  { value: 'R8_NEW_LEAD', label: '新客户' },
]
export const CHANNELS = { phone: '电话', whatsapp: 'WhatsApp', email: '邮件（手工）', tm: 'TM（手工）', meeting: '见面', sample: '寄样', other: '其他' }
export const SOURCES = { all: '全部', whatsapp: 'WhatsApp', order: '订单', research: '背调', followup: '跟进' }
export function errorText(error) {
  const detail = error?.response?.data?.detail
  return (typeof detail === 'object' ? detail?.message : detail) || error?.response?.data?.message || error?.message || '加载失败，请重试'
}
export function safeDestination(value) {
  if (typeof value !== 'string') return null
  if (value.startsWith('/client-desk') && !value.startsWith('//')) return value
  try { const url = new URL(value); return url.protocol === 'https:' && url.hostname === 'wa.me' ? url.href : null } catch { return null }
}
export function analysisLabel(status) {
  return ({ succeeded: 'AI 建议', queued: '等待分析', running: '正在分析', ambiguous: '结果未确认 · 未自动重试', failed: '分析失败 · 规则提醒', rule_only: '仅规则提醒', revoked: '授权已变更，需重新分析' })[status] || '尚未分析'
}
export function latestRequestGate() {
  let generation = 0
  return { next: () => ++generation, current: token => generation === token, invalidate: () => ++generation }
}

export function normalizeDetail(data) {
  const suggestion = data.suggestion ? { ...data.suggestion, draft: data.suggestion.draft_message ?? data.suggestion.draft } : null
  return { ...data, personal_state: { ...data.personal_state, brief_md: data.brief_md ?? data.personal_state?.brief_md, last_analyzed_at: data.last_analyzed_at ?? data.personal_state?.last_analyzed_at }, suggestion }
}

export async function revalidatedDraft(loadCustomer, customerId, suggestionId, isCurrent) {
  const fresh = normalizeDetail(await loadCustomer(customerId))
  if (!isCurrent() || String(fresh.suggestion?.id) !== String(suggestionId) || !fresh.suggestion?.draft) {
    throw new Error('草稿或来源已变化，请重新查看客户资料。')
  }
  return fresh
}

export async function copyOrFallback(text, writeText, isCurrent) {
  try { await writeText(text); return isCurrent() ? { copied: true, text } : null }
  catch { return isCurrent() ? { copied: false, text } : null }
}
