/**
 * 私海客户工作台（PCW-01..06）纯逻辑控制器。
 * 无 Vue 依赖，行为由 frontend/tests/customerWorkspace.test.mjs 覆盖。
 * 字段与版本契约见 docs/requirements/private-customer-workbench-prototype/api-contracts.md 第 6 节。
 */

function fail(code, message) {
  const error = new Error(message)
  error.code = code
  throw error
}

// ── 页签与权限声明 ─────────────────────────────────────────
export const WORKSPACE_TABS = [
  { key: 'overview', label: '概览', permission: 'customer:read' },
  { key: 'profile', label: '档案与建议', permission: 'customer:read' },
  { key: 'conversations', label: '沟通与询盘', permission: 'customer:read' },
  { key: 'orders', label: '订单与复购', permission: 'customer:read' },
  { key: 'monitor', label: '渠道监控', permission: 'customer:read' },
  { key: 'maintenance', label: '维护计划', permission: 'customer:read' },
]

// ── PCW-01 概览 ────────────────────────────────────────────
const CUSTOMER_SCOPE_HINTS = { primary: '我主负责', collaborator: '我协作', authorized: '授权可见' }
export const WATERMARK_STATUS_LABELS = { fresh: '已同步', stale: '有缺口' }

const count = value => (value == null || Number.isNaN(Number(value)) ? 0 : Number(value))

export function mapWorkbenchOverview(data) {
  if (!data || typeof data !== 'object') {
    return { cards: [], scans: null, scansRows: [], watermarks: [], generatedAt: null }
  }
  const cards = [
    {
      key: 'customers', label: '范围内客户', value: count(data.customers_total),
      hint: CUSTOMER_SCOPE_HINTS[data.customer_scope] || '当前范围', toView: 'all',
    },
    {
      key: 'pending', label: '待办任务', value: count(data.pending_actions),
      hint: `涉及 ${count(data.affected_customers)} 位客户`, toView: 'focus',
    },
    {
      key: 'overdue', label: '原期限已逾期', value: count(data.overdue_actions ?? data.overdue),
      hint: '延后提醒仍保留期限风险', toView: 'overdue',
    },
    {
      key: 'reorder', label: '复购窗口客户', value: count(data.reorder_window_customers ?? data.reorder_customers),
      hint: '基于商业订单 · 非库存预测', toView: 'high_priority',
    },
  ]
  const scans = data.scans && typeof data.scans === 'object' ? data.scans : null
  // 规则扫描与 AI 分析分开呈现：失败不互相掩盖，AI 未变更跳过不是完成
  const scansRows = scans
    ? [
        { key: 'rule', label: '规则评估', expected: scans.expected ?? null, completed: scans.rule_completed ?? null, failed: scans.rule_failed ?? null },
        { key: 'ai', label: 'AI 增量分析', expected: scans.expected ?? null, completed: scans.ai_completed ?? null, skipped: scans.ai_skipped_unchanged ?? null, failed: scans.ai_failed ?? null },
      ]
    : []
  const watermarks = (Array.isArray(data.watermarks) ? data.watermarks : []).map(item => ({
    source: item.source || '未知来源',
    status: item.status || 'stale',
    syncedThrough: item.synced_through ?? null,
    gapCount: item.gap_count ?? 0,
  }))
  return { cards, scans, scansRows, watermarks, generatedAt: data.generated_at ?? null }
}

// ── PCW-02 档案修订与建议 ──────────────────────────────────
export const PROFILE_FIELD_LABELS = {
  'preference.expressed.color': '颜色偏好',
  'preference.expressed.product_family': '产品族偏好',
  'preference.expressed.model': '型号偏好',
  'preference.expressed.length': '长度偏好',
  'preference.expressed.delivery_window': '交期偏好',
  'preference.expressed.quantity': '数量需求',
  'preference.expressed.price_range': '价格区间',
  'profile.business_type': '业务类型',
}
export const PROFILE_FIELD_WHITELIST = Object.keys(PROFILE_FIELD_LABELS)
const PROFILE_FIELD_VALUE_TYPES = {
  'preference.expressed.quantity': 'number',
  'preference.expressed.price_range': 'object',
}
export const profileFieldValueType = fieldKey => PROFILE_FIELD_VALUE_TYPES[fieldKey] || 'string'

const hasValue = value => {
  if (value == null) return false
  if (typeof value === 'string') return value.trim() !== ''
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}
const hasText = value => typeof value === 'string' && value.trim() !== ''

