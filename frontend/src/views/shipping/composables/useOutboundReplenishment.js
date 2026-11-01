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
  const reviewRow = ref(null)
  // Administrator confirmation that an uncertain submission created nothing in OKKI.
  async function confirmNotCreated(review) {
    const row = reviewRow.value
    if (!row || replenishingId.value !== null) return
    replenishingId.value = row.outbound_record_id
    try {
      const result = (await syncOutboundReplenishment(row.outbound_record_id, review)).data
      reviewRow.value = null
      msgSuccessText(result.message)
    } catch (error) {
      msgError(error?.response?.data?.detail || error?.response?.data?.message || '人工核对未完成，请刷新后重试', error)
    } finally {
      try { await refresh({ silent: true }) } finally { replenishingId.value = null }
    }
  }
  return { replenishingId, replenish, reviewRow, confirmNotCreated }
}
