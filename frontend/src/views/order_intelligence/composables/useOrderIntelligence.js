import { computed, onMounted, reactive, ref } from 'vue'
import {
  generateOrderAiBrief,
  getCountryAnalysis,
  getCustomerActions,
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
  const filters = reactive({ dateRange: [oneYearAgo(), today()], team: '', user_id: '' })
  const options = reactive({ can_read_all: false, teams: [], users: [], countries: [] })
  const overview = ref(null)
  const countries = ref({ items: [], total: 0 })
  const people = ref({ items: [], total: 0 })
  const customers = ref({ items: [], total: 0, page: 1, page_size: 20 })
  const customerFilters = reactive({ risk_status: '', country: '' })
  const aiBrief = ref({ visible: false, content: '', source: '' })
  let requestVersion = 0

  const scopedUsers = computed(() => filters.team
    ? options.users.filter(user => user.team === filters.team)
    : options.users)
  const baseParams = () => ({
    date_from: filters.dateRange?.[0],
    date_to: filters.dateRange?.[1],
    team: filters.team || undefined,
    user_id: filters.user_id || undefined,
  })
  const scopeParams = () => ({ team: filters.team || undefined, user_id: filters.user_id || undefined })

  async function loadFilters() {
    const data = await getOrderIntelligenceFilters(scopeParams())
    Object.assign(options, data)
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
          ...scopeParams(),
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

  async function generateBrief(focus = 'executive') {
    aiLoading.value = true
    aiBrief.value.visible = true
    aiBrief.value.content = ''
    try {
      const result = await generateOrderAiBrief({ ...baseParams(), focus })
      aiBrief.value.content = result.content || ''
      aiBrief.value.source = result.source || ''
    } catch (cause) {
      aiBrief.value.content = cause?.response?.data?.detail || cause?.message || 'AI 简报生成失败'
      aiBrief.value.source = 'error'
    } finally {
      aiLoading.value = false
    }
  }

  onMounted(async () => {
    try {
      await loadFilters()
      await loadPage()
    } catch (cause) {
      error.value = cause?.response?.data?.detail || cause?.message || '页面初始化失败'
    }
  })

  return {
    activeTab, aiBrief, aiLoading, changeCustomerPage, changePeopleDimension,
    changeTab, changeTeam, countries, customerFilters, customers, detailLoading,
    error, filters, generateBrief, loadPage, loading, options, overview,
    people, peopleDimension, scopedUsers,
  }
}
