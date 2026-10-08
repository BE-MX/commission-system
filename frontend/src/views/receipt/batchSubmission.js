// One unresolved operation per actor and tab; no credentials or display metadata.
export const batchSubmissionKey = actor => `ark_receipt_batch_pending_v1:${actor}`
export const copySubmission = body => JSON.parse(JSON.stringify(body))
function validRecord(record, actor) {
  const body = record?.body
  return record?.actor === actor && typeof body?.request_key === 'string' && /^[a-zA-Z0-9_-]{16,64}$/.test(body.request_key)
    && Array.isArray(body.allocations) && body.allocations.length > 0 && body.allocations.length <= 50
    && body.allocations.every(row => Number.isSafeInteger(row.invoice_id) && row.invoice_id > 0 && /^[a-f0-9]{64}$/.test(row.balance_version))
    && Array.isArray(body.attachment_ids) && body.attachment_ids.length > 0
}
export function readSubmission(storage, actor) {
  if (!Number.isSafeInteger(actor) || actor <= 0) throw new Error('请先重新确认当前登录账号')
  const value = storage.getItem(batchSubmissionKey(actor))
  if (value == null) return null
  const record = JSON.parse(value)
  if (!validRecord(record, actor)) throw new Error('原提交恢复记录异常，请联系管理员核对原批次，勿重新创建')
  return copySubmission(record.body)
}
export function saveSubmission(storage, actor, body) {
  const previous = readSubmission(storage, actor)
  // Even the same key with a different body must never replace the pending command.
  if (previous && JSON.stringify(previous) !== JSON.stringify(body)) throw new Error('当前账号还有原提交待核对，请先恢复原批次')
  const record = { actor, body: copySubmission(body) }
  if (!validRecord(record, actor)) throw new Error('无法保存原提交，请重新核对')
  const value = JSON.stringify(record)
  storage.setItem(batchSubmissionKey(actor), value)
  if (storage.getItem(batchSubmissionKey(actor)) !== value) throw new Error('未能可靠保存原提交，本次尚未发送')
}
export function clearSubmission(storage, actor, key) {
  const previous = readSubmission(storage, actor)
  if (previous && previous.request_key === key) storage.removeItem(batchSubmissionKey(actor))
}
export function isBatchReceipt(result, body) {
  if (!Number.isSafeInteger(result?.id) || result.id <= 0 || result.request_key !== body.request_key
    || !['active', 'voided'].includes(result.status) || !Array.isArray(result.items)) return false
  const expected = new Set(body.allocations.map(row => row.invoice_id)), actual = new Set(result.items.map(row => row.invoice_id))
  return expected.size === actual.size && [...actual].every(id => expected.has(id))
}
export function uncertainSubmission(error, alreadyUnknown = false) {
  const status = error?.response?.status
  return alreadyUnknown || !status || status >= 500 || status === 408
}