export function buildProfileRevisionPayload(form = {}, versions = {}) {
  const fieldKey = form.fieldKey ?? form.field_key
  if (!PROFILE_FIELD_WHITELIST.includes(fieldKey)) {
    fail('FIELD_NOT_ALLOWED', '该字段不在可修订白名单内；身份、归属与联系限制请走治理流程')
  }
  if (!hasValue(form.value)) fail('VALUE_REQUIRED', '请填写新值')
  if (!hasText(form.reason)) fail('REASON_REQUIRED', '请填写修订依据')
  const expectedVersionId = versions.expectedProfileVersionId ?? versions.expected_profile_version_id
  const expectedInputSeq = versions.expectedProfileInputSeq ?? versions.expected_profile_input_seq
  if (expectedVersionId == null || expectedInputSeq == null) {
    fail('VERSION_REQUIRED', '缺少档案版本，请刷新档案后重试')
  }
  const payload = {
    expected_profile_version_id: expectedVersionId,
    expected_profile_input_seq: expectedInputSeq,
    field_key: fieldKey,
    value_type: profileFieldValueType(fieldKey),
    value: form.value,
    reason: form.reason.trim(),
    evidence_refs: Array.isArray(form.evidenceRefs ?? form.evidence_refs) ? (form.evidenceRefs ?? form.evidence_refs) : [],
  }
  const targetFactId = form.targetFactId ?? form.target_fact_id
  if (targetFactId != null) payload.target_fact_id = targetFactId
  return payload
}

export const SUGGESTION_DECISIONS = ['accept', 'edit_accept', 'reject', 'defer']
export const SUGGESTION_DECISION_LABELS = { accept: '采纳', edit_accept: '编辑采纳', reject: '驳回', defer: '稍后处理' }

export function buildSuggestionDecisionPayload(operation, form = {}, versions = {}) {
  if (!SUGGESTION_DECISIONS.includes(operation)) fail('OPERATION_UNSUPPORTED', `不支持的建议操作：${operation}`)
  const expectedSuggestionVersion = versions.expectedSuggestionVersion ?? versions.expected_suggestion_version
  if (expectedSuggestionVersion == null) fail('VERSION_REQUIRED', '缺少建议版本，请刷新后重试')
  const payload = { operation, expected_suggestion_version: expectedSuggestionVersion }
  if (operation === 'reject') {
    if (!hasText(form.reason)) fail('REASON_REQUIRED', '驳回必须填写原因')
    payload.reason = form.reason.trim()
  }
  if (operation === 'defer') {
    if (!hasText(form.deferUntil ?? form.defer_until)) fail('DEFER_UNTIL_REQUIRED', '稍后处理必须选择再提醒日期')
    payload.defer_until = form.deferUntil ?? form.defer_until
    if (hasText(form.reason)) payload.reason = form.reason.trim()
  }
  if (operation === 'accept' || operation === 'edit_accept') {
    const expectedVersionId = versions.expectedProfileVersionId ?? versions.expected_profile_version_id
    const expectedInputSeq = versions.expectedProfileInputSeq ?? versions.expected_profile_input_seq
    if (expectedVersionId == null || expectedInputSeq == null) fail('VERSION_REQUIRED', '缺少档案版本，请刷新档案后重试')
    payload.expected_profile_version_id = expectedVersionId
    payload.expected_profile_input_seq = expectedInputSeq
    if (operation === 'edit_accept') {
      if (!hasValue(form.value)) fail('VALUE_REQUIRED', '编辑采纳必须填写确认后的值')
      payload.value = form.value
    }
    if (hasText(form.reason)) payload.reason = form.reason.trim()
  }
  return payload
}

// ── PCW-03 会话绑定 ────────────────────────────────────────
export function buildBindingPayload(form = {}) {
  for (const [key, label] of [
    ['source_system', '来源系统'], ['source_account_key', '来源账号'], ['source_conversation_id', '源会话'],
  ]) {
    if (!hasText(form[key])) fail('VALUE_REQUIRED', `缺少${label}标识`)
  }
  if (form.customer_id == null && form.customerId == null) fail('VALUE_REQUIRED', '请选择候选客户')
  const contactId = form.contact_id ?? form.contactId
  const evidence = Array.isArray(form.evidence_refs ?? form.evidenceRefs) ? (form.evidence_refs ?? form.evidenceRefs) : []
  // 明确联系人依据：contact_id 或至少一条证据引用（群聊场景靠证据说明参与者）
  if (contactId == null && evidence.length === 0) {
    fail('VALUE_REQUIRED', '绑定需要明确的联系人依据')
  }
  return {
    source_system: form.source_system,
    source_account_key: form.source_account_key,
    source_conversation_id: form.source_conversation_id,
    customer_id: form.customer_id ?? form.customerId,
    contact_id: contactId ?? null,
    expected_binding_version: form.expected_binding_version ?? form.expectedBindingVersion ?? 0,
    evidence_refs: evidence,
    share_scope: form.share_scope ?? form.shareScope ?? 'customer_team',
  }
}

