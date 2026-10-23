export function hasActiveShipment(settlements) {
  return settlements.some(row => !['cancelled', 'shipped'].includes(row.state))
}
export function remainingShipmentQuantity(line, settlements) {
  const identities = new Set([line.id, ...(line.presale_source_item_ids || [])].map(String))
  const used = settlements.filter(row => row.state !== 'cancelled').reduce((sum, row) => sum +
    (row.quote?.items || row.items || []).filter(item => identities.has(String(item.invoice_item_id)))
      .reduce((subtotal, item) => subtotal + Number(item.quantity || 0), 0), 0)
  return Math.max(0, Number(line.quantity || 0) - used)
}

export function canChangeShipment(row, action) {
  return row.actions?.[action]?.allowed === true
}

export function shipmentActionReason(row, action) {
  return row.actions?.[action]?.reason || (canChangeShipment(row, action) ? '' : '操作条件尚未核实，请刷新原批次')
}

export function isShipmentStateReceipt(row, action, result) {
  const states = { cancel: ['cancelled'], pause: ['paused'], resume: ['awaiting_payment', 'awaiting_verification'] }
  return result?.id === row.id && result.invoice_id === row.invoice_id &&
    Number.isSafeInteger(result.version) && result.version > row.version && states[action]?.includes(result.state) === true
}

export function canReconcileOutbound(row) {
  const target = row.outbound
  if (!target || target.confirmation?.in_progress === true) return false
  return ['pending_remote', 'shipped', 'uncertain', 'verifying', 'confirm_uncertain', 'shipped_unfunded'].includes(target.status) ||
    target.confirmation?.requires_review === true
}
