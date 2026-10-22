import { ref } from 'vue'
import { syncOutboundReplenishment } from '@/api/shipping'
import { msgSuccessText, msgWarning, msgError } from '@/utils/feedback'

export function useOutboundReplenishment(refresh) {
  const replenishingId = ref(null)
  async function replenish(row) {
    if (replenishingId.value !== null) return
    const id = row.outbound_record_id
    replenishingId.value = id
    try {
      const response = await syncOutboundReplenishment(id)
      const result = response.data
      if (result.status === 'done') msgSuccessText(result.message)
      else msgWarning(result.message || '库存状态已更新，请核对原任务')
    } catch (error) {
      msgError(error?.response?.data?.detail || error?.response?.data?.message || '补货同步结果暂未确认，请刷新核对原任务；不要重复提交', error)
    } finally {
      try { await refresh({ silent: true }) } finally { replenishingId.value = null }
    }
  }
  return { replenishingId, replenish }
}
