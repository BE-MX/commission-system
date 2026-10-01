import { confirmAction, msgSuccessText, isFeedbackCancelled } from '@/utils/feedback'
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'

import { useAsyncResource } from '@/composables/useAsyncResource'
import { operationsClient } from '@/api/clients'

const AUTO_REFRESH_MS = 30_000

export function useOperationsCenter() {
  const loading = ref(false)
  const actionJobId = ref('')
  const overviewResource = useAsyncResource(async (_, { signal }) => (await operationsClient.get('/overview', { signal, suppressToast: true, showLoading: false })).data)
  const runsResource = useAsyncResource(async (params, { signal }) => (await operationsClient.get('/job-runs', { signal, suppressToast: true, params, showLoading: false })).data || [], { initialData: [] })
  const overview = overviewResource.data, jobRuns = runsResource.data
  const runStatus = ref(''), appliedRunStatus = ref('')
  const runsPending = computed(() => runStatus.value !== appliedRunStatus.value)
  let refreshTimer = null
  let interactiveRequests = 0
  let active = false

  const scheduler = computed(() => overview.value?.scheduler || { jobs: [] })
  const services = computed(() => overview.value?.services || [])
  const runtimeInstances = computed(() => overview.value?.runtime_instances || [])
  const summary = computed(() => overview.value?.summary || {})

  const loadOverview = () => overviewResource.load()
  function loadJobRuns() { return runsResource.load({ limit: 30, ...(appliedRunStatus.value ? { status: appliedRunStatus.value } : {}) }) }
  function searchRuns() { appliedRunStatus.value = runStatus.value; return loadJobRuns() }
  function resetRuns() { runStatus.value = ''; return searchRuns() }

  async function loadDashboard({ quiet = false } = {}) {
    if (!quiet) {
      interactiveRequests++
      loading.value = true
    }
    try {
      await Promise.all([loadOverview(), loadJobRuns()])
    } finally {
      if (!quiet) loading.value = --interactiveRequests > 0
    }
  }

  async function operateJob(job, action) {
    const labels = { run: '立即执行', pause: '暂停', resume: '恢复' }
    const actionLabel = labels[action]
    if (!actionLabel) return
    const warnings = {
      run: `任务会使用生产数据和现有外部配置。`,
      pause: '暂停后将不再按计划执行，直至人工恢复。',
      resume: '恢复后任务会重新按原计划执行。',
    }
    if (actionJobId.value || overviewResource.error.value || !overviewResource.hasLoaded.value) return
    actionJobId.value = job.id
    try {
      await confirmAction(
        `确定${actionLabel}「${job.name}」？${warnings[action]}`,
        `${actionLabel}确认`,
        { type: 'warning', confirmButtonText: `确定${actionLabel}`, cancelButtonText: '取消' },
      )
      const response = await operationsClient.post(`/jobs/${job.id}/${action}`, null, { showLoading: false })
      msgSuccessText(response.message || `${actionLabel}成功`)
      await loadDashboard({ quiet: true })
    } catch (error) {
      if (!isFeedbackCancelled(error)) throw error
    } finally {
      actionJobId.value = ''
    }
  }

  function refresh(quiet = true) {
    if (document.hidden) return
    void loadDashboard({ quiet })
  }
  function startRefresh() {
    if (active) return
    active = true
    refresh(Boolean(overview.value))
    refreshTimer = window.setInterval(() => refresh(), AUTO_REFRESH_MS)
  }
  function stopRefresh() {
    active = false
    if (refreshTimer !== null) window.clearInterval(refreshTimer)
    refreshTimer = null
    overviewResource.cancel(); runsResource.cancel()
  }
  onMounted(startRefresh)
  onActivated(startRefresh)
  onDeactivated(stopRefresh)
  onBeforeUnmount(stopRefresh)

  return {
    loading, actionJobId, overview, scheduler, services, runtimeInstances, summary,
    jobRuns, runStatus, runsPending, searchRuns, resetRuns, overviewResource, runsResource, loadOverview, loadDashboard, loadJobRuns, operateJob,
  }
}
