import { reactive } from 'vue'
import { msgSuccessText, msgWarning } from '@/utils/feedback'
import { terminateOrderItem, newRequestId } from '@/api/domestic'

export function useDomesticItemTermination(refreshAll) {
  const terminatingItemIds = reactive(new Set())
  const pendingAttempts = new Map()
  const terminationDialog = reactive({ visible: false, item: null, qty: 1, maxQty: 1, reason: '', requestId: '' })
  function handleTerminateItem(item) {
    if (terminatingItemIds.size) return
    const pending = pendingAttempts.get(item.id)
    if (pending) {
      Object.assign(terminationDialog, { visible: true, item, ...pending })
      return
    }
    const maxQty = item.order_qty - Number(item.shipped_qty || 0)
    if (maxQty < 1) return
    Object.assign(terminationDialog, { visible: true, item, qty: maxQty, maxQty, reason: '', requestId: newRequestId() })
  }
  async function confirmTerminateItem() {
    const { item, qty, maxQty, reason, requestId } = terminationDialog
    if (!item || terminatingItemIds.has(item.id)) return
    if (!Number.isInteger(qty) || qty < 1 || qty > maxQty) return msgWarning('请选择有效的终止数量')
    if (!reason.trim()) return msgWarning('请填写终止原因')
    terminatingItemIds.add(item.id)
    pendingAttempts.set(item.id, { qty, maxQty, reason, requestId })
    try {
      await terminateOrderItem(item.id, reason.trim(), qty, requestId)
      pendingAttempts.delete(item.id)
      terminationDialog.visible = false
      msgSuccessText(`已终止 ${qty} 件`)
      await refreshAll()
    } finally { terminatingItemIds.delete(item.id) }
  }

  return { handleTerminateItem, terminatingItemIds, terminationDialog, confirmTerminateItem }
}
