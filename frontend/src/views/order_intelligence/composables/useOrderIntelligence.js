import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  generateOrderAiBrief,
  getActiveOrderAiBrief,
  getCountryAnalysis,
  getCustomerActions,
  getCustomerProfileAnalysis,
  getLatestOrderAiBrief,
  getOrderAiBriefStatus,
  getOrderIntelligenceFilters,
  getOrderOverview,
  getPeopleAnalysis,
} from '@/api/orderIntelligence'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useListPage } from '@/composables/useListPage'
import { clearListResource } from '@/composables/useListResourceScope'
import { currentBeijingDate, formatBeijingDate } from '@/utils/datetime'

const today = () => currentBeijingDate()
const oneYearAgo = () => {
  return formatBeijingDate(new Date(Date.now() - 364 * 86400000))
}

export function useOrderIntelligence() {
  const activeTab = ref('overview')
  const peopleDimension = ref('user')
  const aiLoading = ref(false)
  const filters = reactive({
    dateRange: [oneYearAgo(), today()],
    team: '',
    user_id: '',
    countryPaths: [],
    models: [],
    colors: [],
    sources: [],
  })
  const copy = value => JSON.parse(JSON.stringify(value))
  const initialFilters = copy(filters)
  const appliedFilters = ref(copy(filters))
  const hasPendingAnalysis = computed(() => JSON.stringify(filters) !== JSON.stringify(appliedFilters.value))
  const readConfig = context => ({ signal: context.signal, suppressToast: true })
  const optionsResource = useAsyncResource((params, context) => getOrderIntelligenceFilters(params, readConfig(context)))
  const overviewResource = useAsyncResource((params, context) => getOrderOverview(params, readConfig(context)))
  const countriesResource = useAsyncResource((params, context) => getCountryAnalysis(params, readConfig(context)))
  const peopleResource = useAsyncResource((params, context) => getPeopleAnalysis(params, readConfig(context)))
  const profilesResource = useAsyncResource((params, context) => getCustomerProfileAnalysis(params, readConfig(context)))
  const options = computed(() => optionsResource.data.value || {
    can_read_all: false, teams: [], users: [], countries: [], country_tree: [], models: [], colors: [], source_categories: [],
  })
  const overview = overviewResource.data
  const countries = computed(() => countriesResource.data.value || { items: [], total: 0 })
  const people = computed(() => peopleResource.data.value || { items: [], total: 0 })
  const profiles = computed(() => profilesResource.data.value || { items: [], total: 0, summary: {}, definitions: {} })
  const customerMeta = ref({})
  const customerState = useListPage(async (params, context) => {
    const query = baseParams()
    const data = await getCustomerActions({ ...query, ...params, as_of: query.date_to,
      risk_status: params.risk_status || undefined, country: params.country || undefined }, readConfig(context))
    if (context.isCurrent()) customerMeta.value = { risk_definition: data.risk_definition }
    return data
  }, { immediate: false, searchForm: { risk_status: '', country: '' } })
  const customerFilters = customerState.searchForm
  const customers = reactive({ items: customerState.list, total: customerState.total, page: customerState.page,
    page_size: customerState.pageSize, risk_definition: computed(() => customerMeta.value.risk_definition) })
  const activeResource = computed(() => ({ countries: countriesResource, people: peopleResource, profiles: profilesResource })[activeTab.value])
  const detailLoading = computed(() => activeTab.value === 'customers' ? customerState.loading.value : !!activeResource.value?.loading.value)
  const loading = computed(() => overviewResource.loading.value)
  const aiBrief = ref({ visible: false, job_id: null, status: 'idle', content: '', source: '', error_message: '' })
  let aiPollTimer = null
  let briefVersion = 0

  const scopedUsers = computed(() => filters.team
    ? options.value.users.filter(user => user.team === filters.team)
    : options.value.users)
  const selectedCountries = computed(() => [...new Set(
    appliedFilters.value.countryPaths.map(path => path[path.length - 1]).filter(Boolean),
  )])
  const currentBriefContext = computed(() => ({
    date_from: appliedFilters.value.dateRange?.[0] || '', date_to: appliedFilters.value.dateRange?.[1] || '',
    team: appliedFilters.value.team || '', user_id: appliedFilters.value.user_id || '',
    countries: [...selectedCountries.value].sort(), models: [...appliedFilters.value.models].sort(),
    colors: [...appliedFilters.value.colors].sort(), sources: [...appliedFilters.value.sources].sort(),
  }))
  const briefMatchesFilters = computed(() => {
    const context = aiBrief.value.request_context || {}
    return JSON.stringify({ date_from: aiBrief.value.date_from || '', date_to: aiBrief.value.date_to || '',
      team: context.team || '', user_id: context.user_id || '', countries: [...(context.countries || [])].sort(),
      models: [...(context.models || [])].sort(), colors: [...(context.colors || [])].sort(), sources: [...(context.sources || [])].sort(),
    }) === JSON.stringify(currentBriefContext.value)
  })
  const baseParams = () => ({
    date_from: appliedFilters.value.dateRange?.[0], date_to: appliedFilters.value.dateRange?.[1],
    team: appliedFilters.value.team || undefined, user_id: appliedFilters.value.user_id || undefined,
    countries: selectedCountries.value, models: [...appliedFilters.value.models],
    colors: [...appliedFilters.value.colors], sources: [...appliedFilters.value.sources],
  })
  function loadFilters() {
    const params = baseParams()
    return optionsResource.load({ date_from: params.date_from, date_to: params.date_to })
  }
  function loadActiveDetail() {
    const params = baseParams()
    if (activeTab.value === 'countries') return countriesResource.load(params)
    if (activeTab.value === 'people') return peopleResource.load({ ...params, dimension: peopleDimension.value })
    if (activeTab.value === 'profiles') return profilesResource.load(params)
    if (activeTab.value === 'customers') return customerState.fetchList()
    return Promise.resolve(true)
  }
  function loadPage() {
    return Promise.all([loadFilters(), overviewResource.load(baseParams()), loadActiveDetail()])
  }
  function applyAnalysis() {
    appliedFilters.value = copy(filters)
    for (const [tab, resource] of Object.entries({ countries: countriesResource, people: peopleResource, profiles: profilesResource })) {
      if (activeTab.value !== tab) resource.clear()
    }
    clearListResource(customerState); customerMeta.value = {}
    return loadPage()
  }
  function resetAnalysis() { Object.assign(filters, copy(initialFilters)); return applyAnalysis() }
  const changeTab = () => loadActiveDetail()
  function changeTeam() {
    if (filters.user_id && !scopedUsers.value.some(user => user.user_id === filters.user_id)) filters.user_id = ''
  }
  function changePeopleDimension() {
    peopleResource.clear()
    if (activeTab.value === 'people') return loadActiveDetail()
  }
  const changeCustomerPage = customerState.handlePageChange
  const changeCustomerSize = customerState.handleSizeChange

  function applyBriefJob(job, showDrawer = true) {
    if (!job) return
    aiBrief.value = { ...aiBrief.value, ...job, visible: showDrawer || aiBrief.value.visible }
    aiLoading.value = ['queued', 'running'].includes(job.status)
  }

  function scheduleBriefPoll() {
    if (aiPollTimer || !aiLoading.value || !aiBrief.value.job_id) return
    const version = briefVersion, jobId = aiBrief.value.job_id
    aiPollTimer = setTimeout(async () => {
      aiPollTimer = null
      if (version !== briefVersion || jobId !== aiBrief.value.job_id) return
      try {
        const job = await getOrderAiBriefStatus(jobId)
        if (version !== briefVersion || jobId !== aiBrief.value.job_id) return
        applyBriefJob(job, false)
      } catch (cause) {
        if (version !== briefVersion || jobId !== aiBrief.value.job_id) return
        aiBrief.value.error_message = cause?.response?.data?.detail || cause?.message || '查询简报状态失败'
      }
      if (aiLoading.value) scheduleBriefPoll()
    }, 3000)
  }

  async function restoreActiveBrief() {
    const version = ++briefVersion
    try {
      const active = await getActiveOrderAiBrief()
      if (version !== briefVersion) return
      const job = active || await getLatestOrderAiBrief()
      if (version !== briefVersion) return
      if (!job) return
      applyBriefJob(job, Boolean(active))
      scheduleBriefPoll()
    } catch (cause) {
      // 页面主数据不应因简报恢复失败而无法使用，等用户主动重试。
      console.warn('restore active order brief failed', cause?.message || cause)
    }
  }

  async function generateBrief(focus = 'executive') {
    if (aiLoading.value) return
    const version = ++briefVersion
    if (aiPollTimer) { clearTimeout(aiPollTimer); aiPollTimer = null }
    aiLoading.value = true
    aiBrief.value = { visible: true, job_id: null, status: 'queued', content: '', source: '', error_message: '' }
    try {
      const job = await generateOrderAiBrief({ ...baseParams(), focus })
      if (version !== briefVersion) return
      applyBriefJob(job)
      scheduleBriefPoll()
    } catch (cause) {
      if (version !== briefVersion) return
      aiBrief.value.status = 'failed'
      aiBrief.value.error_message = cause?.response?.data?.detail || cause?.message || 'AI 简报任务提交失败'
      aiLoading.value = false
    }
  }

  function handleBriefAction() {
    if (aiBrief.value.status === 'succeeded' && aiBrief.value.content && briefMatchesFilters.value) {
      aiBrief.value.visible = true
      return
    }
    generateBrief()
  }

  onMounted(() => { restoreActiveBrief(); loadPage() })
  onBeforeUnmount(() => { briefVersion++; if (aiPollTimer) clearTimeout(aiPollTimer) })

  return {
    activeTab, aiBrief, aiLoading, briefMatchesFilters, changeCustomerPage, changeCustomerSize, changePeopleDimension,
    changeTab, changeTeam, countries, customerFilters, customers, customerState, detailLoading,
    filters, appliedFilters, hasPendingAnalysis, applyAnalysis, resetAnalysis, generateBrief, handleBriefAction, loadPage,
    loading, options, overview, people, peopleDimension, profiles, scopedUsers,
    optionsResource, overviewResource, countriesResource, peopleResource, profilesResource,
  }
}
