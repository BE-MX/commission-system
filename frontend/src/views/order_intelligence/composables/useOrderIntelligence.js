import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  generateOrderAiBrief,
  getActiveOrderAiBrief,
  getCountryAnalysis,
  getCustomerActions,
  getLatestOrderAiBrief,
  getOrderAiBriefStatus,
  getOrderIntelligenceFilters,
  getOrderOverview,
  getPeopleAnalysis,
} from '@/api/orderIntelligence'

const isoDate = value => {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const today = () => isoDate(new Date())
const oneYearAgo = () => {
  const value = new Date()
  value.setDate(value.getDate() - 364)
  return isoDate(value)
}

export function useOrderIntelligence() {
  const activeTab = ref('overview')
  const peopleDimension = ref('user')
  const loading = ref(false)
  const detailLoading = ref(false)
  const aiLoading = ref(false)
  const error = ref('')
  const filters = reactive({
    dateRange: [oneYearAgo(), today()],
    team: '',
    user_id: '',
    countryPaths: [],
    models: [],
    colors: [],
    sources: [],
  })
  const options = reactive({
    can_read_all: false,
    teams: [],
    users: [],
    countries: [],
    country_tree: [],
    models: [],
    colors: [],
    source_categories: [],
  })
  const overview = ref(null)
  const countries = ref({ items: [], total: 0 })
  const people = ref({ items: [], total: 0 })
  const customers = ref({ items: [], total: 0, page: 1, page_size: 20 })
  const customerFilters = reactive({ risk_status: '', country: '' })
  const aiBrief = ref({ visible: false, job_id: null, status: 'idle', content: '', source: '', error_message: '' })
  let requestVersion = 0
  let aiPollTimer = null

  const scopedUsers = computed(() => filters.team
    ? options.users.filter(user => user.team === filters.team)
    : options.users)
  const selectedCountries = computed(() => [...new Set(
    filters.countryPaths.map(path => path[path.length - 1]).filter(Boolean),
  )])
  const currentBriefContext = computed(() => ({
    date_from: filters.dateRange?.[0] || '',
    date_to: filters.dateRange?.[1] || '',
    team: filters.team || '',
    user_id: filters.user_id || '',
    countries: [...selectedCountries.value].sort(),
    models: [...filters.models].sort(),
    colors: [...filters.colors].sort(),
    sources: [...filters.sources].sort(),
  }))
  const briefMatchesFilters = computed(() => {
    const context = aiBrief.value.request_context || {}
    const briefContext = {
      date_from: aiBrief.value.date_from || '',
      date_to: aiBrief.value.date_to || '',
      team: context.team || '',
      user_id: context.user_id || '',
      countries: [...(context.countries || [])].sort(),
      models: [...(context.models || [])].sort(),
      colors: [...(context.colors || [])].sort(),
      sources: [...(context.sources || [])].sort(),
    }
    return JSON.stringify(briefContext) === JSON.stringify(currentBriefContext.value)
  })
  const baseParams = () => ({
    date_from: filters.dateRange?.[0],
    date_to: filters.dateRange?.[1],
    team: filters.team || undefined,
    user_id: filters.user_id || undefined,
    countries: selectedCountries.value,
    models: filters.models,
    colors: filters.colors,
    sources: filters.sources,
  })
  const scopeParams = () => ({
    date_from: filters.dateRange?.[0],
    date_to: filters.dateRange?.[1],
  })

  async function loadFilters() {
    const data = await getOrderIntelligenceFilters(scopeParams())
    Object.assign(options, data)
    const availableCountries = new Set(options.countries)
    const availableModels = new Set(options.models)
    const availableColors = new Set(options.colors)
    filters.countryPaths = filters.countryPaths.filter(path => availableCountries.has(path[path.length - 1]))
    filters.models = filters.models.filter(model => availableModels.has(model))
    filters.colors = filters.colors.filter(color => availableColors.has(color))
  }

  async function loadOverview() {
    overview.value = await getOrderOverview(baseParams())
  }

  async function loadActiveDetail() {
    detailLoading.value = true
    try {
      if (activeTab.value === 'countries') {
        countries.value = await getCountryAnalysis(baseParams())
      } else if (activeTab.value === 'people') {
        people.value = await getPeopleAnalysis({ ...baseParams(), dimension: peopleDimension.value })
      } else if (activeTab.value === 'customers') {
        customers.value = await getCustomerActions({
          ...baseParams(),
          date_from: filters.dateRange?.[0],
          as_of: filters.dateRange?.[1],
          risk_status: customerFilters.risk_status || undefined,
          country: customerFilters.country || undefined,
          page: customers.value.page,
          page_size: customers.value.page_size,
        })
      }
    } finally {
      detailLoading.value = false
    }
  }

  async function loadPage() {
    const version = ++requestVersion
    loading.value = true
    error.value = ''
    try {
      await loadFilters()
      await Promise.all([loadOverview(), loadActiveDetail()])
      if (version !== requestVersion) return
    } catch (cause) {
      if (version !== requestVersion) return
      error.value = cause?.response?.data?.detail || cause?.message || '分析加载失败，请稍后重试'
    } finally {
      if (version === requestVersion) loading.value = false
    }
  }

  async function changeTab() {
    error.value = ''
    try {
      await loadActiveDetail()
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause?.message || '明细加载失败'
    }
  }

  function changeTeam() {
    if (filters.user_id && !scopedUsers.value.some(user => user.user_id === filters.user_id)) {
      filters.user_id = ''
    }
  }

  async function changePeopleDimension() {
    if (activeTab.value === 'people') await changeTab()
  }

  async function changeCustomerPage() {
    if (activeTab.value === 'customers') await changeTab()
  }

  function applyBriefJob(job, showDrawer = true) {
    if (!job) return
    aiBrief.value = { ...aiBrief.value, ...job, visible: showDrawer || aiBrief.value.visible }
    aiLoading.value = ['queued', 'running'].includes(job.status)
  }

  function scheduleBriefPoll() {
    if (aiPollTimer || !aiLoading.value || !aiBrief.value.job_id) return
    aiPollTimer = setTimeout(async () => {
      aiPollTimer = null
      try {
        const job = await getOrderAiBriefStatus(aiBrief.value.job_id)
        applyBriefJob(job, false)
      } catch (cause) {
        aiBrief.value.error_message = cause?.response?.data?.detail || cause?.message || '查询简报状态失败'
      }
      if (aiLoading.value) scheduleBriefPoll()
    }, 3000)
  }

  async function restoreActiveBrief() {
    try {
      const active = await getActiveOrderAiBrief()
      const job = active || await getLatestOrderAiBrief()
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
    aiLoading.value = true
    aiBrief.value = { visible: true, job_id: null, status: 'queued', content: '', source: '', error_message: '' }
    try {
      const job = await generateOrderAiBrief({ ...baseParams(), focus })
      applyBriefJob(job)
      scheduleBriefPoll()
    } catch (cause) {
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

  onMounted(async () => {
    try {
      await restoreActiveBrief()
      await loadPage()
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause?.message || '页面初始化失败'
    }
  })
  onBeforeUnmount(() => { if (aiPollTimer) clearTimeout(aiPollTimer) })

  return {
    activeTab, aiBrief, aiLoading, briefMatchesFilters, changeCustomerPage, changePeopleDimension,
    changeTab, changeTeam, countries, customerFilters, customers, detailLoading,
    error, filters, generateBrief, handleBriefAction, loadPage, loading, options, overview,
    people, peopleDimension, scopedUsers,
  }
}
