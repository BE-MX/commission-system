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
    const pool = ['presale_deposit', 'presale_advance'].includes(row.purpose)
    const balance = !pool && row.balance?.active_settlement ? row.balance.active_settlement : row.balance
    const allocated = cents(row.amount), remaining = cents(balance?.remaining_amount), charge = cents(row.bank_charge || 0)
    const order = row.invoice_no || '所选订单'
    if (pool && row.balance?.active_settlement && row.balance.active_settlement.funding_version !== 2) return '存在旧版未完成发货结算，请选择本批补款'
    if (allocated == null || allocated <= 0) return `${order}：分配金额须大于 0，且最多保留两位小数`
    if (balance?.version == null || (!pool && remaining == null)) return `${order}：余额尚未核验，请刷新该订单后重试`
    if (pool && (row.balance?.funding_mode !== 'presale_pool' || charge == null || charge >= allocated)) return '预售收款须核验原单，手续费须小于分配金额'
    if (!pool && remaining === 0) return `${order}：${row.balance?.active_settlement ? '本批可补款' : '可登记'}余额为 0，请核对已登记回款或预付款抵扣${row.balance?.active_settlement?.funding_version === 2 ? '；新增到账请另选预付货款用途' : ''}`
    if (!pool && allocated > remaining) return `${order}：分配金额超过已核验余额，请刷新并核对本次用途和金额`
    if (actualChargeForRow(row) && (charge == null || charge >= allocated
      || (!pool && charge > cents(balance.charge_remaining)))) return '实际银行手续费须小于分配金额，且不超过本批可用手续费额度'
    sum += allocated
  }
  return sum === total ? '' : '分配金额合计必须与本次回款总金额完全一致'
}
export function purposeForBalance(balance, selected = '') {
  if (balance?.funding_mode !== 'presale_pool') return 'ordinary'
  const active = balance.active_settlement
  if (active && active.funding_version !== 2) return 'ordinary'
  if (['presale_advance', 'presale_deposit'].includes(selected)) return selected
  if (active && (selected === 'ordinary' || cents(active.remaining_amount) > 0)) return 'ordinary'
  return 'presale_advance'
}
export function actualChargeForRow(row) {
  return ['presale_deposit', 'presale_advance'].includes(row.purpose)
    || row.balance?.active_settlement?.funding_version === 2
}
export function allocationForRow(row) {
  const pool = ['presale_deposit', 'presale_advance'].includes(row.purpose)
  const balance = !pool && row.balance?.active_settlement ? row.balance.active_settlement : row.balance
  return { invoice_id: row.id, settlement_id: pool ? null : balance.settlement_id || null,
    amount: String(row.amount), balance_version: balance.version, purpose: row.purpose || 'ordinary',
    bank_charge: actualChargeForRow(row) ? String(row.bank_charge || 0) : '0' }
}
export function latestRequest() {
  let sequence = 0
  return { next: () => ++sequence, isCurrent: value => value === sequence }
}
