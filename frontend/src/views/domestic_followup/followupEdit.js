import { newRequestId } from './followupDraft.js'

export function mayEditFollowup(user, record) {
  return Boolean(record && (user?.roles?.includes('super_admin') || (
    Number(user?.id) === Number(record.author_user_id) && user?.permissions?.includes('domestic_followup:write'))))
}

export function recordToEditForm(record) {
  return {
    version: record.version, request_id: newRequestId(), reason: '',
    raw_text: record.raw_text || '', followup_date: record.followup_date, channel: record.channel,
    summary: record.summary || '', state_changes: [...(record.state_changes || [])],
    next_date: record.next_date, next_plan: record.next_plan || '', next_method: record.next_method,
    attachment_ids: record.attachments.map(a => a.id),
    items: record.items.map(item => ({
      id: item.id, kind: item.kind, text: item.text, category: item.category, severity: item.severity,
      origin: item.origin, handler_user_id: item.handler_user_id,
      record_only: item.status === 'closed_no_action' && (item.resolution || '').startsWith('仅记录'),
    })),
  }
}

export function canRemoveEditItem(item, record) {
  if (!item.id || item.kind === 'content') return true
  const old = record.items.find(row => row.id === item.id)
  return old?.status === 'open' || (old?.status === 'closed_no_action' && (old.resolution || '').startsWith('仅记录'))
}

export function canToggleRecordOnly(item, record) {
  return canRemoveEditItem(item, record)
}
