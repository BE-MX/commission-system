import { toMoneyCents } from './invoiceSettlement.js'

export function invoiceReceiptSyncGuidance(form) {
  if (!form.id || form.transaction_mode === 'local') return null
  if (['cancel_pending', 'cancelled'].includes(form.status)) return null
  if (form.receipt_sync_refresh_required) return { message: '同步状态未能刷新，请关闭并重新打开订单，核对结果后再补登记回款。', canSync: false }
  if (form.linked_sync_id) return { message: '订单关联同步尚未完成，请先处理上方的关联同步任务，完成后再补登记回款。', canSync: false }
  if (form.sync_status === 'sync_uncertain') return { message: '订单同步结果待核对，请先返回订单列表“处理待核对”，核对原同步结果后再补登记回款。', canSync: false }
  if (['armed', 'ready'].includes(form.receipt_draft?.status)) return { message: '首次回款正在处理中，请等待处理完成后刷新资金汇总，再核对是否需要补登记回款。', canSync: false }
  const needsSync = form.receipt_order_dirty || ['not_synced', 'sync_failed'].includes(form.sync_status)
  if (!needsSync) return null
  if (form.presale_edit_blocked_reason) return { message: form.presale_edit_blocked_reason, canSync: false }
  return { message: '订单尚未完成同步，请先保存并同步，再补登记回款。同步成功后重新打开订单，在下方登记实际到账款。', canSync: true }
}

export function projectReceiptBalance(balance, total) {
  const due = toMoneyCents(total), effective = toMoneyCents(balance.effective_amount)
  const registered = toMoneyCents(balance.registered_amount)
  return { unpaid: Math.max(due - effective, 0) / 100, overpaid: Math.max(effective - due, 0) / 100,
    available: Math.max(due - registered, 0) / 100, pendingExcess: Math.max(registered - Math.max(due, effective), 0) / 100 }
}

export function receiptActionState(receipt) {
  if (!receipt) return { editable: false, label: '尚未生成回款', hint: '有实际到账款后可登记回款。' }
  if (receipt.status !== 'active') return { editable: false, label: receipt.status === 'voided' ? '已作废' : '远端删除已核实', hint: '原回款记录与凭证保留，新增收款请另行登记。' }
  if (receipt.deletion_pending) return { editable: false, label: '删除待核验', hint: '原删除请求已记录，请继续核验删除；核验通过前不能登记替代回款。' }
  if (receipt.batch_id || ['presale_deposit', 'presale_advance'].includes(receipt.purpose)) return { editable: false, label: '预售 / 批次回款', hint: '原款用于后续发货抵扣，新增收款请单独登记；用途纠错请在回款单中核对。' }
  const editable = ['pending', 'failed'].includes(receipt.sync_status) && !receipt.xiaoman_receipt_id
  const labels = { pending: '待发送', failed: '同步失败', syncing: '发送中', synced: '已同步小满', uncertain: '结果待核对' }
  return { editable, label: labels[receipt.sync_status] || '待处理',
    hint: editable ? '可修正原回款；保存修正后需点击重试同步。' : receipt.sync_status === 'synced'
      ? '已同步金额保留；新增实际收款另行登记，录入纠错请先在小满处理后核对变更。'
      : '正在发送或结果待核对，请核实原回款，避免重复登记。' }
}

function withoutInvoiceGroups(payload) {
  const { item_groups, expected_groups_version, ...rest } = payload
  return {
    ...rest,
    items: (payload.items || []).map(({ group_key, ...item }) => item),
  }
}

export function invoiceBusinessSignature(payload) {
  return JSON.stringify(withoutInvoiceGroups(payload))
}

export function invoiceOrderSignature(payload) {
  const { receipt_draft, ...order } = withoutInvoiceGroups(payload)
  return JSON.stringify(order)
}

export function applySubmittedReceipt(form, row) {
  const draft = form.receipt_draft
  if (!draft || !['armed', 'ready', 'converted'].includes(draft.status) || row.source !== 'auto' || row.invoice_id !== form.id) return false
  if (draft.status === 'converted' && draft.receipt_id !== row.id) return false
  if (draft.status === 'converted' && row.version < draft.receipt_version) return false
  Object.assign(draft, { status: 'converted', receipt_id: row.id, amount: Number(row.amount),
    purpose: row.purpose, bank_charge: Number(row.bank_charge || 0),
    collection_date: row.collection_date, payment_type: row.payment_type, remark: row.remark || '',
    attachment_ids: row.attachments.map(file => file.id), last_error: row.last_error,
    receipt_status: row.status, receipt_sync_status: row.sync_status, receipt_version: row.version })
  return true
}
