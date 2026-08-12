import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { operationsClient } from '@/api/clients'

const AUTO_REFRESH_MS = 30_000

export function useOperationsCenter() {
  const loading = ref(false)
  const actionJobId = ref('')
  const overview = ref(null)
  const jobRuns = ref([])
  const runStatus = ref('')
  let refreshTimer = null
  let requestSequence = 0
  let runRequestSequence = 0
  let dashboardSequence = 0

  const scheduler = computed(() => overview.value?.scheduler || { jobs: [] })
  const services = computed(() => overview.value?.services || [])
  const runtimeInstances = computed(() => overview.value?.runtime_instances || [])
  const summary = computed(() => overview.value?.summary || {})

  async function loadOverview({ quiet = false } = {}) {
    const sequence = ++requestSequence
    if (!quiet) loading.value = true
    try {
      const response = await operationsClient.get('/overview', { showLoading: false })
      if (sequence === requestSequence) overview.value = response.data
    } finally {
      if (!quiet && sequence === requestSequence) loading.value = false
    }
  }

  async function loadJobRuns() {
    const sequence = ++runRequestSequence
    const params = { limit: 30 }
    if (runStatus.value) params.status = runStatus.value
    const response = await operationsClient.get('/job-runs', { params, showLoading: false })
    if (sequence === runRequestSequence) jobRuns.value = response.data || []
  }

  async function loadDashboard({ quiet = false } = {}) {
    const sequence = ++dashboardSequence
    if (!quiet) loading.value = true
    try {
      await Promise.all([loadOverview({ quiet: true }), loadJobRuns()])
    } finally {
      if (!quiet && sequence === dashboardSequence) loading.value = false
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
    if (actionJobId.value) return
    actionJobId.value = job.id
    try {
      await ElMessageBox.confirm(
        `确定${actionLabel}「${job.name}」？${warnings[action]}`,
        `${actionLabel}确认`,
        { type: 'warning', confirmButtonText: `确定${actionLabel}`, cancelButtonText: '取消' },
      )
      const response = await operationsClient.post(`/jobs/${job.id}/${action}`, null, { showLoading: false })
      ElMessage.success(response.message || `${actionLabel}成功`)
      await loadDashboard({ quiet: true })
    } finally {
      actionJobId.value = ''
    }
  }

  onMounted(async () => {
    await loadDashboard()
    refreshTimer = window.setInterval(() => loadDashboard({ quiet: true }), AUTO_REFRESH_MS)
  })
  onBeforeUnmount(() => {
    if (refreshTimer) window.clearInterval(refreshTimer)
  })

  return {
    loading, actionJobId, overview, scheduler, services, runtimeInstances, summary,
    jobRuns, runStatus, loadDashboard, loadJobRuns, operateJob,
  }
}
