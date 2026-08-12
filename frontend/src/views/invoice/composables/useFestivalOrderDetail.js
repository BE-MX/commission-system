import { onMounted, reactive, ref } from 'vue'
import { getFestivalOrderSummary, listFestivalOrders } from '@/api/festivalOrder'

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

  function changePage() {
    loadPage({ refreshSummary: false })
  }

  onMounted(loadPage)
  return {
    activeType, changePage, changeScope, changeType, error, filters, loadPage,
    loading, orders, pagination, search, selectedUserId, summary,
  }
}
