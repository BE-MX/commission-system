/** Numeric IDs are only meaningful together with their server-declared source. */
export function localShipmentIdentity(row) {
  if (row?.record_source !== 'local_shipment' || (row.transaction_route && row.transaction_route !== 'local')) return null
  if (!Number.isInteger(Number(row.id)) || Number(row.id) <= 0) return null
  return { source: 'local_shipment', id: Number(row.id), key: `local_shipment:${row.id}` }
}
export function localShipmentCan(row, action) {
  if (!localShipmentIdentity(row) || row.capabilities?.[action] !== true) return false
  if (action === 'ship') return row.state === 'ready' && row.inspection_current === true
  return true
}
