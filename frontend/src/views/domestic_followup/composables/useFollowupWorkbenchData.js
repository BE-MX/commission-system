import { computed, reactive, ref } from 'vue'
import { errorMessage } from '../../../utils/errors.js'

export function useFollowupWorkbenchData(api, potentialOnly) {
  const emptySummary = () => ({ receipt: 0, plan: 0, issue: 0, urgent: 0, upcoming: 0 })
  const summary = reactive(emptySummary()), typeFilter = ref('')
  const dueTasks = ref([]), upcomingTasks = ref([]), drafts = ref([])
  const records = reactive({ items: [], total: 0, page: 1, pageSize: 20, loading: false, error: '', loaded: false })
  const loading = ref(false), error = ref(''), loaded = ref(false)
  let taskRequest = 0, recordRequest = 0
  const matchType = (task, type) => type === 'issue' ? ['issue', 'suggestion'].includes(task.task_type) : task.task_type === type
  const filtered = computed(() => ({
    due: typeFilter.value ? dueTasks.value.filter(t => matchType(t, typeFilter.value)) : dueTasks.value,
    upcoming: typeFilter.value ? upcomingTasks.value.filter(t => matchType(t, typeFilter.value)) : upcomingTasks.value,
  }))
  async function loadTasks() {
    const run = ++taskRequest, scope = potentialOnly.value
    loading.value = true
    error.value = ''
    try {
      const [s, due, upcoming, d] = await Promise.all([
        api.summary({ potential_only: scope }), api.tasks({ due: 'today', page_size: 200, potential_only: scope }),
        api.tasks({ due: 'upcoming', page_size: 100, potential_only: scope }), api.drafts({ potential_only: scope }),
      ])
      if (run !== taskRequest || scope !== potentialOnly.value) return
      Object.assign(summary, s)
      dueTasks.value = due.items
      upcomingTasks.value = upcoming.items
      drafts.value = d
      loaded.value = true
    } catch (failure) { if (run === taskRequest) error.value = errorMessage(failure, '待办加载失败') }
    finally { if (run === taskRequest) loading.value = false }
  }
  async function loadRecords(page = 1) {
    const run = ++recordRequest, scope = potentialOnly.value
    records.loading = true
    records.error = ''
    try {
      const res = await api.followups({ mine: true, page, page_size: records.pageSize, potential_only: scope })
      if (run !== recordRequest || scope !== potentialOnly.value) return
      Object.assign(records, { items: res.items, total: res.total, page, loaded: true })
    } catch (failure) { if (run === recordRequest) records.error = errorMessage(failure, '记录加载失败') }
    finally { if (run === recordRequest) records.loading = false }
  }
  function resetScope() {
    taskRequest++; recordRequest++
    dueTasks.value = []
    upcomingTasks.value = []
    drafts.value = []
    Object.assign(summary, emptySummary())
    loaded.value = false
    error.value = ''
    Object.assign(records, { items: [], total: 0, page: 1, error: '', loaded: false, loading: false })
  }
  return { summary, typeFilter, filtered, drafts, records, loading, loaded, error, loadTasks, loadRecords, resetScope }
}
