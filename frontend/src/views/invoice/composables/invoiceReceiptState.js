import { toMoneyCents } from './invoiceSettlement.js'

export function nextDraftAmount(draft, previous, value, orderType) {
  if (!draft || draft.status !== 'draft' || orderType === 'presale') return draft?.amount
  if (draft.amount == null || toMoneyCents(draft.amount) === toMoneyCents(previous)) return Number(value) > 0 ? Number(value) : null
  return draft.amount
}

export function projectReceiptBalance(balance, total) {
  const due = toMoneyCents(total), effective = toMoneyCents(balance.effective_amount)
  const registered = toMoneyCents(balance.registered_amount)
  return { unpaid: Math.max(due - effective, 0) / 100, overpaid: Math.max(effective - due, 0) / 100,
    available: Math.max(due - registered, 0) / 100, pendingExcess: Math.max(registered - Math.max(due, effective), 0) / 100 }
}

export function receiptActionState(receipt) {
  if (!receipt) return { editable: false, label: '尚未生成回款', hint: '首次回款在订单完整同步后生成。' }
  if (receipt.status !== 'active') return { editable: false, label: receipt.status === 'voided' ? '已作废' : '远端删除已核实', hint: '原回款记录与凭证保留，新增收款请另行登记。' }
  if (receipt.batch_id || ['presale_deposit', 'presale_advance'].includes(receipt.purpose)) return { editable: false, label: '预售 / 批次回款', hint: '原款用于后续发货抵扣，新增收款请单独登记；用途纠错请在回款单中核对。' }
  const editable = ['pending', 'failed'].includes(receipt.sync_status) && !receipt.xiaoman_receipt_id
  const labels = { pending: '待发送', failed: '同步失败', syncing: '发送中', synced: '已同步小满', uncertain: '结果待核对' }
  return { editable, label: labels[receipt.sync_status] || '待处理',
    hint: editable ? '可修正原回款；保存修正后需点击重试同步。' : receipt.sync_status === 'synced'
      ? '已同步金额保留；新增实际收款另行登记，录入纠错请先在小满处理后核对变更。'
      : '正在发送或结果待核对，请核实原回款，避免重复登记。' }
}

export function invoiceOrderSignature(payload) {
  const { receipt_draft, ...order } = payload
  return JSON.stringify(order)
}

export function applySubmittedReceipt(form, row) {
  const draft = form.receipt_draft
  if (!draft || !['armed', 'ready', 'converted'].includes(draft.status) || row.source !== 'auto' || row.invoice_id !== form.id) return false
  if (draft.status === 'converted' && draft.receipt_id !== row.id) return false
  Object.assign(draft, { status: 'converted', receipt_id: row.id, amount: Number(row.amount),
    purpose: row.purpose, bank_charge: Number(row.bank_charge || 0),
    collection_date: row.collection_date, payment_type: row.payment_type, remark: row.remark || '',
    attachment_ids: row.attachments.map(file => file.id), last_error: row.last_error,
    receipt_status: row.status, receipt_sync_status: row.sync_status, receipt_version: row.version })
  return true
}
