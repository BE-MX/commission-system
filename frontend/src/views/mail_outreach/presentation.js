/**
 * 邮件触达域的展示映射（中文硬编码，无 i18n）。
 * 状态文案与设计文档 §4 状态机对齐；未知状态一律回退展示原始值，不吞数据。
 */

export const JOB_STATUS_LABELS = {
  scheduled: '已排程',
  claimed: '已认领',
  sending: '发送中',
  provider_accepted: '通道已接受',
  failed_safe: '失败(未发送)',
  ambiguous: '结果未知待核对',
  blocked: '已阻断',
  needs_review: '待复核',
  cancelled: '已撤销',
}

const JOB_STATUS_TAG_TYPES = {
  scheduled: 'primary',
  claimed: 'warning',
  sending: 'warning',
  provider_accepted: 'success',
  failed_safe: 'danger',
  ambiguous: 'danger',
  blocked: 'danger',
  needs_review: 'warning',
  cancelled: 'info',
}

export function jobStatusLabel(status) {
  return JOB_STATUS_LABELS[status] || status || '未知'
}

export function jobStatusTagType(status) {
  return JOB_STATUS_TAG_TYPES[status] || 'info'
}

export const DRAFT_STATUS_LABELS = {
  draft: '草稿',
  approved: '已批准',
  rejected: '已拒绝',
  cancelled: '已撤销',
  completed: '已完成',
}

const DRAFT_STATUS_TAG_TYPES = {
  draft: 'info',
  approved: 'success',
  rejected: 'danger',
  cancelled: 'info',
  completed: 'success',
}

export function draftStatusLabel(status) {
  return DRAFT_STATUS_LABELS[status] || status || '未知'
}

export function draftStatusTagType(status) {
  return DRAFT_STATUS_TAG_TYPES[status] || 'info'
}

export const RELATIONSHIP_GOAL_OPTIONS = [
  { value: 'first_intro', label: '首次引介' },
  { value: 'follow_up', label: '续接' },
  { value: 'reactivation', label: '唤醒' },
]

export function relationshipGoalLabel(value) {
  return RELATIONSHIP_GOAL_OPTIONS.find(option => option.value === value)?.label || value || '未指定'
}

export const LANGUAGE_SOURCE_LABELS = {
  recipient: '收件人偏好',
  company: '公司默认',
  country: '国家/地区推断',
}

export function languageSourceLabel(value) {
  return LANGUAGE_SOURCE_LABELS[value] || value || '未提供'
}

const VERIFICATION_STATUS_LABELS = {
  valid: '已验证',
  unknown: '未知',
  risky: '有风险',
  invalid: '无效',
}

const VERIFICATION_STATUS_TAG_TYPES = {
  valid: 'success',
  unknown: 'info',
  risky: 'warning',
  invalid: 'danger',
}

export function verificationStatusLabel(value) {
  return VERIFICATION_STATUS_LABELS[value] || value || '未知'
}

export function verificationStatusTagType(value) {
  return VERIFICATION_STATUS_TAG_TYPES[value] || 'info'
}

const MAILBOX_AUTH_STATUS_LABELS = {
  active: '授权有效',
  expired: '授权过期',
  unbound: '未绑定',
  unknown: '未知',
}

const MAILBOX_AUTH_STATUS_TAG_TYPES = {
  active: 'success',
  expired: 'danger',
  unbound: 'warning',
  unknown: 'info',
}

export function mailboxAuthStatusLabel(value) {
  return MAILBOX_AUTH_STATUS_LABELS[value] || value || '未知'
}

export function mailboxAuthStatusTagType(value) {
  return MAILBOX_AUTH_STATUS_TAG_TYPES[value] || 'info'
}

/** 邮箱是否可选作发件账号：停用或已暂停（pause_reason 非空）均不可选 */
export function isMailboxSelectable(mailbox) {
  return mailbox?.status !== 'disabled' && !mailbox?.pause_reason
}