// ── PCW-05 监控订阅与事件 ──────────────────────────────────
export const MONITOR_COLLECTION_STATUS_LABELS = {
  baseline: '待建基线', active: '最近采集成功', failed: '采集失败', restricted: '源权限受限',
}
export const MONITOR_EVENT_STATUS_LABELS = { pending: '待确认', confirmed: '已确认', ignored: '已忽略' }

export function buildSubscriptionPayload(form = {}) {
  if (!hasText(form.channel)) fail('VALUE_REQUIRED', '请选择监控渠道')
  let parsed
  try {
    parsed = new URL(String(form.url || ''))
  } catch {
    fail('URL_INVALID', '请填写完整的公开 HTTPS 地址')
  }
  // 前端仅预检 https 协议；DNS/IP/重定向/内网等真实校验在服务端（URL_NOT_ALLOWED 原样展示）
  if (parsed.protocol !== 'https:') fail('URL_INVALID', '仅支持 https 网址，服务端会做完整安全校验')
  const intervalDays = Number(form.interval_days ?? form.intervalDays)
  if (!Number.isInteger(intervalDays) || intervalDays <= 0) fail('VALUE_REQUIRED', '采集频率需为正整数天数')
  return { channel: form.channel, url: parsed.href, interval_days: intervalDays }
}

export const EVENT_DECISIONS = ['confirm', 'ignore']
export function buildEventDecisionPayload(operation, form = {}) {
  if (!EVENT_DECISIONS.includes(operation)) fail('OPERATION_UNSUPPORTED', `不支持的事件操作：${operation}`)
  const expectedEventVersion = form.expected_event_version ?? form.expectedEventVersion
  if (expectedEventVersion == null) fail('VERSION_REQUIRED', '缺少事件版本，请刷新后重试')
  if (operation === 'ignore' && !hasText(form.reason)) fail('REASON_REQUIRED', '忽略事件必须保留原因')
  const payload = { operation, expected_event_version: expectedEventVersion }
  if (hasText(form.reason)) payload.reason = form.reason.trim()
  return payload
}

// ── PCW-06 维护计划（六类 typed_payload）────────────────────
export const MAINTENANCE_PLAN_TYPES = ['manual', 'birthday', 'holiday', 'campaign', 'shipping', 'sample']
export const MAINTENANCE_PLAN_TYPE_LABELS = {
  manual: '日常联系', birthday: '生日', holiday: '节日', campaign: '活动', shipping: '物流', sample: '样品',
}

