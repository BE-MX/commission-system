export function mapCustomerProfileSections(customer = {}, timeline = []) {
  const profile = customer.profile || {}
  const metadata = customer.profile_metadata || null
  const evidence = customer.profile_projection === 'customer_profile_v1'
    ? metadata?.evidence_refs ?? null
    : customer.profile_projection === 'customer_context_v1'
      ? profile.evidence_refs ?? null
      : null
  const business = profile.business_profile ?? profile.business
  const contacts = profile.key_contacts ?? profile.contacts?.items ?? profile.contacts
  const commercial = profile.commercial_summary ?? profile.commercial
  const behavior = profile.behavior_patterns ?? profile.behavior
  const opportunities = profile.open_opportunities ?? profile.opportunities?.open ?? profile.opportunities
  const quality = profile.data_quality ?? profile.quality
  return {
    overview: { identity: profile.identity, business, engagement: profile.engagement, risks: profile.risks },
    identity: profile.identity,
    contacts,
    currentNeeds: profile.current_needs ?? profile.engagement?.current_needs ?? business?.current_needs,
    preferences: profile.preferences,
    behaviorPatterns: behavior,
    conversations: timeline.map(event => Object.fromEntries(
      ['event_id', 'event_type', 'title', 'summary', 'occurred_at']
        .filter(key => event[key] !== undefined)
        .map(key => [key, event[key]]),
    )),
    orders: commercial,
    evidence: evidence == null ? { available: false, message: '该档案版本未提供证据引用' } : { available: true, value: evidence },
    opportunities,
    actions: profile.recommended_actions,
    risks: profile.risks,
    recentChanges: profile.recent_changes ?? profile.engagement?.recent_changes,
    openQuestions: profile.open_questions ?? quality?.open_questions,
    annotations: profile.annotations,
    versionQuality: quality,
    profileMetadata: metadata,
  }
}

export const canOpenCustomerDetail = permissions => permissions.includes('customer:read')
export const canReviewResearchDetail = (resource, taskId) => !resource.loading && !resource.error
  && resource.data?.research_task_id === taskId && resource.data?.task_status === 'completed'
  && resource.data?.content_redacted !== true
export const canRequeueJob = job => job?.status === 'failed'
export const isEmptyCompletedSearchJob = job => job?.status === 'completed' && Number(job?.result_count ?? 0) === 0
export function getSearchJobFeedback(job) {
  if (job?.error_message) return { text: job.error_message, tone: 'danger' }
  if (isEmptyCompletedSearchJob(job)) return { text: '任务完成但未产出候选客户，请检查执行端或调整后重新创建任务', tone: 'danger' }
  return { text: `已去重 ${job?.deduplicated_count ?? 0} 条`, tone: 'normal' }
}
const SEARCH_RESULT_STATUS_LABELS = { active: '待跟进', ignored: '已忽略', qualified: '审核通过', rejected: '已驳回' }
export const searchResultStatusLabel = status => SEARCH_RESULT_STATUS_LABELS[status] || status || '未知'
export const shouldPollSearchJobs = jobs => jobs.some(job => ['pending', 'running'].includes(job?.status))
export const shouldOpenProfileEditor = result => result?.ok === true
export const getResearchReviewSuccessMessage = status => ({
  accepted: '已通过复核',
  revision_requested: '已要求修订',
  rejected: '已驳回',
})[status]

const OPPORTUNITY_TRANSITIONS = {
  pending: ['contacted', 'dismissed'],
  contacted: ['replied', 'lost', 'dismissed'],
  replied: ['quoted', 'lost', 'dismissed'],
  quoted: ['won', 'lost', 'dismissed'],
  lost: ['pending'],
  dismissed: ['pending'],
}

const OPPORTUNITY_CLOSE_REASONS = {
  won: ['order_confirmed', 'manual_confirmed'],
  lost: ['no_response', 'price', 'product_mismatch', 'timing', 'competitor', 'budget', 'risk_rejected', 'other'],
  dismissed: ['duplicate', 'not_qualified', 'wrong_customer', 'no_opportunity', 'dnc', 'other'],
}

export const getOpportunityTransitionOptions = status => OPPORTUNITY_TRANSITIONS[status] || []
export const getOpportunityCloseReasonOptions = status => OPPORTUNITY_CLOSE_REASONS[status] || []

