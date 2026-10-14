/** Rates are fractions of the order amount (0.03 = 3%), never pool weights. */
export function formatCommissionRate(rate) {
  return `${Math.round(Number(rate) * 10000) / 100}%`
}

export function commissionSummary(allocations = [], empty = '未配置提成分配') {
  if (!allocations.length) return empty
  const people = allocations.map(row => `${row.user_name || '未命名业务员'} ${formatCommissionRate(row.rate)}`).join(' · ')
  const total = allocations.reduce((sum, row) => sum + Math.round(Number(row.rate) * 10000), 0) / 10000
  return `${people}（合计 ${formatCommissionRate(total)}）`
}

export function expectedCommission(allocations = []) {
  return allocations.map(({ user_id, rate }) => ({ user_id, rate }))
}

export function retainSelectedCustomer(items, selected) {
  return selected && !items.some(row => row.id === selected.id) ? [selected, ...items] : items
}