export function buildPlanPayload(planType, form = {}) {
  if (!MAINTENANCE_PLAN_TYPES.includes(planType)) fail('PLAN_TYPE_UNSUPPORTED', `不支持的维护计划类型：${planType}`)
  if (!hasText(form.title)) fail('VALUE_REQUIRED', '请填写计划名称')
  let typed
  if (planType === 'manual') {
    if (!hasText(form.scheduled_at ?? form.scheduledAt)) fail('VALUE_REQUIRED', '请填写计划时间')
    typed = {
      scheduled_at: form.scheduled_at ?? form.scheduledAt,
      purpose: form.purpose || '',
      channel: form.channel || 'whatsapp',
    }
  } else if (planType === 'birthday') {
    const month = Number(form.month)
    const day = Number(form.day)
    if (form.contact_id == null && form.contactId == null) fail('VALUE_REQUIRED', '生日计划需要明确联系人')
    if (!Number.isInteger(month) || month < 1 || month > 12 || !Number.isInteger(day) || day < 1 || day > 31) {
      fail('VALUE_REQUIRED', '请填写合法的生日月日')
    }
    // 2/29 默认不猜策略，交业务确认（开发规格 PCW-06）；仅接受显式三选一
    const leapPolicy = form.leap_day_policy ?? form.leapDayPolicy
    if (month === 2 && day === 29 && !['skip', 'feb28', 'mar1'].includes(leapPolicy)) {
      fail('LEAP_DAY_POLICY_REQUIRED', '2 月 29 日生日需明确闰日策略（跳过/按 2-28/按 3-1）')
    }
    typed = {
      contact_id: form.contact_id ?? form.contactId,
      month, day,
      local_contact_time: form.local_contact_time ?? form.localContactTime ?? null,
      leap_day_policy: form.leap_day_policy ?? form.leapDayPolicy ?? null,
    }
  } else if (planType === 'holiday') {
    if (!hasText(form.holiday_code ?? form.holidayCode)) fail('VALUE_REQUIRED', '请选择节日')
    if (!hasText(form.occurrence_local_date ?? form.occurrenceLocalDate)) fail('VALUE_REQUIRED', '请填写本次发生日期')
    if ((form.applicability_confirmed ?? form.applicabilityConfirmed) !== true) {
      fail('APPLICABILITY_NOT_CONFIRMED', '节日计划需确认客户适用依据')
    }
    typed = {
      holiday_code: form.holiday_code ?? form.holidayCode,
      calendar_region: form.calendar_region ?? form.calendarRegion ?? '',
      occurrence_local_date: form.occurrence_local_date ?? form.occurrenceLocalDate,
      local_contact_time: form.local_contact_time ?? form.localContactTime ?? null,
      applicability_confirmed: true,
    }
  } else if (planType === 'campaign') {
    if (form.campaign_id == null && form.campaignId == null) fail('VALUE_REQUIRED', '请选择活动')
    typed = {
      campaign_id: form.campaign_id ?? form.campaignId,
      campaign_version: form.campaign_version ?? form.campaignVersion ?? null,
      audience_decision_ref: form.audience_decision_ref ?? form.audienceDecisionRef ?? null,
    }
  } else if (planType === 'shipping') {
    const linkIds = form.shipment_order_link_ids ?? form.shipmentOrderLinkIds
    if (!Array.isArray(linkIds) || linkIds.length === 0) fail('VALUE_REQUIRED', '物流计划需要显式订单/运单关联')
    if (!hasText(form.shipment_event_id ?? form.shipmentEventId)) fail('VALUE_REQUIRED', '缺少物流事件标识')
    typed = {
      shipment_order_link_ids: linkIds,
      trigger_event_type: form.trigger_event_type ?? form.triggerEventType ?? 'delivered',
      shipment_event_id: form.shipment_event_id ?? form.shipmentEventId,
      contact_channel: form.contact_channel ?? form.contactChannel ?? 'whatsapp',
    }
  } else {
    if (form.sample_case_id == null && form.sampleCaseId == null) fail('VALUE_REQUIRED', '样品计划需要关联样品事项')
    const testPlanned = form.test_planned_date ?? form.testPlannedDate
    const feedbackDue = form.feedback_due_at ?? form.feedbackDueAt
    // 测试计划日与反馈期限阶段互斥（schema 第 6 节）
    if (hasText(testPlanned) && hasText(feedbackDue)) fail('SAMPLE_DATES_EXCLUSIVE', '测试日期与反馈期限二选一，不能同时填写')
    if (!hasText(testPlanned) && !hasText(feedbackDue)) fail('SAMPLE_DATE_REQUIRED', '请填写测试日期或反馈期限')
    typed = {
      sample_case_id: form.sample_case_id ?? form.sampleCaseId,
      purpose: form.purpose || 'feedback',
      ...(hasText(testPlanned) ? { test_planned_date: testPlanned } : { feedback_due_at: feedbackDue }),
    }
  }
  return {
    plan_type: planType,
    title: form.title.trim(),
    timezone: form.timezone || 'Asia/Shanghai',
    evidence_refs: Array.isArray(form.evidence_refs ?? form.evidenceRefs) ? (form.evidence_refs ?? form.evidenceRefs) : [],
    typed_payload: typed,
  }
}

