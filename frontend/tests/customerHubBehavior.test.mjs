import test from 'node:test'
import assert from 'node:assert/strict'
import { createCustomerHubApi } from '../src/api/customerHubContract.js'
import {
  buildAcquisitionProfilePayload,
  buildActionUpdate,
  buildOpportunityUpdate,
  getOpportunityTransitionOptions,
  getRadarOperationOptions,
  getResearchReviewSuccessMessage,
  canReviewResearchDetail,
  canOpenCustomerDetail,
  canRequeueJob,
  mapCustomerProfileSections,
  shouldOpenProfileEditor,
} from '../src/views/customer_hub/customerHubController.js'
import {
  createLatestResource,
  createMutationController,
  createPagedResource,
} from '../src/views/customer_hub/customerHubResources.js'

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

test('API maps params and mutation payloads through injected customer hub client', async () => {
  const calls = []
  const client = {
    get: async (...args) => { calls.push(['get', ...args]); return { data: {} } },
    post: async (...args) => { calls.push(['post', ...args]); return { data: {} } },
    put: async (...args) => { calls.push(['put', ...args]); return { data: {} } },
  }
  const api = createCustomerHubApi(client)
  await api.listCustomers({ page: 2, page_size: 50, keyword: 'ark' })
  await api.getResearchTask(7)
  await api.updateOpportunity(9, { status: 'contacted', reason: 'called' })
  await api.updateAction(11, { operation: 'feedback', feedback: 'not_useful' })
  assert.deepEqual(calls, [
    ['get', '/customers', { params: { page: 2, page_size: 50, keyword: 'ark' }, showLoading: false }],
    ['get', '/research-tasks/7'],
    ['put', '/opportunities/9', { status: 'contacted', reason: 'called' }],
    ['put', '/actions/11', { operation: 'feedback', feedback: 'not_useful' }],
  ])
})

test('research review is gated by the loaded matching detail', () => {
  assert.equal(canReviewResearchDetail({ loading: false, error: null, data: { research_task_id: 7, task_status: 'completed' } }, 7), true)
  assert.equal(canReviewResearchDetail({ loading: false, error: null, data: { research_task_id: 7, task_status: 'completed', content_redacted: true } }, 7), false)
  assert.equal(canReviewResearchDetail({ loading: true, error: null, data: { research_task_id: 7, task_status: 'completed' } }, 7), false)
  assert.equal(canReviewResearchDetail({ loading: false, error: null, data: { research_task_id: 8, task_status: 'completed' } }, 7), false)
  assert.equal(canReviewResearchDetail({ loading: false, error: null, data: { research_task_id: 7, task_status: 'running' } }, 7), false)
})

test('opportunity and radar action payloads follow backend schemas', () => {
  assert.deepEqual(buildOpportunityUpdate({ status: 'contacted', reason: 'called', evidenceFactIds: [2] }), {
    status: 'contacted', reason: 'called', close_reason_code: null, close_reason_text: null,
    linked_order_id: null, evidence_event_ids: [], evidence_fact_ids: [2],
  })
  assert.deepEqual(buildOpportunityUpdate({
    status: 'won', reason: 'order received', closeReasonCode: 'order_confirmed', linkedOrderId: '12',
    evidenceEventIdsText: '4, 5', evidenceFactIdsText: '2, 3',
  }), {
    status: 'won', reason: 'order received', close_reason_code: 'order_confirmed', close_reason_text: null,
    linked_order_id: 12, evidence_event_ids: [4, 5], evidence_fact_ids: [2, 3],
  })
  assert.deepEqual(buildActionUpdate('snooze', { snoozedUntil: '2026-09-01T09:00:00+08:00' }), {
    operation: 'snooze', snoozed_until: '2026-09-01T09:00:00+08:00',
  })
  assert.deepEqual(buildActionUpdate('snooze', { snoozedUntil: '2026-09-01T09:00:00' }), {
    operation: 'snooze', snoozed_until: '2026-09-01T09:00:00+08:00',
  })
  assert.deepEqual(buildActionUpdate('dismiss', { reasonCode: 'user_dismissed', note: 'not relevant' }), {
    operation: 'dismiss', reason_code: 'user_dismissed', note: 'not relevant',
  })
  assert.deepEqual(buildActionUpdate('feedback', { feedback: 'useful', note: '准确' }), { operation: 'feedback', feedback: 'useful', note: '准确' })
  assert.deepEqual(buildActionUpdate('complete', { outcomeCode: 'contacted', feedback: 'not_useful', note: '目标错误' }), {
    operation: 'complete', outcome_code: 'contacted', channel: null, occurred_at: null,
    summary: null, next_step: null, feedback: 'not_useful', note: '目标错误',
  })
  assert.deepEqual(getOpportunityTransitionOptions('pending'), ['contacted', 'dismissed'])
  assert.deepEqual(getOpportunityTransitionOptions('won'), [])
  assert.deepEqual(getRadarOperationOptions('pending'), ['complete', 'snooze', 'dismiss', 'feedback'])
  assert.deepEqual(getRadarOperationOptions('snoozed'), ['feedback'])
  assert.deepEqual(getRadarOperationOptions('done'), ['feedback'])
})

