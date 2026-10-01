import { computed, onMounted, reactive, ref, watch } from 'vue'
import { getFestivalOrderSummary, listFestivalOrders } from '@/api/festivalOrder'
import { useTableView } from '@/composables/useTableView'

const emptySummary = () => ({
  can_read_all: false,
  users: [],
  selected_user_id: null,
  selected_user_name: null,
  new_sign: { count: 0, target: 0, progress_percent: 0, points: 0 },
  first_return_count: 0,
  repurchase_amount: 0,
})

export function useFestivalOrderDetail() {
  const activeType = ref('new_sign')
  const selectedUserId = ref('')
  const summary = ref(emptySummary())
  const orders = ref([])
  const loading = ref(false)
  const error = ref('')
  const filters = reactive({ keyword: '' })
  const pagination = reactive({ page: 1, page_size: 20, total: 0 })
  let latestRequest = 0

  const scopeParams = () => selectedUserId.value ? { user_id: selectedUserId.value } : {}

  function orderParams() {
    return {
      type: activeType.value,
      keyword: filters.keyword || undefined,
      page: pagination.page,
      page_size: pagination.page_size,
      ...scopeParams(),
    }
  }

  async function loadPage({ refreshSummary = true } = {}) {
    const requestId = ++latestRequest
    loading.value = true
    error.value = ''
    try {
      if (refreshSummary) {
        const [nextSummary, nextPage] = await Promise.all([getFestivalOrderSummary(scopeParams()), listFestivalOrders(orderParams())])
        if (requestId !== latestRequest) return
        summary.value = nextSummary
        orders.value = nextPage.items || []
        pagination.total = nextPage.total || 0
      } else {
        const nextPage = await listFestivalOrders(orderParams())
        if (requestId !== latestRequest) return
        orders.value = nextPage.items || []
        pagination.total = nextPage.total || 0
      }
    } catch (cause) {
      if (requestId !== latestRequest) return
      error.value = cause?.response?.data?.detail || cause?.message || '加载失败，请稍后重试'
    } finally {
      if (requestId === latestRequest) loading.value = false
    }
  }

  function changeScope() {
    pagination.page = 1
    loadPage()
  }

  function changeType() {
    pagination.page = 1
    loadPage({ refreshSummary: false })
  }

  function search() {
    pagination.page = 1
    loadPage({ refreshSummary: false })
  }

  function resetFilters() {
    filters.keyword = ''
    pagination.page = 1
    loadPage({ refreshSummary: false })
  }

  function handleSizeChange() {
    pagination.page = 1
    loadPage({ refreshSummary: false })
  }

  function changePage() {
    loadPage({ refreshSummary: false })
  }

  // 列配置元数据：TableTools 列显隐面板的数据源（推广期模板列保持静态，不改 v-for 渲染）
  const columnDefs = [
    { key: 'order-no', label: '订单号' },
    { key: 'account-date', label: '记账日期' },
    { key: 'amount-usd', label: '金额（USD）' },
    { key: 'company-name', label: '客户名称' },
    { key: 'user-name', label: '业务员' },
    { key: 'team', label: '所属团队' },
    { key: 'camp', label: '所属阵营' },
    { key: 'points', label: '积分' },
  ]
  // 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
  const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
    useTableView('festival-order-detail', columnDefs)
  const currentColumnDefs = computed(() => activeType.value === 'new_sign'
    ? columnDefs : columnDefs.filter(column => column.key !== 'points'))
  watch(currentColumnDefs, columns => {
    if (!columns.some(column => visibleKeys.value.includes(column.key))) {
      visibleKeys.value = [...visibleKeys.value, columns[0].key]
    }
  }, { immediate: true })

  onMounted(loadPage)
  return {
    activeType, changePage, changeScope, changeType, error, filters, loadPage,
    loading, orders, pagination, search, selectedUserId, summary,
    resetFilters, handleSizeChange,
    columnDefs, currentColumnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen,
  }
}
