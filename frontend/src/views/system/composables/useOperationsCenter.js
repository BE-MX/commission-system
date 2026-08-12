import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { operationsClient } from '@/api/clients'

const AUTO_REFRESH_MS = 30_000

export function useOperationsCenter() {
  const loading = ref(false)
  const actionJobId = ref('')
  const overview = ref(null)
  let refreshTimer = null
  let requestSequence = 0

  const scheduler = computed(() => overview.value?.scheduler || { jobs: [] })
  const services = computed(() => overview.value?.services || [])
  const summary = computed(() => overview.value?.summary || {})

  async function loadOverview({ quiet = false } = {}) {
    const sequence = ++requestSequence
    if (!quiet) loading.value = true
    try {
      const response = await operationsClient.get('/overview', { showLoading: false })
      if (sequence === requestSequence) overview.value = response.data
    } finally {
      if (sequence === requestSequence) loading.value = false
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
    await ElMessageBox.confirm(
      `确定${actionLabel}「${job.name}」？${warnings[action]}`,
      `${actionLabel}确认`,
      { type: 'warning', confirmButtonText: `确定${actionLabel}`, cancelButtonText: '取消' },
    )
    actionJobId.value = job.id
    try {
      const response = await operationsClient.post(`/jobs/${job.id}/${action}`, null, { showLoading: false })
      ElMessage.success(response.message || `${actionLabel}成功`)
      await loadOverview({ quiet: true })
    } finally {
      actionJobId.value = ''
    }
  }

  onMounted(async () => {
    await loadOverview()
    refreshTimer = window.setInterval(() => loadOverview({ quiet: true }), AUTO_REFRESH_MS)
  })
  onBeforeUnmount(() => {
    if (refreshTimer) window.clearInterval(refreshTimer)
  })

  return { loading, actionJobId, overview, scheduler, services, summary, loadOverview, operateJob }
}
