/**
 * customer_info.company_id 的 API 契约始终是非空字符串。
 * 兼容部分 MySQL 驱动把纯数字 VARCHAR 返回为 number 的历史情况。
 */
export function normalizeCustomerId(value) {
  if (value === null || value === undefined) return ''
  if (typeof value !== 'string' && typeof value !== 'number') return ''
  if (typeof value === 'number' && !Number.isSafeInteger(value)) return ''
  return String(value).trim()
}

export function formatCustomerOptionLabel(customer) {
  const country = String(customer?.country || '').trim() || '未知国家'
  return `${String(customer?.name || '').trim()} · ${country}`
}
