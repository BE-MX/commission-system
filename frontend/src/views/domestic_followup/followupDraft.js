/** 跟进表单的纯逻辑：草稿 ↔ 表单、粘贴截图、到期文案。无 Vue 依赖，便于 node --test。 */
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

export function newRequestId() {
  return globalThis.crypto?.randomUUID?.() || `fu-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function weekdayLabel(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''))
  if (!m) return ''
  // 用 UTC 构造避免客户端时区把日期挪一天（红线 23）
  return WEEKDAYS[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()]
}

const shortDate = iso => String(iso || '').slice(5)

export function emptyForm(today) {
  return {
    id: null, version: null, customer_id: null, followup_date: today, channel: null, raw_text: '',
    summary: '', chat_title: null, customerConfidence: null,
    contents: [], issues: [], suggestions: [], state_changes: [],
    next_date: null, next_plan: '', next_method: null, nextBasis: 'none', nextExpression: null,
    unreadable: [], closeTaskIds: [], resolvedItems: [], source_task_id: null,
  }
}

const tracked = item => ({
  text: item.text || '', category: item.category || null, severity: item.severity || '一般',
  origin: item.origin || 'user', record_only: Boolean(item.record_only),
})

export function draftToForm(draft, today) {
  const ai = draft?.ai_result || {}
  const items = ai.items || []
  const next = ai.next || {}
  return {
    ...emptyForm(today),
    id: draft.id, version: draft.version, raw_text: draft.raw_text || '',
    followup_date: draft.followup_date || today, source_task_id: draft.source_task_id || null,
    customer_id: draft.customer_id || ai.customer_id || null,
    customerConfidence: draft.customer_id ? null : (ai.customer_confidence ?? null),
    chat_title: ai.chat_title || null, summary: ai.summary || '',
    channel: draft.channel || ai.channel || null,  // 用户在输入步选的沟通方式优先
    contents: items.filter(i => i.kind === 'content').map(i => ({ text: i.text, origin: i.origin || 'user' })),
    issues: items.filter(i => i.kind === 'issue').map(tracked),
    suggestions: items.filter(i => i.kind === 'suggestion').map(tracked),
    state_changes: ai.state_changes || [],
    next_date: next.date || null, next_plan: next.plan || '', next_method: next.method || null,
    nextBasis: next.basis || 'none', nextExpression: next.expression || null,
    unreadable: ai.unreadable || [],
  }
}

const clean = text => String(text || '').trim()

export function formToPayload(form) {
  const items = [
    ...form.contents.map(i => ({ kind: 'content', text: clean(i.text), origin: i.origin || 'user', record_only: false })),
    ...form.issues.map(i => ({ kind: 'issue', ...tracked(i), text: clean(i.text) })),
    ...form.suggestions.map(i => ({ kind: 'suggestion', ...tracked(i), text: clean(i.text) })),
  ].filter(i => i.text)
  return {
    customer_id: form.customer_id || null,
    followup_date: form.followup_date || null,
    channel: form.channel || null,
    summary: clean(form.summary) || null,
    chat_title: form.chat_title || null,
    state_changes: form.state_changes || [],
    next_date: form.next_date || null,
    next_plan: clean(form.next_plan) || null,
    next_method: form.next_method || null,
    items,
    close_task_ids: form.closeTaskIds || [],
    resolved_items: (form.resolvedItems || []).map(r => ({
      item_id: r.item_id, status: r.status || 'resolved', resolution: clean(r.resolution) || null,
    })),
  }
}

const filled = value => (typeof value === 'string' ? Boolean(value.trim()) : value != null)

/** AI 结果回填后，把输入步手填的沟通方式与下次跟进字段盖回去：用户亲手写的比 AI 推断可信。 */
export function mergeManualFields(form, manual) {
  if (!manual) return form
  const merged = { ...form }
  for (const key of ['channel', 'next_date', 'next_plan', 'next_method']) {
    if (filled(manual[key])) merged[key] = manual[key]
  }
  if (filled(manual.next_date)) Object.assign(merged, { nextBasis: 'none', nextExpression: null })
  return merged
}

export function clipboardHasText(event) {
  return Array.from(event?.clipboardData?.types || []).includes('text/plain')
}

export function imageFilesFromDrop(event) {
  return Array.from(event?.dataTransfer?.files || []).filter(f => String(f.type).startsWith('image/'))
}

export function imageFilesFromClipboard(event) {
  const items = Array.from(event?.clipboardData?.items || [])
  return items.filter(i => i.kind === 'file' && String(i.type).startsWith('image/'))
    .map(i => i.getAsFile()).filter(Boolean)
}

export function taskDueLabel(task, today) {
  if (task.overdue_days > 0) return `逾期 ${task.overdue_days} 天`
  if (task.due_date === today) return '今天'
  return `${shortDate(task.due_date)} ${weekdayLabel(task.due_date)}`
}

export function nextBasisHint(form) {
  if (form.nextBasis === 'mismatch') return `AI 给的日期和原话不一致，已按「${form.nextExpression}」改为 ${shortDate(form.next_date)}，请核对`
  if (form.nextBasis === 'unverified') return 'AI 推算的日期，原话里没有明确时间，请核对'
  return ''
}
