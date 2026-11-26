// Pure logic for the unlinked-leads (B track) view: clock, form validation, card and review mapping. No Vue, no I/O.

export const WORK_HOURS = { start: 9, end: 18 }
export const LEAD_CHANNEL_LABELS = { tm: 'TM 询盘' }
export const URGENCY_LABELS = { high: '高', medium: '中', low: '低' }
export const IGNORE_CONFIRM_TEXT = '标记为「不是客户」后，该线索的分析内容（前情、草稿等）会被清空，确定继续吗？'

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

export function isIsoDate(value) {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false
  const [y, m, d] = value.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d
}

// Local clock for the lead's own timezone. Returns null when the backend has no timezone, so the UI shows nothing.
export function localClock(timezone, now = new Date()) {
  if (!timezone) return null
  let hour, minute
  try {
    const parts = new Intl.DateTimeFormat('en-GB', { timeZone: timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now)
    hour = Number(parts.find(p => p.type === 'hour')?.value)
    minute = Number(parts.find(p => p.type === 'minute')?.value)
  } catch {
    return null
  }
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null
  const working = hour >= WORK_HOURS.start && hour < WORK_HOURS.end
  const hm = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
  return { hm, working, text: `当地 ${hm} · ${working ? '工作时段' : '非工作时段'}` }
}

// Prospect follow-up form: both the date and the promise text are mandatory.
export function validateProspectForm({ next_followup_date: date = '', next_followup_remark: remark = '' } = {}) {
  const errors = {}
  if (!date) errors.next_followup_date = '请选择下次跟进日期'
  else if (!isIsoDate(date)) errors.next_followup_date = '日期格式不正确'
  const text = String(remark).trim()
  if (!text) errors.next_followup_remark = '请填写跟进说明'
  const ok = !Object.keys(errors).length
  return { ok, errors, payload: { next_followup_date: date, next_followup_remark: text } }
}

// Prospects sorted by follow-up date ascending; undated items go last. Does not mutate the input.
export function sortProspects(items = []) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const da = a.item.next_followup_date || '', db = b.item.next_followup_date || ''
      if (da && db) return da < db ? -1 : da > db ? 1 : a.index - b.index
      if (da) return -1
      if (db) return 1
      return a.index - b.index
    })
    .map(({ item }) => item)
}

export function threadCard(thread, now = new Date()) {
  const run = thread.run || null
  const draft = run?.draft_message || ''
  return {
    id: thread.id,
    channelLabel: LEAD_CHANNEL_LABELS[thread.channel] || '未知渠道',
    name: thread.display_name || '未知买家',
    hint: thread.company_hint || '',
    status: thread.status,
    lastAt: thread.last_message_at || null,
    clock: localClock(thread.local_timezone, now),
    analysisPending: !run,
    analysisStale: Boolean(thread.analysis_stale),
    summary: run?.one_line_summary || '',
    nextAction: run?.missing_or_next_action || '',
    angle: run?.breakthrough_angle || '',
    urgency: run?.urgency ? { label: URGENCY_LABELS[run.urgency] || run.urgency, level: run.urgency } : null,
    draft,
    draftHint: draft ? '草稿中的占位符需先核对，再发送给客户' : '',
    draftWarning: draft && run?.needs_review ? '含报价/交期，发送前请核对' : '',
    match: thread.match ? { companyId: thread.match.company_id, name: thread.match.name, hint: thread.match.hint || '' } : null,
    followup: thread.status === 'prospect'
      ? { date: thread.next_followup_date || '', remark: thread.next_followup_remark || '' }
      : null,
  }
}

const REVIEW_SECTIONS = [
  { key: 'missed_tasks', title: '遗漏任务', action: 'open', actionLabel: '去处理', text: item => item.title, sub: item => [item.evidence, item.suggested_action].filter(Boolean).join(' · ') },
  { key: 'breakthrough_leads', title: '突破点', action: 'open', actionLabel: '去处理', text: item => item.concern, sub: item => [item.angle, item.draft_hint].filter(Boolean).join(' · ') },
  { key: 'likely_existing_customers', title: '疑似老客', action: 'bind', actionLabel: '确认绑定', text: item => item.why, sub: () => '' },
  { key: 'cleanup_candidates', title: '可清理', action: 'ignore', actionLabel: '不是客户', text: item => item.reason, sub: () => '' },
]

// Four action lists from the latest weekly review. Each row carries thread_id and the action key it maps to.
export function reviewSections(review) {
  if (!review) return []
  return REVIEW_SECTIONS.map(section => ({
    key: section.key,
    title: section.title,
    rows: (review[section.key] || []).map((item, index) => ({
      id: `${section.key}-${index}`,
      threadId: item.thread_id,
      matchedCompanyId: item.matched_company_id ?? null,
      text: section.text(item) || '（无描述）',
      sub: section.sub(item),
      action: section.action,
      actionLabel: section.actionLabel,
    })),
  }))
}

// The newest review is the first item after sorting by week start, so the page never depends on API order.
export function latestReview(items = []) {
  return [...items].sort((a, b) => String(b.week_start_date).localeCompare(String(a.week_start_date)))[0] || null
}

export function sameThread(left, right) {
  return left != null && right != null && String(left) === String(right)
}
