// One unresolved explicit confirmation per actor/tab; storage is not an authority source.
export const confirmationKey = actor => `ark_shipment_confirmation_v1:${actor}`
const positive = value => Number.isSafeInteger(value) && value > 0
const copy = value => JSON.parse(JSON.stringify(value))
const equal = (left, right) => JSON.stringify(left) === JSON.stringify(right)
function valid(command) {
  return positive(command?.invoice_id) && positive(command?.settlement_id) && positive(command?.outbound_id)
    && typeof command.remote_id === 'string' && /^[1-9][0-9]{0,63}$/.test(command.remote_id)
    && positive(command.body?.version) && typeof command.body.reason === 'string'
    && command.body.reason.trim().length >= 2 && command.body.reason.length <= 500
}
export function readConfirmation(storage, actor) {
  if (!positive(actor)) throw new Error('请先重新确认当前登录账号')
  const raw = storage.getItem(confirmationKey(actor))
  if (raw == null) return null
  const record = JSON.parse(raw)
  if (record?.actor !== actor || !valid(record.command)) throw new Error('原实际出库确认记录异常，请联系管理员核对，禁止再次发送')
  return copy(record.command)
}
export function saveConfirmation(storage, actor, command) {
  if (!valid(command)) throw new Error('原实际出库确认内容不完整，本次尚未发送')
  const previous = readConfirmation(storage, actor)
  if (previous && !equal(previous, command)) throw new Error('当前账号还有实际出库确认待核对，请先处理原结算')
  const value = JSON.stringify({ actor, command: copy(command) })
  storage.setItem(confirmationKey(actor), value)
  if (storage.getItem(confirmationKey(actor)) !== value) throw new Error('原实际出库确认无法可靠保存，本次尚未发送')
}
export function clearConfirmation(storage, actor, command) {
  const previous = readConfirmation(storage, actor)
  if (previous && !equal(previous, command)) throw new Error('原实际出库确认记录已变化，请先核对')
  if (previous) storage.removeItem(confirmationKey(actor))
  if (storage.getItem(confirmationKey(actor)) != null) throw new Error('原实际出库确认记录未能清除，请继续核对')
}
export function isConfirmationTarget(row, command) {
  return valid(command) && row?.id === command.settlement_id && row.invoice_id === command.invoice_id
    && row.outbound?.id === command.outbound_id && row.outbound.remote_id === command.remote_id
}
export function isConfirmationResolution(row, command, submittedVersion) {
  const summary = row?.outbound?.confirmation
  return isConfirmationTarget(row, command) && positive(submittedVersion) && positive(row.version)
    && row.version > Math.max(command.body.version, submittedVersion)
    && summary && ['none', 'resolved'].includes(summary.state) && summary.blocks_confirmation === false
    && summary.requires_review === false && summary.in_progress === false
    && (row.outbound.status === 'pending_remote' && row.state === 'outbound_pending'
      || row.outbound.status === 'shipped' && row.state === 'shipped'
      || row.outbound.status === 'shipped_unfunded' && row.state === 'outbound_uncertain')
}
export function protectConfirmation(row, command) {
  if (!isConfirmationTarget(row, command)) return row
  return { ...row, outbound: { ...row.outbound, confirmation: {
    state: row.outbound.confirmation?.in_progress === true ? 'active' : 'unresolved',
    requires_review: true, blocks_confirmation: true, in_progress: row.outbound.confirmation?.in_progress === true,
    message: '原实际出库确认仍待核对，普通刷新不能证明未执行，禁止再次发送',
  } } }
}
