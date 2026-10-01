import { formatMoney } from '../../utils/money.js'
/**
 * 提成管理域呈现格式化（纯函数，Node 可直接测试）。
 * 批次状态/角色/金额/比例的展示口径在这里统一，四个提成页面共用。
 */

/** 美元金额：1234.5 → $1,234.50 */
export function usd(value) {
  return formatMoney(value, { currency: 'USD', currencyDisplay: 'narrowSymbol' })
}

/** 美元金额（可缺省）：null/undefined → '-'，与“真 0”区分（管理端明细未计算字段） */
export function usdOrDash(value) {
  if (value === null || value === undefined || value === '') return '-'
  return usd(value)
}

/** 人民币金额：1234.5 → ¥1,234.50 */
export function cny(value) {
  return formatMoney(value, { currency: 'CNY', currencyDisplay: 'narrowSymbol' })
}

/** 月平均汇率：7.12345 → 7.123450 */
export function exchangeRate(value) {
  return Number(value || 0).toFixed(6)
}

/** 提成比例：0.0525 → 5.25%；未配置比例（null/undefined）显示 -，与 0% 区分 */
export function commissionRate(value) {
  if (value === null || value === undefined || value === '') return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

/** 批次状态 → el-tag type（calculated 沿用历史渲染为 info） */
export function batchStatusType(status) {
  return { draft: 'info', calculated: 'info', confirming: 'warning', confirmed: 'success', voided: 'danger' }[status] || 'info'
}

export function batchStatusLabel(status) {
  return { draft: '草稿', calculated: '已计算', confirming: '确认中', confirmed: '已确认', voided: '已作废' }[status] || status
}

export function confirmationStatusType(status) {
  return { not_required: 'info', not_started: 'info', partial_confirmed: 'warning', all_confirmed: 'success' }[status] || 'info'
}

export function confirmationStatusLabel(status) {
  return { not_required: '无需确认', not_started: '未开始', partial_confirmed: '部分确认', all_confirmed: '全部确认' }[status] || status
}

/** 确认进度百分比：无应确认人数时为 0，封顶 100 */
export function confirmPercent(row) {
  const expected = Number(row?.expected_confirm_count || 0)
  if (!expected) return 0
  return Math.min(Math.round((Number(row?.confirmed_count || 0) / expected) * 100), 100)
}

export function periodLabel(periodType) {
  return { monthly: '月度', quarterly: '季度', semi_annual: '半年', annual: '年度' }[periodType] || periodType
}

export function roleLabel(role) {
  return {
    salesperson: '业务员',
    supervisor: '一级主管',
    second_supervisor: '二级主管',
  }[role] || role
}