// ── 样品事项阶段与可用操作 ─────────────────────────────────
export const SAMPLE_STAGE_FLOW = ['ordered', 'shipped', 'delivered', 'awaiting_test', 'testing', 'feedback_received', 'closed']
export const SAMPLE_STAGE_LABELS = {
  ordered: '已下单', shipped: '已发货', delivered: '已签收', awaiting_test: '待测试',
  testing: '测试中', feedback_received: '已收反馈', closed: '已关闭',
}
export const SAMPLE_OPERATION_LABELS = { reschedule: '改约', start_test: '开始测试', record_feedback: '登记反馈', close: '关闭' }
// 发出/签收由物流事实推进，界面不提供入口；签收不自动开始测试
const SAMPLE_STAGE_OPERATIONS = {
  ordered: [],
  shipped: [],
  delivered: ['reschedule', 'close'],
  awaiting_test: ['reschedule', 'start_test', 'close'],
  testing: ['record_feedback', 'close'],
  feedback_received: ['close'],
  closed: [],
}
export const sampleCaseOperations = stage => [...(SAMPLE_STAGE_OPERATIONS[stage] || [])]

export function buildSampleCasePayload(operation, form = {}, versions = {}) {
  if (!SAMPLE_OPERATION_LABELS[operation]) fail('OPERATION_UNSUPPORTED', `不支持的样品操作：${operation}`)
  const sampleVersion = versions.expectedSampleVersion ?? versions.expected_sample_version
  if (sampleVersion == null) fail('VERSION_REQUIRED', '缺少样品事项版本，请刷新后重试')
  const payload = { operation, expected_sample_version: sampleVersion }
  if (operation === 'reschedule') {
    // 改约与样品事项/实例/当前行动版本原子校验（契约 4.5）
    const occurrenceVersion = versions.expectedOccurrenceVersion ?? versions.expected_occurrence_version
    const actionVersion = versions.expectedActionVersion ?? versions.expected_action_version
    if (occurrenceVersion == null || actionVersion == null) fail('VERSION_REQUIRED', '缺少实例或行动版本，请刷新后重试')
    if (!hasText(form.test_planned_date ?? form.testPlannedDate)) fail('VALUE_REQUIRED', '请选择新的测试日期')
    if (!hasText(form.reason)) fail('REASON_REQUIRED', '改约必须填写原因')
    payload.expected_occurrence_version = occurrenceVersion
    payload.expected_action_version = actionVersion
    payload.test_planned_date = form.test_planned_date ?? form.testPlannedDate
    payload.reason = form.reason.trim()
  }
  if (operation === 'start_test') {
    if (!hasText(form.actual_date ?? form.actualDate)) fail('VALUE_REQUIRED', '请填写实际测试日期')
    const evidence = form.evidence_message_ids ?? form.evidenceMessageIds
    if (!Array.isArray(evidence) || evidence.length === 0) fail('EVIDENCE_REQUIRED', '开始测试需要客户明确证据')
    payload.actual_date = form.actual_date ?? form.actualDate
    payload.evidence_message_ids = evidence
  }
  if (operation === 'record_feedback') {
    if (!hasText(form.feedback)) fail('VALUE_REQUIRED', '请填写反馈内容')
    if (!hasText(form.feedback_date ?? form.feedbackDate)) fail('VALUE_REQUIRED', '请填写反馈日期')
    payload.feedback = form.feedback.trim()
    payload.feedback_date = form.feedback_date ?? form.feedbackDate
    if (hasText(form.reason)) payload.reason = form.reason.trim()
  }
  if (operation === 'close') {
    if (!hasText(form.reason)) fail('REASON_REQUIRED', '关闭需要已获反馈或明确取消依据')
    payload.reason = form.reason.trim()
  }
  return payload
}

// ── PCW-04 订单分析与复购 ──────────────────────────────────
export const ORDER_ANALYTICS_DIMENSIONS = [
  { value: 'product_family', label: '产品族' },
  { value: 'model', label: '产品型号' },
  { value: 'color', label: '颜色' },
  { value: 'length', label: '长度' },
]
export const ORDER_ANALYTICS_MEASURES = [
  { value: 'amount', label: '原币金额' },
  { value: 'quantity', label: '同单位数量' },
  { value: 'order_coverage', label: '订单覆盖率' },
]