test('paged resource preserves page_result and ignores out-of-order responses', async () => {
  const first = deferred(), second = deferred()
  const queue = [first, second]
  const state = createPagedResource(() => queue.shift().promise)
  const older = state.load({ page: 1, page_size: 20 })
  const newer = state.load({ page: 2, page_size: 20 })
  second.resolve({ data: { items: [{ customer_id: 2 }], total: 21, page: 2, page_size: 20 } })
  await newer
  first.resolve({ data: { items: [{ customer_id: 1 }], total: 21, page: 1, page_size: 20 } })
  await older
  assert.deepEqual(state.items, [{ customer_id: 2 }])
  assert.equal(state.page, 2)
  assert.equal(state.total, 21)
  assert.equal(state.loading, false)
})

test('paged stale guidance retains prior results after latest request fails', async () => {
  let fail = false
  const state = createPagedResource(async () => {
    if (fail) throw new Error('offline')
    return { data: { items: [{ customer_id: 1 }], total: 1, page: 1, page_size: 20 } }
  })
  await state.load({ page: 1, page_size: 20 })
  fail = true
  await state.load({ page: 1, page_size: 20 })
  assert.equal(state.error.message, 'offline')
  assert.match(state.staleGuidance, /数据可能已过期/)
  assert.deepEqual(state.items, [{ customer_id: 1 }])
})

test('latest detail resource separates error retry and stale responses', async () => {
  const a = deferred(), b = deferred()
  const resource = createLatestResource(id => id === 1 ? a.promise : b.promise)
  const old = resource.load(1)
  const current = resource.load(2)
  b.reject(new Error('denied'))
  await current
  assert.equal(resource.error.message, 'denied')
  a.resolve({ data: { customer_id: 1 } })
  await old
  assert.equal(resource.data, null)
  b.resolve = null
})

test('timeline resource ignores a late response for the previously selected customer', async () => {
  const first = deferred(), second = deferred()
  const timeline = createLatestResource(customerId => customerId === 1 ? first.promise : second.promise)
  const old = timeline.load(1)
  const current = timeline.load(2)
  second.resolve({ data: { items: [{ event_id: 22 }] } })
  await current
  first.resolve({ data: { items: [{ event_id: 11 }] } })
  await old
  assert.equal(timeline.key, 2)
  assert.deepEqual(timeline.data.items, [{ event_id: 22 }])
})

test('latest resource retries the same research detail after an error', async () => {
  let attempts = 0
  const resource = createLatestResource(async taskId => {
    attempts += 1
    if (attempts === 1) throw new Error('offline')
    return { data: { research_task_id: taskId, task_status: 'completed' } }
  })
  await resource.load(7)
  assert.equal(resource.error.message, 'offline')
  await resource.retry()
  assert.equal(resource.error, null)
  assert.equal(resource.data.research_task_id, 7)
})

test('mutation controller rejects concurrent research reviews and recovers after errors', async () => {
  const pending = deferred()
  let calls = 0
  const mutation = createMutationController(async value => { calls += 1; if (value === 'fail') throw new Error('denied'); return pending.promise })
  const first = mutation.submit('accepted')
  assert.equal(await mutation.submit('rejected'), false)
  assert.equal(calls, 1)
  pending.resolve({ data: {} })
  assert.equal(await first, true)

  const failed = createMutationController(async () => { throw new Error('denied') })
  assert.equal(await failed.submit('fail'), false)
  assert.equal(failed.loading, false)
  assert.equal(failed.error.message, 'denied')
})

test('research review success messages match each accepted backend state', () => {
  assert.equal(getResearchReviewSuccessMessage('accepted'), '已通过复核')
  assert.equal(getResearchReviewSuccessMessage('revision_requested'), '已要求修订')
  assert.equal(getResearchReviewSuccessMessage('rejected'), '已驳回')
})

test('successful null acquisition profile remains distinct from a load failure', async () => {
  const unconfigured = createLatestResource(async () => ({ data: null }))
  await unconfigured.load('profile')
  assert.equal(unconfigured.data, null)
  assert.equal(unconfigured.error, null)

  const failed = createLatestResource(async () => { throw new Error('offline') })
  await failed.load('profile')
  assert.equal(failed.data, null)
  assert.equal(failed.error.message, 'offline')
})

