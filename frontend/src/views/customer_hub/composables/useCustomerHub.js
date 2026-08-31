import { computed, ref } from 'vue'
import { useListPage } from '@/composables/useListPage'
import { createLatestResource, createMutationController, createPagedResource } from '../customerHubResources'
import {
  createPublicPoolBatch,
  createSearchJob,
  getCustomer,
  getResearchTask,
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
  updateOpportunity,
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
  const mutation = createMutationController(request => request())
  const profileResource = createLatestResource(getAcquisitionProfile)
  async function run(request) {
    workflowLoading.value = true
    workflowError.value = null
    const result = await mutation.submit(request)
    workflowLoading.value = mutation.loading
    workflowError.value = mutation.error
    return result
  }
  async function loadProfile() {
    workflowLoading.value = true
    await profileResource.load('acquisition-profile')
    workflowLoading.value = profileResource.loading
    workflowError.value = profileResource.error
    profile.value = profileResource.data
    return { ok: !profileResource.error, data: profileResource.data, error: profileResource.error }
  }
  async function saveProfile(payload) { return run(() => saveAcquisitionProfile(payload)) }
  async function createJob(payload) { return run(() => createSearchJob(payload)) }
  return { workflowLoading, workflowError, profile, loadProfile, saveProfile, createJob }
}

export function useResearchWorkflows() {
  const workflowLoading = ref(false), workflowError = ref(null)
  const detail = ref(null), detailLoading = ref(false), detailError = ref(null), detailTaskId = ref(null)
  const mutation = createMutationController(request => request())
  const detailResource = createLatestResource(getResearchTask)
  async function run(request) {
    workflowLoading.value = true
    workflowError.value = null
    const result = await mutation.submit(request)
    workflowLoading.value = mutation.loading
    workflowError.value = mutation.error
    return result
  }
  const createBatch = payload => run(() => createPublicPoolBatch(payload))
  const reviewTask = (taskId, status) => run(() => reviewResearchTask(taskId, status))
  async function loadTaskDetail(taskId) {
    detailTaskId.value = taskId
    detail.value = null
    detailError.value = null
    detailLoading.value = true
    await detailResource.load(taskId)
    detail.value = detailResource.data
    detailError.value = detailResource.error
    detailLoading.value = detailResource.loading
    return detail.value
  }
  async function retryTaskDetail() {
    if (!detailTaskId.value) return null
    detailError.value = null
    detailLoading.value = true
    await detailResource.retry()
    detail.value = detailResource.data
    detailError.value = detailResource.error
    detailLoading.value = detailResource.loading
    return detail.value
  }
  return { workflowLoading, workflowError, createBatch, reviewTask, detail, detailLoading, detailError, detailTaskId, loadTaskDetail, retryTaskDetail }
}

export function useOpportunityWorkflow() {
  const workflowLoading = ref(false), workflowError = ref(null)
  async function submit(opportunityId, payload) {
    if (workflowLoading.value) return false
    workflowLoading.value = true; workflowError.value = null
    try { await updateOpportunity(opportunityId, payload); return true }
    catch (error) { workflowError.value = error; return false }
    finally { workflowLoading.value = false }
  }
  return { workflowLoading, workflowError, submit }
}

export function useRadarWorkflow() {
  const workflowLoading = ref(false), workflowError = ref(null)
  async function submit(actionId, payload) {
    if (workflowLoading.value) return false
    workflowLoading.value = true; workflowError.value = null
    try { await updateAction(actionId, payload); return true }
    catch (error) { workflowError.value = error; return false }
    finally { workflowLoading.value = false }
  }
  return { workflowLoading, workflowError, submit }
}

export function useCustomerHub(kind) {
  const error = ref(null)
  const lastSuccessfulAt = ref(null)
  const detail = ref(null)
  const detailLoading = ref(false)
  const timeline = ref([])
  const timelineTotal = ref(0)
  const timelineLoading = ref(false)
  const timelineLoadedFor = ref(null)
  const mutatingId = ref(null)
  const detailError = ref(null)
  const timelineError = ref(null)
  const currentCustomerId = ref(null)
  const loading = ref(false)
  const listResource = createPagedResource(params => LISTERS[kind](params))
  const detailResource = createLatestResource(getCustomer)
  const timelineResource = createLatestResource(customerId => listCustomerTimeline(customerId, { page: 1, page_size: 50 }))

  const state = useListPage(async params => {
    loading.value = true
    const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value != null))
    await listResource.load(clean)
    loading.value = listResource.loading
    error.value = listResource.error
    if (!listResource.error) {
      lastSuccessfulAt.value = new Date()
    }
    return { items: listResource.items, total: listResource.total }
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
    currentCustomerId.value = id
    timelineResource.invalidate()
    timelineLoading.value = false
    detailError.value = null
    detailLoading.value = true
    detail.value = null
    timeline.value = []
    timelineTotal.value = 0
    timelineLoadedFor.value = null
    await detailResource.load(id)
    detail.value = detailResource.data
    detailError.value = detailResource.error
    detailLoading.value = detailResource.loading
    return detail.value
  }

  async function loadTimeline(customerId) {
    if (!customerId || timelineLoadedFor.value === customerId) return
    timelineError.value = null
    timelineLoading.value = true
    await timelineResource.load(customerId)
    if (timelineResource.key === customerId && currentCustomerId.value === customerId) {
      timeline.value = timelineResource.data?.items || []
      timelineTotal.value = timelineResource.data?.total ?? timeline.value.length
      timelineError.value = timelineResource.error
      timelineLoading.value = timelineResource.loading
      if (!timelineResource.error) timelineLoadedFor.value = customerId
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
    timelineTotal,
    timelineLoading,
    detailError,
    timelineError,
    currentCustomerId,
    mutatingId,
    loadDetail,
    loadTimeline,
    requeueJob,
  }
}
