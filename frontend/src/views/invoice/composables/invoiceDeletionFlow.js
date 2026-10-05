import { formatMoney } from '../../../utils/money.js'

export function usesRelatedInvoiceDeletion(row) {
  return Boolean(row.xiaoman_order_id || row.sync_status === 'synced' || ['synced', 'cancel_pending'].includes(row.status))
}

export function buildInvoiceDeletionConfirmation(preview) {
  const outbounds = preview.outbounds || []
  const receipts = preview.receipts || []
  const amounts = receipts.map(receipt => `${receipt.number || receipt.id}：${receipt.currency || '未知币种'} ${formatMoney(receipt.amount)}`)
  const localCount = Number(preview.local_receipt_count) || 0
  return [
    `确定删除订单发票「${preview.invoice_no}」及关联单据？`,
    `系统将自动删除 ${outbounds.length} 张关联出库单、${receipts.length} 笔小满回款及小满订单，同步处理 ${localCount} 笔方舟回款并保留原凭证与审计记录。`,
    amounts.length ? `小满回款金额：${amounts.join('；')}。` : '',
    '原发票和审计记录将保留为取消归档。删除回款记录不会退款，此操作不可恢复。',
  ].filter(Boolean).join('\n')
}

export function invoiceDeletionFeedback(result) {
  if (result.status === 'remote_deleted') return { type: 'success', message: result.message || '关联单据已删除，订单发票已取消归档' }
  if (result.status === 'uncertain') return { type: 'warning', message: `${result.message || '部分删除请求的结果待核对'}。请再次点击删除核对进度，系统不会重复发送结果未知的请求。` }
  if (result.status === 'running') return { type: 'info', message: result.message || '删除任务正在处理，请稍后再次点击删除核对进度' }
  return { type: 'warning', message: result.message || '关联单据删除尚未完成，请再次点击删除查看阻碍并继续处理' }
}

// Only the explicit confirmation authorizes a POST; retries always begin with a fresh preview.
export async function runRelatedInvoiceDeletion(id, { preview, confirm, remove, refresh, notify, showBlockers, isCancelled }) {
  const evidence = await preview(id)
  if (evidence.complete) {
    notify('success', '关联单据已删除，订单发票已取消归档')
    await refresh()
    return 'remote_deleted'
  }
  if (evidence.blockers?.length) {
    await showBlockers(evidence.blockers.join('\n'))
    await refresh()
    return 'blocked'
  }
  try {
    await confirm(buildInvoiceDeletionConfirmation(evidence))
  } catch (error) {
    if (isCancelled(error)) return 'cancelled'
    throw error
  }
  let result
  try {
    result = await remove(id, { expected_version: evidence.version, confirmed: true })
    if (!result?.status) result = { status: 'uncertain', message: '删除响应缺少结果，进度待核对' }
  } catch (error) {
    const status = error?.response?.status
    result = {
      status: status >= 400 && status < 500 ? 'blocked' : 'uncertain',
      message: error?.response?.data?.message || error?.response?.data?.detail || '未收到完整删除结果',
    }
  }
  const feedback = invoiceDeletionFeedback(result)
  notify(feedback.type, feedback.message)
  await refresh()
  return result.status
}
