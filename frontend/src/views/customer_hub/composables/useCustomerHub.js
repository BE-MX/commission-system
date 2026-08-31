import { computed, ref } from 'vue'
import { useListPage } from '@/composables/useListPage'
import {
  createPublicPoolBatch,
  createSearchJob,
  getCustomer,
  getAcquisitionProfile,
  listActions,
  listCustomerTimeline,
  listCustomers,
  listOpportunities,
  listResearchTasks,
  listSearchJobs,
  requeueSearchJob,
  reviewResearchTask,
  saveAcquisitionProfile,
  updateAction,
} from '@/api/customerHub'

const LISTERS = {
  customers: listCustomers,
  acquisition: listSearchJobs,
  research: listResearchTasks,
  opportunities: listOpportunities,
  radar: listActions,
}

export function useAcquisitionWorkflows() {
  const workflowLoading = ref(false), workflowError = ref(null), profile = ref(null)
  async function run(request) { workflowLoading.value = true; workflowError.value = null; try { return await request() } catch (error) { workflowError.value = error; return null } finally { workflowLoading.value = false } }
  async function loadProfile() { const response = await run(getAcquisitionProfile); profile.value = response?.data || null; return profile.value }
  async function saveProfile(payload) { const response = await run(() => saveAcquisitionProfile(payload)); return Boolean(response) }
  async function createJob(payload) { return Boolean(await run(() => createSearchJob(payload))) }
  return { workflowLoading, workflowError, profile, loadProfile, saveProfile, createJob }
}

export function useResearchWorkflows() {
  const workflowLoading = ref(false), workflowError = ref(null)
  async function run(request) { workflowLoading.value = true; workflowError.value = null; try { return Boolean(await request()) } catch (error) { workflowError.value = error; return false } finally { workflowLoading.value = false } }
  const createBatch = payload => run(() => createPublicPoolBatch(payload))
  const reviewTask = (taskId, status) => run(() => reviewResearchTask(taskId, status))
  return { workflowLoading, workflowError, createBatch, reviewTask }
}

export function useCustomerHub(kind) {
  const error = ref(null)
  const lastSuccessfulAt = ref(null)
  const detail = ref(null)
  const detailLoading = ref(false)
  const timeline = ref([])
  const timelineLoading = ref(false)
  const timelineLoadedFor = ref(null)
  const mutatingId = ref(null)
  const detailError = ref(null)
  const timelineError = ref(null)
  const currentCustomerId = ref(null)
  const loading = ref(false)
  let listRequest = 0
  let detailRequest = 0
  let timelineRequest = 0

  const state = useListPage(async params => {
    const requestId = ++listRequest
    loading.value = true
    error.value = null
    try {
      const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value != null))
      const response = await LISTERS[kind](clean)
      if (requestId !== listRequest) return { items: state.list.value, total: state.total.value }
      lastSuccessfulAt.value = new Date()
      return response.data || {}
    } catch (caught) {
      if (requestId === listRequest) error.value = caught
      return { items: state.list.value, total: state.total.value }
    } finally {
      if (requestId === listRequest) loading.value = false
    }
  }, {
    searchForm: kind === 'customers' ? { keyword: '' } : kind === 'acquisition' ? { status: '' } : {},
  })

  const empty = computed(() => !loading.value && !error.value && state.list.value.length === 0)
  const errorGuidance = computed(() => error.value ? '加载失败。请检查网络或权限后重新加载。' : '')
  const staleGuidance = computed(() => {
    if (!error.value || !lastSuccessfulAt.value || state.list.value.length === 0) return ''
    return '当前保留上次成功结果，数据可能已过期。'
  })

  async function loadDetail(id) {
    const requestId = ++detailRequest
    currentCustomerId.value = id
    timelineRequest += 1
    timelineLoading.value = false
    detailError.value = null
    detailLoading.value = true
    detail.value = null
    timeline.value = []
    timelineLoadedFor.value = null
    try {
      const response = await getCustomer(id)
      if (requestId !== detailRequest || currentCustomerId.value !== id) return null
      detail.value = response.data
      return detail.value
    } catch (caught) {
      if (requestId === detailRequest) detailError.value = caught
      return null
    } finally {
      if (requestId === detailRequest) detailLoading.value = false
    }
  }

  async function loadTimeline(customerId) {
    if (!customerId || timelineLoadedFor.value === customerId) return
    const requestId = ++timelineRequest
    timelineError.value = null
    timelineLoading.value = true
    try {
      const response = await listCustomerTimeline(customerId, { page: 1, page_size: 50 })
      if (requestId === timelineRequest && currentCustomerId.value === customerId) {
        timeline.value = response.data?.items || []
        timelineLoadedFor.value = customerId
      }
    } catch (caught) {
      if (requestId === timelineRequest && currentCustomerId.value === customerId) timelineError.value = caught
    } finally {
      if (requestId === timelineRequest && currentCustomerId.value === customerId) timelineLoading.value = false
    }
  }

  async function requeueJob(jobId) {
    mutatingId.value = jobId
    try {
      await requeueSearchJob(jobId)
      await state.fetchList()
    } catch (caught) {
      error.value = caught
      throw caught
    } finally {
      mutatingId.value = null
    }
  }

  async function completeAction(actionId) {
    mutatingId.value = actionId
    try {
      await updateAction(actionId, { operation: 'complete', outcome_code: 'other' })
      await state.fetchList()
    } catch (caught) {
      error.value = caught
      throw caught
    } finally {
      mutatingId.value = null
    }
  }

  return {
    ...state,
    loading,
    empty,
    error,
    errorGuidance,
    staleGuidance,
    detail,
    detailLoading,
    timeline,
    timelineLoading,
    detailError,
    timelineError,
    currentCustomerId,
    mutatingId,
    loadDetail,
    loadTimeline,
    requeueJob,
    completeAction,
  }
}
