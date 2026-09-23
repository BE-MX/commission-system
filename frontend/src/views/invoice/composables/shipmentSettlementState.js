export function hasActiveShipment(settlements) {
  return settlements.some(row => !['cancelled', 'shipped'].includes(row.state))
}
export function remainingShipmentQuantity(line, settlements) {
  const used = settlements.filter(row => row.state !== 'cancelled').reduce((sum, row) => sum +
    (row.quote?.items || row.items || []).filter(item => String(item.invoice_item_id) === String(line.id))
      .reduce((subtotal, item) => subtotal + Number(item.quantity || 0), 0), 0)
  return Math.max(0, Number(line.quantity || 0) - used)
}
