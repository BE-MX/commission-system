import { createIdempotencyKey } from './customerWorkspaceController.js'

export const ITEM_VIEWS = [
  { value: 'need_me', label: '待我处理', count: 'items_need_me' },
  { value: 'in_progress', label: '推进中', count: 'items_in_progress' },
  { value: 'ended', label: '已结束', count: null },
]
export const ITEM_STATE_LABELS = { open: '待处理', in_progress: '推进中', waiting: '等待', decision_required: '待决策', blocked: '受阻', paused: '已暂停', resolved: '已解决', cancelled: '已终止' }
export const ITEM_OPERATION_LABELS = { start: '开始推进', wait: '等待反馈', decide: '提交决策', block: '登记阻碍', pause: '暂停事项', resume: '恢复事项', cancel: '终止事项', reopen: '重新开启', resolve: '确认解决', revalidate: '复核结果', reverify: '重新核验来源', snooze: '延后提醒', record_delivery_plan: '登记交付方案决定' }
export const FEEDBACK_DIMENSIONS = { accuracy: '事实准确', applicability: '建议适用', adoption: '实际采纳' }
export const DELEGATION_STATE_LABELS = { active: '已授权准备', waiting: '等待输入或定期核验', needs_decision: '等待人工核验', blocked: '需核验后继续', paused: '已暂停', cancelled: '已终止', completed: '已完成' }
export const RUN_STATE_LABELS = { queued: '等待执行器领取', leased: '执行器已领取', running: '准备中', waiting_input: '等待输入', completed: '本轮已交付', failed: '本轮失败', cancelled: '本轮已停止', ambiguous: '本轮结果不确定' }
export const LEGACY_TAB_MAP = { identity: 'profile', governance: 'profile', intelligence: 'profile', relationships: 'conversations', orders: 'overview', monitor: 'profile', maintenance: 'maintenance', workbench: 'overview', mailOutreach: 'conversations' }
export function normalizeWorkspaceTab(tab) { return ['overview', 'conversations', 'profile', 'maintenance'].includes(tab) ? tab : LEGACY_TAB_MAP[tab] || 'overview' }
function requireValue(value, message) { if (value == null || value === '') throw new Error(message); return value }
export function availableItemOperations(item) { return item?.can_operate && Array.isArray(item.allowed_operations) ? item.allowed_operations.filter(value => ITEM_OPERATION_LABELS[value]) : [] }
export function buildItemTransition(item, operation, form = {}) {
  if (!availableItemOperations(item).includes(operation)) throw new Error('当前事项不允许该操作，请刷新状态')
  const payload = { operation, expected_item_version: requireValue(item.row_version, '缺少事项版本，请刷新') }
  requireValue(form.reason?.trim(), '请填写本次操作的原因或结果依据')
  if (form.reason?.trim()) payload.reason = form.reason.trim()
  if (['resolve', 'revalidate', 'reverify', 'reopen', 'record_delivery_plan'].includes(operation)) {
    if (!form.evidence_refs?.length || form.evidence_refs.some(ref => !ref.type || ref.id == null || ref.revision == null)) throw new Error('请选择有明确来源和版本的有效证据')
    payload.evidence_refs = form.evidence_refs
  }
  if (['wait', 'block', 'snooze', 'record_delivery_plan'].includes(operation)) payload.review_at = requireValue(form.review_at, '请选择北京时间的再核验时间')
  if (operation === 'record_delivery_plan') {
    payload.delivery_decision = requireValue(form.delivery_decision, '请选择交付方案决定')
    payload.delivery_plan = requireValue(form.delivery_plan?.trim(), '请说明已决定的交付方案')
  }
  if (['resolve', 'revalidate'].includes(operation) && form.cancel_remaining === true) payload.cancel_remaining = true
  if (item.goal_type === 'delivery_exception' && ['resolve', 'revalidate'].includes(operation)) {
    payload.customer_decision = requireValue(form.customer_decision, '请明确客户是否接受了对应方案')
    if (payload.customer_decision !== 'accepted') throw new Error('客户未接受或仍未确认方案，不能登记解决')
  }
  if (operation === 'wait') { payload.waiting_kind = requireValue(form.waiting_kind, '请选择等待对象'); payload.resume_condition = requireValue(form.resume_condition?.trim(), '请填写继续推进的条件') }
  if (operation === 'pause') payload.resume_condition = requireValue(form.resume_condition?.trim(), '请填写恢复条件')
  return payload
}
export function buildVersionedActionUpdate(action, payload) {
  if (!action.work_item_id) return payload
  if (payload.operation === 'complete') { requireValue(payload.next_step?.trim(), '事项尚未解决，请填写下一次推进或内部核验'); requireValue(payload.next_step_due_at, '请填写下次核验的未来期限') }
  const result = { ...payload, expected_action_version: requireValue(action.row_version, '缺少行动版本，请刷新'), expected_work_item_version: requireValue(action.work_item_version, '缺少事项版本，请刷新') }
  if (action.occurrence_id != null) result.expected_occurrence_version = requireValue(action.occurrence_version, '缺少维护实例版本，请刷新')
  return result
}
/** Failed attempts reuse the key; changing any payload field creates a new operation. */
export function createSubmissionIdentity(scope, generate = createIdempotencyKey) {
  let fingerprint, key
  return { forPayload(payload) { const next = JSON.stringify(payload); if (next !== fingerprint) { fingerprint = next; key = generate(scope) } return key }, reset() { fingerprint = undefined; key = undefined } }
}
export function evidenceReference(row) { const ref = row?.evidence_ref; return row?.selectable && ref?.type && ref.id != null && ref.revision != null ? { ...ref } : null }
export function errorMessage(error) { return error?.response?.status === 409 ? `${error?.response?.data?.message || '数据已更新'}；输入已保留，请刷新状态后重新确认。` : error?.response?.data?.message || error?.message || '操作未确认，请刷新核对后重试。' }
