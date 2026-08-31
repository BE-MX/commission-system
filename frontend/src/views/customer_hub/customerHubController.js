export function createPagedResource(fetcher) {
  let requestId = 0
  return {
    items: [], total: 0, page: 1, pageSize: 20, loading: false, error: null, staleGuidance: '',
    async load(params) {
      const current = ++requestId
      this.loading = true
      this.error = null
      try {
        const response = await fetcher(params)
        if (current !== requestId) return
        const data = response?.data || {}
        this.items = data.items || []
        this.total = data.total ?? this.items.length
        this.page = data.page ?? params.page
        this.pageSize = data.page_size ?? params.page_size
        this.staleGuidance = ''
      } catch (error) {
        if (current !== requestId) return
        this.error = error
        this.staleGuidance = this.items.length ? '当前保留上次成功结果，数据可能已过期。' : ''
      } finally {
        if (current === requestId) this.loading = false
      }
    },
  }
}

export function createLatestResource(fetcher) {
  let requestId = 0
  return {
    data: null, loading: false, error: null, key: null,
    async load(key) {
      const current = ++requestId
      this.key = key
      this.data = null
      this.error = null
      this.loading = true
      try {
        const response = await fetcher(key)
        if (current === requestId) this.data = response?.data ?? null
      } catch (error) {
        if (current === requestId) this.error = error
      } finally {
        if (current === requestId) this.loading = false
      }
      return this.data
    },
    retry() { return this.load(this.key) },
    invalidate() { requestId += 1; this.loading = false },
  }
}

export function mapCustomerProfileSections(profile = {}, timeline = []) {
  const evidence = profile.evidence_refs ?? profile.facts ?? null
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
  }
}

export const canOpenCustomerDetail = permissions => permissions.includes('customer:read')
export const canReviewResearchDetail = (resource, taskId) => !resource.loading && !resource.error
  && resource.data?.research_task_id === taskId && resource.data?.task_status === 'completed'
export const canRequeueJob = job => job?.status === 'failed'
export const shouldOpenProfileEditor = profile => Boolean(profile?.data ?? profile)

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
  if (status === 'snoozed') return ['complete', 'feedback']
  if (['done', 'dismissed', 'cancelled'].includes(status)) return ['feedback']
  return []
}

function parseIdList(value) {
  if (Array.isArray(value)) return value.map(Number).filter(item => Number.isInteger(item) && item > 0)
  return String(value || '').split(',').map(item => item.trim()).filter(item => /^\d+$/.test(item)).map(Number).filter(item => item > 0)
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
