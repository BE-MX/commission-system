/** Shared feedback; keep domain evidence and confirmations intact. */
import { ElMessage, ElMessageBox } from 'element-plus'

export function msgSuccess(action = '操作') { return msgSuccessText(`${action}成功`) }
export function msgError(text = '操作失败', error) {
  if (error?._arkFeedbackHandled) return
  if (error && typeof error === 'object') error._arkFeedbackHandled = true
  return ElMessage.error(text)
}
export function msgSuccessText(text) { return ElMessage.success(text) }
export function msgWarning(text) { return ElMessage.warning(text) }
export function msgInfo(text) { return ElMessage.info(text) }
export function isFeedbackCancelled(error) {
  const action = typeof error === 'string' ? error : error?.action || error?.message
  return action === 'cancel' || action === 'close'
}
export function notifyFeedback(type, text) {
  return ({ success: msgSuccessText, error: msgError, warning: msgWarning, info: msgInfo }[type] || msgInfo)(text)
}
export function confirmAction(message, title = '操作确认', options = {}) { return ElMessageBox.confirm(message, title, options) }
export function promptAction(message, title = '填写信息', options = {}) { return ElMessageBox.prompt(message, title, options) }
export function alertAction(message, title = '提示', options = {}) { return ElMessageBox.alert(message, title, options) }
export function confirmDanger(action, target, extra = '此操作不可恢复。') {
  return confirmAction(`确定${action}${target ? `「${target}」` : ''}？${extra}`, `${action}确认`,
    { type: 'warning', confirmButtonText: `确定${action}`, cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' })
}