export function mapOrderAnalyticsBuckets(response = {}) {
  const buckets = Array.isArray(response.buckets) ? response.buckets : []
  const rows = buckets.map(bucket => ({
    key: bucket.key ?? null,
    label: bucket.label ?? bucket.key ?? '（未知）',
    value: bucket.value ?? null,
    currency: bucket.currency ?? null,
    unit: bucket.unit ?? null,
    orderCount: bucket.order_count ?? null,
    // 百分比分母来自服务端，前端不另算口径
    sharePercent: bucket.share_percent ?? null,
  }))
  // 金额按币种、数量按单位分桶，互不混加；无币种/单位（如订单覆盖率）归入 plain
  const groups = []
  for (const row of rows) {
    const groupKey = row.currency ? `currency:${row.currency}` : row.unit ? `unit:${row.unit}` : 'plain'
    let group = groups.find(item => item.key === groupKey)
    if (!group) {
      group = { key: groupKey, currency: row.currency, unit: row.unit, rows: [] }
      groups.push(group)
    }
    group.rows.push(row)
  }
  return {
    rows,
    groups,
    metricVersion: response.metric_version ?? null,
    eligibleOrderCount: response.eligible_order_count ?? 0,
    includedCount: response.included_count ?? 0,
    unknownCount: response.unknown_count ?? 0,
    excludedReasons: Array.isArray(response.excluded_reasons) ? response.excluded_reasons : [],
    coverage: response.coverage ?? null,
    amountBasis: response.amount_basis ?? null,
    quantityUnit: response.quantity_unit ?? null,
  }
}

export const REORDER_CONFIDENCE_LABELS = {
  regular: '周期观察可用', irregular: '仅供参考待核验', insufficient: '样本不足',
}

export function mapReorderWindow(window = {}) {
  const confidence = window.confidence ?? window.status ?? 'insufficient'
  return {
    id: window.window_id ?? window.id ?? null,
    productFamily: window.product_family ?? window.family ?? '—',
    medianIntervalDays: window.median_interval_days ?? window.median_days ?? null,
    windowFrom: window.window_from ?? null,
    windowTo: window.window_to ?? null,
    sampleCount: window.sample_count ?? window.batch_count ?? null,
    metricVersion: window.metric_version ?? null,
    confidence,
    confidenceLabel: REORDER_CONFIDENCE_LABELS[confidence] ?? confidence,
    degraded: confidence !== 'regular',
    state: window.state ?? 'open',
    actionId: window.action_id ?? null,
  }
}

// ── 活动 ──────────────────────────────────────────────────
export function buildCampaignActionsPayload(form = {}) {
  if (!hasText(form.preview_version ?? form.previewVersion)) fail('VERSION_REQUIRED', '缺少预览版本，请重新预览')
  const customerIds = form.customer_ids ?? form.customerIds
  if (!Array.isArray(customerIds) || customerIds.length === 0) fail('VALUE_REQUIRED', '请至少选择一位客户')
  return { preview_version: form.preview_version ?? form.previewVersion, customer_ids: customerIds }
}

// ── 维护日历分组 ───────────────────────────────────────────
export function groupCalendarByDate(items = []) {
  const groups = new Map()
  for (const item of Array.isArray(items) ? items : []) {
    const date = item.business_date ?? item.date ?? item.occurrence_date ?? null
    if (!groups.has(date)) groups.set(date, [])
    groups.get(date).push(item)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === null ? 1 : b === null ? -1 : a < b ? -1 : a > b ? 1 : 0))
    .map(([date, groupItems]) => ({ date, items: groupItems }))
}

// ── 错误识别 ───────────────────────────────────────────────
export function errorCodeOf(error) {
  const data = error?.response?.data
  const detail = data?.detail
  return data?.data?.error_code
    ?? data?.error_code
    ?? (detail && typeof detail === 'object' ? detail.error_code ?? detail.code ?? null : null)
    ?? error?.error_code
    ?? null
}

export function isVersionConflict(error) {
  if ((error?.response?.status ?? error?.status) === 409) return true
  const code = errorCodeOf(error)
  return typeof code === 'string' && code.endsWith('_CONFLICT')
}

export function isNotFoundOrForbidden(error) {
  if ((error?.response?.status ?? error?.status) === 404) return true
  return errorCodeOf(error) === 'CUSTOMER_NOT_FOUND_OR_FORBIDDEN'
}

export const VERSION_CONFLICT_MESSAGE = '数据已更新，请刷新后重试'
export const CUSTOMER_FORBIDDEN_MESSAGE = '客户不存在或你没有访问权限'

/** 幂等键：pcw-<scope>-<32hex>，同一表单的重复提交复用同一键，新表单重新生成。 */
export function createIdempotencyKey(scope, cryptoApi = globalThis.crypto) {
  const bytes = new Uint8Array(16)
  cryptoApi.getRandomValues(bytes)
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return `pcw-${scope}-${hex}`
}
