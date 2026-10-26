import { ref } from 'vue'
import { promptAction, msgSuccessText } from '@/utils/feedback'
import { skipAllOrderProcesses, newRequestId } from '@/api/domestic'

export function useDomesticOrderSkip(refreshAll) {
  const skippingAll = ref(false)
  let pending = null
  async function handleSkipAll(order) {
    if (skippingAll.value) return
    skippingAll.value = true
    try {
      if (pending?.orderId !== order.id) {
        let value
        try {
          ({ value } = await promptAction(
            `将跳过 ${order.domestic_no} 中所有未完成工序，保留已报工与已发货记录。跳过不计工资，不生成发货记录。`,
            '一键跳过全部工序', {
              type: 'warning', confirmButtonText: '确认跳过', inputPlaceholder: '填写原因（至少 5 字）',
              inputValidator: value => (value?.trim().length >= 5 && value.trim().length <= 500) || '原因需为 5 到 500 字',
            },
          ))
        } catch { return }
        pending = { orderId: order.id, reason: value.trim(), request_id: newRequestId() }
      }
      await skipAllOrderProcesses(order.id, { reason: pending.reason, request_id: pending.request_id })
      pending = null
      msgSuccessText('剩余工序已全部跳过')
      await refreshAll()
    } finally { skippingAll.value = false }
  }
  return { skippingAll, handleSkipAll }
}
