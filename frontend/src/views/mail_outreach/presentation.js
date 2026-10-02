import { statusDictionary, statusLabels, statusTypes, resolveStatus } from '../../utils/status.js'
/**
 * 邮件触达域的展示映射（中文硬编码，无 i18n）。
 * 状态文案与设计文档 §4 状态机对齐；未知状态保留代码并明确显示未知，不吞数据。
 */

export const JOB_STATUS = statusDictionary([
  ['scheduled', '已排程', 'primary'],
  ['claimed', '已认领', 'warning'],
  ['sending', '发送中', 'warning'],
  ['provider_accepted', '通道已接受', 'success'],
  ['failed_safe', '失败(未发送)', 'danger'],
  ['ambiguous', '结果未知待核对', 'danger'],
  ['blocked', '已阻断', 'danger'],
  ['needs_review', '待复核', 'warning'],
  ['cancelled', '已撤销', 'info'],
])
export const JOB_STATUS_LABELS = statusLabels(JOB_STATUS)

const JOB_STATUS_TAG_TYPES = statusTypes(JOB_STATUS)

export function jobStatusLabel(status) {
  return resolveStatus(status, JOB_STATUS).label
}

export function jobStatusTagType(status) {
  return resolveStatus(status, JOB_STATUS).type
}

export const DRAFT_STATUS = statusDictionary([
  ['draft', '草稿', 'info'],
  ['approved', '已批准', 'success'],
  ['rejected', '已拒绝', 'danger'],
  ['cancelled', '已撤销', 'info'],
  ['completed', '已完成', 'success'],
])
export const DRAFT_STATUS_LABELS = statusLabels(DRAFT_STATUS)

const DRAFT_STATUS_TAG_TYPES = statusTypes(DRAFT_STATUS)

export function draftStatusLabel(status) {
  return resolveStatus(status, DRAFT_STATUS).label
}

export function draftStatusTagType(status) {
  return resolveStatus(status, DRAFT_STATUS).type
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

const VERIFICATION_STATUS = statusDictionary([
  ['valid', '已验证', 'success'],
  ['unknown', '未知', 'info'],
  ['risky', '有风险', 'warning'],
  ['invalid', '无效', 'danger'],
])
const VERIFICATION_STATUS_LABELS = statusLabels(VERIFICATION_STATUS)

const VERIFICATION_STATUS_TAG_TYPES = statusTypes(VERIFICATION_STATUS)

export function verificationStatusLabel(value) {
  return resolveStatus(value, VERIFICATION_STATUS).label
}

export function verificationStatusTagType(value) {
  return resolveStatus(value, VERIFICATION_STATUS).type
}

const MAILBOX_AUTH_STATUS = statusDictionary([
  ['active', '授权有效', 'success'],
  ['expired', '授权过期', 'danger'],
  ['unbound', '未绑定', 'warning'],
  ['unknown', '未知', 'info'],
])
const MAILBOX_AUTH_STATUS_LABELS = statusLabels(MAILBOX_AUTH_STATUS)

const MAILBOX_AUTH_STATUS_TAG_TYPES = statusTypes(MAILBOX_AUTH_STATUS)

export function mailboxAuthStatusLabel(value) {
  return resolveStatus(value, MAILBOX_AUTH_STATUS).label
}

export function mailboxAuthStatusTagType(value) {
  return resolveStatus(value, MAILBOX_AUTH_STATUS).type
}

/** 邮箱是否可选作发件账号：停用或已暂停（pause_reason 非空）均不可选 */
export function isMailboxSelectable(mailbox) {
  return mailbox?.status === 'active' && mailbox?.auth_status === 'active' && !mailbox?.pause_reason
}

export const BLOCKING_RISK_CODES = ['generation_not_ready', 'eligibility_missing', 'unfilled_placeholder', 'unapproved_commercial_promise', 'claim_dropped', 'claim_evidence_dropped', 'model_risk_flag']
export function isBlockingRisk(flag) {
  return flag?.blocking === true || BLOCKING_RISK_CODES.includes(typeof flag === 'string' ? flag : flag?.code)
}
export const RECIPIENT_MISSING_LABELS = {
  timezone: '补充联系人时区', language: '补充写作语言', email_verification: '核实邮箱并填写验证依据',
  contactability: '确认可联系依据', suppression: '已退订或禁止联系，不能发送',
}
export const EVENT_CLASSIFICATION_LABELS = {
  human_reply: '人工回复', auto_reply: '自动回复', bounce: '退信', opt_out: '退订', other: '其他',
}
