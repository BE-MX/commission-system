/**
 * PCW 客户工作区纯逻辑与 API 契约行为测试（node --test）。
 * 对齐 docs/requirements/private-customer-workbench-prototype/api-contracts.md。
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  ORDER_ANALYTICS_DIMENSIONS,
  ORDER_ANALYTICS_MEASURES,
  PROFILE_FIELD_LABELS,
  PROFILE_FIELD_WHITELIST,
  REORDER_CONFIDENCE_LABELS,
  SAMPLE_STAGE_FLOW,
  WORKSPACE_TABS,
  buildBindingPayload,
  buildEventDecisionPayload,
  buildPlanPayload,
  buildProfileRevisionPayload,
  buildSampleCasePayload,
  buildSuggestionDecisionPayload,
  buildSubscriptionPayload,
  errorCodeOf,
  groupCalendarByDate,
  isVersionConflict,
  mapOrderAnalyticsBuckets,
  mapReorderWindow,
  mapWorkbenchOverview,
  profileFieldValueType,
  sampleCaseOperations,
} from '../src/views/customer_hub/customerWorkspaceController.js'
import { createCustomerHubApi, withIdempotency } from '../src/api/customerHubContract.js'

test('WORKSPACE_TABS 覆盖六类能力', () => {
  assert.equal(WORKSPACE_TABS.length, 6)
  assert.deepEqual(WORKSPACE_TABS.map(tab => tab.key), [
    'overview', 'profile', 'conversations', 'orders', 'monitor', 'maintenance',
  ])
})

test('mapWorkbenchOverview 四张指标卡与扫描/水位分离', () => {
  const mapped = mapWorkbenchOverview({
    customer_scope: 'primary',
    customers_total: 120,
    pending_actions: 19,
    affected_customers: 11,
    overdue_actions: 3,
    reorder_window_customers: 5,
    scans: {
      expected: 120, rule_completed: 116, rule_failed: 4,
      ai_completed: 28, ai_skipped_unchanged: 84, ai_failed: 4,
    },
    watermarks: [
      { source: 'whatsapp', status: 'stale', synced_through: '2026-09-22T18:00:00+08:00', gap_count: 2 },
    ],
    generated_at: '2026-09-24T09:00:00+08:00',
  })
  assert.equal(mapped.cards.length, 4)
  assert.equal(mapped.cards[0].value, 120)
  assert.equal(mapped.cards[2].value, 3)
  assert.equal(mapped.scansRows.length, 2)
  assert.equal(mapped.scansRows[1].skipped, 84)
  assert.equal(mapped.watermarks[0].status, 'stale')
  // 无扫描数据时显示"今日尚未评估"而不是零
  assert.equal(mapWorkbenchOverview({}).scans, null)
})

test('档案修订 payload 校验：版本前置与值类型', () => {
  assert.ok(PROFILE_FIELD_WHITELIST.includes('preference.expressed.color'))
  assert.equal(profileFieldValueType('preference.expressed.quantity'), 'number')
  const payload = buildProfileRevisionPayload(
    { field_key: 'preference.expressed.color', value: '#1B', reason: '客户确认' },
    { expected_profile_version_id: 93, expected_profile_input_seq: 18 },
  )
  assert.equal(payload.expected_profile_version_id, 93)
  assert.equal(payload.value_type, 'string')
  assert.throws(
    () => buildProfileRevisionPayload(
      { field_key: 'preference.expressed.color', value: '#1B', reason: '' },
      { expected_profile_version_id: 93, expected_profile_input_seq: 18 },
    ),
  )
  assert.throws(
    () => buildProfileRevisionPayload(
      { field_key: 'identity.legal_name', value: 'X', reason: '治理字段' },
      { expected_profile_version_id: 93, expected_profile_input_seq: 18 },
    ),
  )
})

test('建议决定：reject 必填原因、defer 必填日期、采纳带双档案版本', () => {
  assert.throws(() => buildSuggestionDecisionPayload('reject', { expected_suggestion_version: 2, reason: '' }, { expected_suggestion_version: 2 }))
  assert.throws(() => buildSuggestionDecisionPayload('defer', {}, { expected_suggestion_version: 2 }))
  const accepted = buildSuggestionDecisionPayload('accept', {}, {
    expected_suggestion_version: 2,
    expected_profile_version_id: 93,
    expected_profile_input_seq: 18,
  })
  assert.equal(accepted.expected_suggestion_version, 2)
  assert.equal(accepted.expected_profile_version_id, 93)
  const edited = buildSuggestionDecisionPayload('edit_accept', { value: '#1B' }, {
    expected_suggestion_version: 2,
    expected_profile_version_id: 93,
    expected_profile_input_seq: 18,
  })
  assert.equal(edited.value, '#1B')
})

test('绑定 payload：expected_binding_version=0 表示首次绑定', () => {
  const payload = buildBindingPayload({
    source_system: 'whatsapp',
    source_account_key: 'account-8',
    source_conversation_id: 'conv-42',
    customer_id: 21,
    evidence_refs: [{ type: 'verified_contact_point', id: 88 }],
    share_scope: 'customer_team',
  })
  assert.equal(payload.expected_binding_version, 0)
  assert.throws(() => buildBindingPayload({
    source_system: 'whatsapp', source_account_key: 'a', source_conversation_id: 'c',
    customer_id: 21, evidence_refs: [],
  }))
})

test('监控订阅 payload 仅允许 https（真正校验在服务端）', () => {
  const payload = buildSubscriptionPayload({ channel: 'website', url: 'https://customer.example/news', interval_days: 7 })
  assert.equal(payload.interval_days, 7)
  assert.throws(() => buildSubscriptionPayload({ channel: 'website', url: 'http://customer.example' }))
  const decision = buildEventDecisionPayload('ignore', { expected_event_version: 2, reason: '重复宣传' })
  assert.equal(decision.operation, 'ignore')
  assert.throws(() => buildEventDecisionPayload('ignore', { expected_event_version: 2, reason: '' }))
})

test('维护计划六类 payload 组装（2·29 策略、样本互斥、节日确认）', () => {
  const manual = buildPlanPayload('manual', {
    title: '回访', scheduled_at: '2026-10-01T09:00:00', purpose: 'review', channel: 'whatsapp',
  })
  assert.equal(manual.plan_type, 'manual')
  assert.throws(() => buildPlanPayload('birthday', {
    title: 'x', contact_id: 1, month: 2, day: 29, local_contact_time: '10:00', leap_day_policy: 'guess',
  }))
  assert.throws(() => buildPlanPayload('holiday', {
    title: 'x', holiday_code: 'EID', calendar_region: 'SA',
    occurrence_local_date: '2026-03-20', local_contact_time: '10:00', applicability_confirmed: false,
  }))
  assert.throws(() => buildPlanPayload('sample', {
    title: 'x', sample_case_id: 1, purpose: 'p',
    test_planned_date: '2026-10-01', feedback_due_at: '2026-10-05',
  }))
})

test('样品阶段矩阵与可用操作推导', () => {
  assert.deepEqual(sampleCaseOperations('ordered'), [])
  assert.ok(sampleCaseOperations('awaiting_test').includes('reschedule'))
  assert.ok(sampleCaseOperations('awaiting_test').includes('start_test'))
  assert.ok(sampleCaseOperations('testing').includes('record_feedback'))
  assert.ok(sampleCaseOperations('feedback_received').includes('close'))
  assert.deepEqual(sampleCaseOperations('closed'), [])
  const payload = buildSampleCasePayload('reschedule', {
    test_planned_date: '2026-09-29',
    reason: '客户未测试',
  }, {
    expected_sample_version: 3,
    expected_occurrence_version: 2,
    expected_action_version: 4,
  })
  assert.equal(payload.operation, 'reschedule')
  assert.equal(payload.test_planned_date, '2026-09-29')
  assert.equal(SAMPLE_STAGE_FLOW[0], 'ordered')
  assert.equal(SAMPLE_STAGE_FLOW.at(-1), 'closed')
})

test('订单结构分桶：币种/单位不混加，覆盖率读服务端分母', () => {
  const mapped = mapOrderAnalyticsBuckets({
    metric_version: 'order_analytics_v1',
    amount_basis: 'original_currency',
    eligible_order_count: 10,
    included_count: 8,
    unknown_count: 2,
    excluded_reasons: { cancelled: 1 },
    buckets: [
      { key: '1B', value: '100.00', currency: 'USD' },
      { key: '1B', value: '50.00', currency: 'EUR' },
      { key: '20inch', value: '300', unit: 'pcs' },
      { key: null, value: '1', share_percent: 10 },
    ],
  })
  assert.equal(mapped.groups.length, 4) // USD / EUR / pcs / plain（覆盖率桶）
  assert.equal(mapped.eligibleOrderCount, 10)
  assert.equal(ORDER_ANALYTICS_DIMENSIONS[0].value, 'product_family')
  assert.equal(ORDER_ANALYTICS_MEASURES[2].value, 'order_coverage')
})

test('复购窗口映射：irregular 降级提示', () => {
  const regular = mapReorderWindow({
    id: 1, product_family: 'hair_bundle', median_interval_days: 30,
    window_from: '2026-10-01', window_to: '2026-10-15', confidence: 'regular', state: 'open',
  })
  assert.equal(regular.degraded, false)
  const irregular = mapReorderWindow({ id: 2, confidence: 'irregular' })
  assert.equal(irregular.degraded, true)
  assert.ok(REEORDER_LABEL_OK(irregular.confidenceLabel))
  function REEORDER_LABEL_OK(label) {
    return label === REORDER_CONFIDENCE_LABELS.irregular
  }
})

test('日历按业务日分组排序', () => {
  const groups = groupCalendarByDate([
    { occurrence_date: '2026-10-02', id: 2 },
    { occurrence_date: '2026-10-01', id: 1 },
    { occurrence_date: '2026-10-01', id: 3 },
  ])
  assert.equal(groups.length, 2)
  assert.equal(groups[0].date, '2026-10-01')
  assert.equal(groups[0].items.length, 2)
})

test('版本冲突识别', () => {
  assert.equal(isVersionConflict({ response: { status: 409, data: { data: { error_code: 'ACTION_VERSION_CONFLICT' } } } }), true)
  assert.equal(isVersionConflict({ response: { status: 400, data: { data: { error_code: 'bad_request' } } } }), false)
  assert.equal(errorCodeOf({ response: { data: { data: { error_code: 'PREVIEW_STALE' } } } }), 'PREVIEW_STALE')
})

test('API 契约：方法/路径/幂等头', () => {
  const calls = []
  const client = {
    get: (path, config) => { calls.push(['get', path, config]); return Promise.resolve({ data: {} }) },
    post: (path, payload, config) => { calls.push(['post', path, payload, config]); return Promise.resolve({ data: {} }) },
    patch: (path, payload, config) => { calls.push(['patch', path, payload, config]); return Promise.resolve({ data: {} }) },
    put: (path, payload) => { calls.push(['put', path, payload]); return Promise.resolve({ data: {} }) },
  }
  const api = createCustomerHubApi(client)
  api.getWorkbenchOverview({ customer_scope: 'primary' })
  api.createProfileRevision(21, { field_key: 'x' }, 'key-0001')
  api.createAnalysisJob(42, 'key-0002')
  api.patchMonitorSubscription(7, { enabled: false }, 'key-0003')
  api.createCampaignActions(3, { preview_version: 'hash', customer_ids: [1] }, 'key-0004')
  api.rescheduleOccurrence(9, { occurrence_id: 9, occurrence_date: '2026-10-01' }, 'key-0005')
  assert.deepEqual(calls.map(item => [item[0], item[1]]), [
    ['get', '/workbench/overview'],
    ['post', '/customers/21/profile-revisions'],
    ['post', '/conversations/42/analysis-jobs'],
    ['patch', '/monitor-subscriptions/7'],
    ['post', '/campaigns/3/actions'],
    ['patch', '/maintenance-plans/9'],
  ])
  for (const call of calls.slice(1)) {
    assert.equal(call.at(-1).headers['Idempotency-Key'].startsWith('key-'), true)
  }
  const headers = withIdempotency({ headers: { 'X-A': '1' } }, 'k')
  assert.equal(headers.headers['X-A'], '1')
  assert.equal(headers.headers['Idempotency-Key'], 'k')
})

test('PROFILE_FIELD_LABELS 覆盖白名单全部字段', () => {
  for (const key of PROFILE_FIELD_WHITELIST) {
    assert.ok(PROFILE_FIELD_LABELS[key])
  }
})
