import { computed, onMounted, reactive, ref, watch } from 'vue'
import { getFestivalOrderSummary, listFestivalOrders } from '@/api/festivalOrder'
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { clearListResource } from '@/composables/useListResourceScope'
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
  const scopeParams = () => selectedUserId.value ? { user_id: selectedUserId.value } : {}
  const summaryResource = useAsyncResource(async (params, { signal }) => await getFestivalOrderSummary(params, { signal, suppressToast: true }), { initialData: emptySummary() })
  const summary = summaryResource.data
  const listState = useListPage(async (params, { signal }) => await listFestivalOrders({ ...params, type: activeType.value, ...scopeParams() }, { signal, suppressToast: true }),
    { searchForm: { keyword: '' }, immediate: false })
  const { list: orders, loading, errorMessage: error, searchForm: filters, handleSearch: search, handleReset: resetFilters } = listState
  const pagination = reactive({ page: listState.page, page_size: listState.pageSize, total: listState.total })
  function loadPage({ refreshSummary = true } = {}) {
    return refreshSummary ? Promise.all([summaryResource.load(scopeParams()), listState.fetchList()]) : listState.fetchList()
  }
  function changeScope() {
    clearListResource(listState)
    return Promise.all([summaryResource.load(scopeParams(), { clear: true }), listState.fetchList()])
  }
  function changeType() { clearListResource(listState); return listState.fetchList() }
  function handleSizeChange(size) { return listState.handleSizeChange(size) }
  function changePage(page) { return listState.handlePageChange(page) }

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
    listState, summaryResource, activeType, changePage, changeScope, changeType, error, filters, loadPage,
    loading, orders, pagination, search, selectedUserId, summary,
    resetFilters, handleSizeChange,
    columnDefs, currentColumnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen,
  }
}