export function getRadarOperationOptions(status) {
  if (status === 'pending') return ['complete', 'snooze', 'dismiss', 'feedback']
  if (status === 'snoozed') return ['feedback']
  if (['done', 'dismissed', 'cancelled'].includes(status)) return ['feedback']
  return []
}

function parseIdList(value) {
  if (Array.isArray(value)) return value.map(Number).filter(item => Number.isInteger(item) && item > 0)
  return String(value || '').split(',').map(item => item.trim()).filter(item => /^\d+$/.test(item)).map(Number).filter(item => item > 0)
}

export function getInvalidIdTokens(value) {
  if (Array.isArray(value)) return value.map(String).filter(item => !/^[1-9]\d*$/.test(item))
  return String(value || '').split(',').map(item => item.trim()).filter(item => item && !/^[1-9]\d*$/.test(item))
}

export function getTimelineLimitNotice(visibleCount, total) {
  return visibleCount > 0 && total > visibleCount ? `当前展示最近 ${visibleCount} / ${total} 条记录` : ''
}

function beijingDateTime(value) {
  if (!value) return null
  const text = String(value).trim().replace(' ', 'T')
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}+08:00`
}

export function buildOpportunityUpdate(form) {
  return {
    status: form.status,
    reason: form.reason,
    close_reason_code: form.closeReasonCode || null,
    close_reason_text: form.closeReasonText || null,
    linked_order_id: form.linkedOrderId ? Number(form.linkedOrderId) : null,
    evidence_event_ids: parseIdList(form.evidenceEventIdsText ?? form.evidenceEventIds),
    evidence_fact_ids: parseIdList(form.evidenceFactIdsText ?? form.evidenceFactIds),
  }
}

export function buildActionUpdate(operation, form = {}) {
  if (operation === 'snooze') return { operation, snoozed_until: beijingDateTime(form.snoozedUntil) }
  if (operation === 'dismiss') return { operation, reason_code: form.reasonCode || 'user_dismissed', note: form.note || null }
  if (operation === 'feedback') return { operation, feedback: form.feedback, note: form.note || null }
  return {
    operation: 'complete', outcome_code: form.outcomeCode || 'other', channel: form.channel || null,
    occurred_at: beijingDateTime(form.occurredAt), summary: form.summary || null, next_step: form.nextStep || null,
    feedback: form.feedback || null, note: form.note || null,
  }
}

export function buildAcquisitionProfilePayload(form) {
  return {
    company_name: form.company_name,
    company_website: form.company_website || null,
    products: form.products || [],
    advantages: form.competitive_advantages || [],
    target_countries: form.target_countries || [],
    target_industries: form.target_industries || [],
    target_roles: form.target_roles || [],
    exclusions: form.exclusions || [],
    default_language: form.default_outreach_language || 'en',
    policy_version: form.policy_version,
    policy_json: form.policy_json || {},
  }
}

export function createSearchJobIdempotencyKey(cryptoApi = globalThis.crypto) {
  const bytes = new Uint8Array(32)
  cryptoApi.getRandomValues(bytes)
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}

export function createSearchJobDraft(keyFactory = createSearchJobIdempotencyKey) {
  return { name: '', target_count: 20, countries: '', idempotency_key: keyFactory() }
}

export function buildSearchJobPayload(job) {
  return {
    name: job.name,
    target_count: job.target_count,
    adapter: 'agent',
    criteria_json: { countries: String(job.countries || '').split(',').map(item => item.trim()).filter(Boolean) },
    idempotency_key: job.idempotency_key,
  }
}

export function createSearchJobPollingController({
  shouldPoll,
  refresh,
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
  delay = 10000,
}) {
  let timer = null
  let running = false
  let disposed = false

  function cancelTimer() {
    if (timer !== null) clearTimer(timer)
    timer = null
  }

  function sync() {
    if (disposed) return
    if (!shouldPoll()) {
      cancelTimer()
      return
    }
    if (running || timer !== null) return
    timer = setTimer(run, delay)
  }

  async function run() {
    timer = null
    if (disposed || !shouldPoll()) return
    running = true
    try {
      await refresh()
    } catch {
      // The list resource owns user-visible stale/error guidance.
    } finally {
      running = false
      sync()
    }
  }

  function dispose() {
    disposed = true
    cancelTimer()
  }

  return { sync, dispose }
}
