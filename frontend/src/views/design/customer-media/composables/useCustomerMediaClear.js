import { ref } from 'vue'
import { clearMediaAssets } from '@/api/customerMedia'
import { confirmAction, isFeedbackCancelled, msgError, msgSuccessText } from '@/utils/feedback'

export function useCustomerMediaClear({ getBatch, onBatch, isBlocked, refreshBatch, onCleared }) {
  const clearing = ref(false)

  async function clearAssets() {
    const batch = getBatch()
    if (clearing.value || isBlocked() || !['draft', 'changes_requested'].includes(batch?.status)) return
    const ids = (batch.assets || []).map(asset => asset.id)
    if (!ids.length) return
    clearing.value = true
    try {
      await confirmAction(
        `将删除本批全部 ${ids.length} 个已上传文件（含筛选隐藏项），删除后无法恢复。客户标签和待上传清单会保留。`,
        '清空本批素材',
        { type: 'warning', confirmButtonText: '确认清空', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger', closeOnClickModal: false },
      )
      const response = await clearMediaAssets(batch.id, ids)
      onBatch(response.data)
      onCleared()
      msgSuccessText('本批素材已清空')
    } catch (error) {
      if (isFeedbackCancelled(error)) return
      msgError('清空失败，请核对本批素材后重试', error)
      // A timeout may follow a committed deletion. Read back before another attempt.
      try { await refreshBatch() } catch (refreshError) {
        msgError('素材列表刷新失败，请刷新页面后核对', refreshError)
      }
    } finally { clearing.value = false }
  }

  return { clearing, clearAssets }
}
