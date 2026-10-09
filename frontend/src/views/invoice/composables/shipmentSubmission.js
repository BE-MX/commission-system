// One unresolved original shipment per actor and tab; no credentials or display metadata.
export const shipmentSubmissionKey = actor => `ark_shipment_pending_v1:${actor}`
export const copyShipment = value => JSON.parse(JSON.stringify(value))
const positiveId = value => Number.isSafeInteger(value) && value > 0
const money = value => typeof value === 'string' && /^\d{1,12}(?:\.\d{1,2})?$/.test(value)
function valid(record, actor) {
  const body = record?.body, payment = body?.payment
  return record?.actor === actor && positiveId(record?.invoice_id)
    && /^[a-zA-Z0-9_-]{16,64}$/.test(body?.request_key || '') && /^[a-f0-9]{64}$/.test(body?.quote_hash || '')
    && money(body?.freight_amount) && Array.isArray(body?.items) && body.items.length > 0 && body.items.length <= 200
    && body.items.every(row => positiveId(row.invoice_item_id) && positiveId(row.quantity))
    && new Set(body.items.map(row => row.invoice_item_id)).size === body.items.length
    && (!payment || (money(payment.amount) && Number(payment.amount) > 0 && money(payment.bank_charge)
      && typeof payment.collection_date === 'string' && typeof payment.payment_type === 'string' && payment.payment_type
      && Array.isArray(payment.attachment_ids) && payment.attachment_ids.length > 0 && payment.attachment_ids.every(id => typeof id === 'string' && id)))
}
export function readShipmentSubmission(storage, actor) {
  if (!positiveId(actor)) throw new Error('请先重新确认当前登录账号')
  const value = storage.getItem(shipmentSubmissionKey(actor))
  if (value == null) return null
  const record = JSON.parse(value)
  if (!valid(record, actor)) throw new Error('原发货提交恢复记录异常，请联系管理员核对，勿重新创建')
  return copyShipment({ invoice_id: record.invoice_id, body: record.body })
}
export function saveShipmentSubmission(storage, actor, command) {
  const previous = readShipmentSubmission(storage, actor)
  if (previous && JSON.stringify(previous) !== JSON.stringify(command)) throw new Error('当前账号还有原发货提交待核对，请先恢复原提交')
  const record = { actor, ...copyShipment(command) }
  if (!valid(record, actor)) throw new Error('原发货请求不完整，不能可靠保存')
  const value = JSON.stringify(record)
  storage.setItem(shipmentSubmissionKey(actor), value)
  if (storage.getItem(shipmentSubmissionKey(actor)) !== value) throw new Error('原发货请求未能可靠保存，本次尚未发送')
}
export function clearShipmentSubmission(storage, actor, key) {
  const previous = readShipmentSubmission(storage, actor)
  if (previous && previous.body.request_key === key) storage.removeItem(shipmentSubmissionKey(actor))
}
export function isShipmentReceipt(result, command) {
  return positiveId(result?.id) && result.invoice_id === command?.invoice_id
    && result.request_key === command?.body?.request_key && result.quote_hash === command?.body?.quote_hash
    && positiveId(result.version) && typeof result.settlement_no === 'string' && result.settlement_no
    && typeof result.state === 'string' && result.state && result.quote && typeof result.quote === 'object' && !Array.isArray(result.quote)
}
export function isShipmentObservation(result, command) {
  const items = result?.invoice?.items, expected = command?.body?.items
  return result?.state === 'not_found' && result.request_key === command?.body?.request_key
    && result.invoice?.id === command?.invoice_id && Array.isArray(items) && Array.isArray(expected)
    && items.length === expected.length && new Set(items.map(row => row.id)).size === items.length
    && items.every(row => positiveId(row.id) && positiveId(row.quantity)
      && expected.some(original => original.invoice_item_id === row.id && original.quantity === row.quantity))
}
export function uncertainShipment(error, alreadyUnknown = false) {
  const status = error?.response?.status
  return alreadyUnknown || !status || status >= 500 || status === 408
}
