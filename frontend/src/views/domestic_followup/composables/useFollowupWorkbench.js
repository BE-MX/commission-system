import { computed, reactive, ref } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { newRequestId } from '../followupDraft'

export function useFollowupWorkbench() {
  const summary = reactive({ receipt: 0, plan: 0, issue: 0, urgent: 0, upcoming: 0 })
  const typeFilter = ref('') // '' | receipt | plan | issue
  const dueTasks = ref([])
  const upcomingTasks = ref([])
  const drafts = ref([])
  const records = reactive({ items: [], total: 0, page: 1, pageSize: 20, loading: false })
  const loading = ref(false)

  const filtered = computed(() => ({
    due: typeFilter.value ? dueTasks.value.filter(t => matchType(t, typeFilter.value)) : dueTasks.value,
    upcoming: typeFilter.value ? upcomingTasks.value.filter(t => matchType(t, typeFilter.value)) : upcomingTasks.value,
  }))

  function matchType(task, type) {
    return type === 'issue' ? ['issue', 'suggestion'].includes(task.task_type) : task.task_type === type
  }

  async function loadTasks() {
    loading.value = true
    try {
      const [s, due, upcoming, d] = await Promise.all([
        followupApi.summary(), followupApi.tasks({ due: 'today', page_size: 200 }),
        followupApi.tasks({ due: 'upcoming', page_size: 100 }), followupApi.drafts(),
      ])
      Object.assign(summary, s)
      dueTasks.value = due.items
      upcomingTasks.value = upcoming.items
      drafts.value = d
    } catch (e) { msgError(apiError(e, '待办加载失败'), e) } finally { loading.value = false }
  }

  async function loadRecords(page = 1) {
    records.loading = true
    try {
      const res = await followupApi.followups({ mine: true, page, page_size: records.pageSize })
      Object.assign(records, { items: res.items, total: res.total, page })
    } catch (e) { msgError(apiError(e, '记录加载失败'), e) } finally { records.loading = false }
  }

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

  return { summary, typeFilter, filtered, drafts, records, loading, loadTasks, loadRecords, snooze, receiptOk }
}
