import { canChangeShipment } from './shipmentSettlementState.js'

export function canRecoverOutbound(row) {
  return canChangeShipment(row, 'recover_outbound') && row.state === 'outbound_uncertain' &&
    row.outbound?.status === 'uncertain' && !row.outbound.remote_id &&
    /^[a-f0-9]{64}$/.test(row.actions.recover_outbound.version || '')
}

export function outboundRecoveryBody(row, requestClosed, reference) {
  const value = typeof reference === 'string' ? reference.trim() : ''
  if (!canRecoverOutbound(row) || requestClosed !== true || value.length < 4 || value.length > 200) return null
  return { version: row.version, recovery_version: row.actions.recover_outbound.version,
    original_request_closed: true, resolution_reference: value,
    reason: `确认原请求已结束且未生成，恢复原出库任务；依据：${value}` }
}

export function isOutboundRecoveryReceipt(row, result) {
  return result?.id === row.id && result.invoice_id === row.invoice_id &&
    Number.isSafeInteger(result.version) && result.version === row.version + 1 &&
    result.state === 'outbound_pending' && result.outbound?.id === row.outbound?.id &&
    result.outbound.number === row.outbound.number && result.outbound.status === 'pending' &&
    !result.outbound.remote_id && result.quote?.quote_hash === row.quote?.quote_hash &&
    result.quote?.goods_amount === row.quote?.goods_amount && result.quote?.freight_amount === row.quote?.freight_amount
}
