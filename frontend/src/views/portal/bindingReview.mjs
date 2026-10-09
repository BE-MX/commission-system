export function bindingReviewPayload(context, form) {
  if (!/^[0-9a-f]{64}$/.test(context.review_fingerprint)) throw new Error('复核数据不完整，请重新读取。')
  const reason = form.reason.trim()
  if (!reason || reason.length > 500) throw new Error('请填写 1–500 字的复核原因。')
  const body = { review_fingerprint: context.review_fingerprint, reason }
  if (form.action === 'rebind') {
    if (context.requires_assignment_review || context.customer_requires_review) throw new Error('请先完成方舟客户档案和主负责人复核。')
    if (!context.identities.some(row => row.id === form.identity_id)) throw new Error('请选择当前已验证的公司身份。')
    return { ...body, identity_id: form.identity_id }
  }
  if (form.action !== 'transfer' || !context.assignments.some(row => row.id === form.assignment_id)) throw new Error('请选择方舟当前有效主负责人。')
  const ids = form.pending_request_ids
  if (ids.length > 1000 || new Set(ids).size !== ids.length || ids.some(id => !context.pending_requests.some(row => row.id === id))) throw new Error('交接订单选择已失效，请重新读取。')
  if (!['remove', 'explicit_grant'].includes(form.history_policy)) throw new Error('请选择历史读取策略。')
  if (form.history_policy === 'explicit_grant' && (!Number.isInteger(form.history_days) || form.history_days < 1 || form.history_days > 365)) throw new Error('历史读取期限须为 1–365 天。')
  return { ...body, assignment_id: form.assignment_id, pending_request_ids: [...ids], history_policy: form.history_policy, history_days: form.history_policy === 'explicit_grant' ? form.history_days : null }
}

export function validateBindingReceipt(operation, result) {
  const count = value => Number.isSafeInteger(value) && value >= 0
  if (!result || !['suspended', 'review_required'].includes(result.status) || result.requires_enable !== true) throw new Error('服务器复核回执不完整，请读取当前状态。')
  if (operation.action === 'transfer') {
    if (!Array.isArray(result.reassigned_request_ids) || !Array.isArray(result.unassigned_pending_request_ids) || !count(result.history_grants)) throw new Error('服务器交接回执不完整，请读取当前状态。')
    const selected = [...operation.body.pending_request_ids].sort()
    if (JSON.stringify([...result.reassigned_request_ids].sort()) !== JSON.stringify(selected)) throw new Error('服务器交接范围需要核对，请读取当前状态。')
  } else if (operation.action !== 'rebind' || !count(result.expired_quotes)) throw new Error('服务器身份回执不完整，请读取当前状态。')
  return result
}
