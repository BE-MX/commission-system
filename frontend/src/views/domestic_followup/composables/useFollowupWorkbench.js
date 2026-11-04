import { ref } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { newRequestId } from '../followupDraft'
import { useFollowupWorkbenchData } from './useFollowupWorkbenchData'

export function useFollowupWorkbench(potentialOnly = ref(false)) {
  const data = useFollowupWorkbenchData(followupApi, potentialOnly)
  const { loadTasks } = data

  async function snooze(task, days) {
    try {
      await followupApi.snooze(task.id, days)
      msgSuccessText(`已顺延 ${days} 天`)
      await loadTasks()
    } catch (e) { msgError(apiError(e, '顺延失败'), e) }
  }

  async function receiptOk(task) {
    try {
      await followupApi.receiptOk(task.id, newRequestId())
      msgSuccessText('已记录：回访无问题')
      await loadTasks()
    } catch (e) {
      if (e?.response?.status === 409) {  // 上次超时其实已成功：当成功处理
        msgSuccessText('这条回访已经记过了')
        await loadTasks()
        return
      }
      msgError(apiError(e, '记录失败'), e)
    }
  }

  return { ...data, snooze, receiptOk }
}
