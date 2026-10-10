export function hasActiveShipment(settlements) {
  return settlements.some(row => !['cancelled', 'shipped'].includes(row.state))
}
export function remainingShipmentQuantity(line, settlements) {
  const used = settlements.filter(row => row.state !== 'cancelled').reduce((sum, row) => sum +
    (row.quote?.items || row.items || []).filter(item => String(item.invoice_item_id) === String(line.id))
      .reduce((subtotal, item) => subtotal + Number(item.quantity || 0), 0), 0)
  return Math.max(0, Number(line.quantity || 0) - used)
}

export function canChangeShipment(row, action) {
  if (['cancelled', 'completed', 'shipped', 'outbound_uncertain', 'review_required'].includes(row.state) || row.outbound) return false
  if (['sending', 'verifying', 'uncertain'].includes(row.freight_target?.status)) return false
  if (action === 'cancel') {
    return !row.freight_target?.remote_order_id && row.freight_target?.status !== 'bound' &&
      Number(row.balance?.registered_amount || 0) === 0
  }
  return action === 'pause' ? row.state !== 'paused' : action === 'resume' && row.state === 'paused'
}

export function canReconcileOutbound(row) {
  const target = row.outbound
  if (!target || target.confirmation?.in_progress === true) return false
  return ['pending_remote', 'shipped', 'uncertain', 'verifying', 'confirm_uncertain', 'shipped_unfunded'].includes(target.status) ||
    target.confirmation?.requires_review === true
}