test('full profile sections map overview and explicit version evidence metadata', () => {
  const profile = {
    identity: { legal_name: 'Ark' }, contacts: [{ name: 'A' }], commercial: { order_summary: { count: 2 } },
    recommended_actions: [{ action: 'call' }], opportunities: [{ title: 'renewal' }], quality: { completeness: 80 },
    preferences: { color: '1B' }, behavior: { cadence: 'monthly' }, risks: [{ type: 'dnc' }],
  }
  const metadata = {
    profile_version_id: 31, version_no: 4, profile_schema_version: 'customer_profile_v1',
    compiled_at: '2026-08-31T18:00:00+08:00', data_as_of: '2026-08-30T12:00:00+08:00',
    section_data_as_of: { identity: '2026-08-30T12:00:00+08:00' }, evidence_fact_ids: [11],
    evidence_refs: [{ fact_id: 11, reference_type: 'customer_fact' }],
  }
  const customer = { profile, profile_metadata: metadata }
  const mapped = mapCustomerProfileSections(customer, [{ event_id: 4, title: 'WhatsApp', summary: 'asked price' }])
  assert.deepEqual(mapped.overview, { identity: profile.identity, business: undefined, engagement: undefined, risks: profile.risks })
  assert.deepEqual(mapped.identity, profile.identity)
  assert.deepEqual(mapped.orders, profile.commercial)
  assert.deepEqual(mapped.actions, profile.recommended_actions)
  assert.deepEqual(mapped.opportunities, profile.opportunities)
  assert.deepEqual(mapped.versionQuality, profile.quality)
  assert.deepEqual(mapped.conversations, [{ event_id: 4, title: 'WhatsApp', summary: 'asked price' }])
  assert.deepEqual(mapped.evidence, { available: true, value: metadata.evidence_refs })
  assert.deepEqual(mapped.profileMetadata, metadata)
})

test('context profile uses the same explicit version metadata contract', () => {
  const context = {
    identity: { legal_name: 'Ark Context' }, business_profile: { industry: 'hair' }, key_contacts: [{ name: 'B' }],
    current_needs: [{ fact_id: 1 }], commercial_summary: { order_count: 3 },
    behavior_patterns: { observed: [{ fact_id: 2 }] }, open_opportunities: [{ id: 9 }],
    recommended_actions: [{ id: 10 }], recent_changes: [{ path: 'identity' }], open_questions: ['confirm:name'],
    data_quality: { completeness: 90 }, evidence_refs: [{ fact_id: 1 }],
  }
  const metadata = { profile_version_id: 8, version_no: 2, evidence_refs: [{ fact_id: 1, reference_type: 'customer_fact' }] }
  const contextMapped = mapCustomerProfileSections({ profile: context, profile_metadata: metadata })
  assert.deepEqual(contextMapped.contacts, context.key_contacts)
  assert.deepEqual(contextMapped.currentNeeds, context.current_needs)
  assert.deepEqual(contextMapped.behaviorPatterns, context.behavior_patterns)
  assert.deepEqual(contextMapped.orders, context.commercial_summary)
  assert.deepEqual(contextMapped.opportunities, context.open_opportunities)
  assert.deepEqual(contextMapped.recentChanges, context.recent_changes)
  assert.deepEqual(contextMapped.openQuestions, context.open_questions)
  assert.deepEqual(contextMapped.versionQuality, context.data_quality)
  assert.deepEqual(contextMapped.evidence, { available: true, value: metadata.evidence_refs })
  assert.deepEqual(contextMapped.profileMetadata, metadata)
})

test('customer detail requires customer feature read and ignores read_all alone', () => {
  assert.equal(canOpenCustomerDetail(['customer:read']), true)
  assert.equal(canOpenCustomerDetail(['customer:read_all']), false)
  assert.equal(canOpenCustomerDetail(['customer_opportunity:read']), false)
})

test('acquisition payload preserves every editable schema field', () => {
  const payload = buildAcquisitionProfilePayload({
    company_name: 'Ark', company_website: 'https://ark.example', products: ['wigs'],
    competitive_advantages: ['speed'], target_countries: ['US'], target_industries: ['salon'],
    target_roles: ['buyer'], exclusions: ['retail'], default_outreach_language: 'en',
    policy_version: 'v2', policy_json: { thresholds: {} },
  })
  assert.deepEqual(payload, {
    company_name: 'Ark', company_website: 'https://ark.example', products: ['wigs'], advantages: ['speed'],
    target_countries: ['US'], target_industries: ['salon'], target_roles: ['buyer'], exclusions: ['retail'],
    default_language: 'en', policy_version: 'v2', policy_json: { thresholds: {} },
  })
})

test('profile editor and requeue guard destructive invalid states', () => {
  assert.equal(shouldOpenProfileEditor({ ok: true, data: null }), true)
  assert.equal(shouldOpenProfileEditor({ ok: true, data: { company_name: 'Ark' } }), true)
  assert.equal(shouldOpenProfileEditor({ ok: false, error: new Error('offline') }), false)
  assert.equal(canRequeueJob({ status: 'failed' }), true)
  assert.equal(canRequeueJob({ status: 'completed' }), false)
  assert.equal(canRequeueJob({ status: 'running' }), false)
})
