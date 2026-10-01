/** Boundary stub for the shared feedback module; keeps exact recorded arguments. */
export function feedbackFixture({ ElMessage = {}, ElMessageBox = {} } = {}) {
  return {
    msgSuccessText: (...args) => ElMessage.success?.(...args),
    msgSuccess: action => ElMessage.success?.(`${action}成功`),
    msgError: (text, error) => { if (!error?._arkFeedbackHandled) return ElMessage.error?.(text) },
    msgWarning: (...args) => ElMessage.warning?.(...args),
    msgInfo: (...args) => ElMessage.info?.(...args),
    confirmAction: (...args) => ElMessageBox.confirm?.(...args),
    promptAction: (...args) => ElMessageBox.prompt?.(...args),
    alertAction: (...args) => ElMessageBox.alert?.(...args),
  }
}
