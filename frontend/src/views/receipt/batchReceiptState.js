// Decimal input is converted before summation; binary float totals never decide payment equality.
export function cents(value) {
  const match = String(value ?? '').match(/^(\d+)(?:\.(\d{1,2}))?$/)
  if (!match) return null
  const result = Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0'))
  return Number.isSafeInteger(result) ? result : null
}
export function validateAllocations(rows, amount) {
  const total = cents(amount)
  if (!rows.length || total == null || total <= 0) return '请选择订单并填写有效回款总金额'
  const first = rows[0]
  if (!first.customer_id || !first.currency || rows.some(row => row.customer_id !== first.customer_id || row.currency !== first.currency)) return '一次回款只能选择同一客户、同一币种的订单'
  if (new Set(rows.map(row => row.id)).size !== rows.length) return '订单不能重复分配'
  let sum = 0
  for (const row of rows) {
    const allocated = cents(row.amount), remaining = cents(row.balance?.remaining_amount)
    if (allocated == null || allocated <= 0 || remaining == null || allocated > remaining || row.balance?.version == null) return '每笔分配须大于 0 且不超过已核验余额'
    sum += allocated
  }
  return sum === total ? '' : '分配金额合计必须与本次回款总金额完全一致'
}
export function latestRequest() {
  let sequence = 0
  return { next: () => ++sequence, isCurrent: value => value === sequence }
}
