/**
 * 列表页编排 composable（2026-07-03 治理 F-2）。
 *
 * 统一加载状态、已提交查询、分页和操作后的刷新，新列表页必须使用（宪法 14）。
 * 与 useTableSort / useTableMaxHeight 自由组合；标杆用例：views/expo/ExpoLeads.vue。
 *
 * @param {Function} fetchFn async (params, { signal, isCurrent }) => ({ items, total })
 *   调用方负责适配响应、传递 signal；域元数据赋值须先判断 isCurrent()。
 *   自行展示列表错误的 API 请求应 suppressToast，认证失效仍由拦截器处理。
 * @param {Object}   options  { pageSize=20, immediate=true, searchForm={} }
 */
import { computed, getCurrentInstance, onMounted, onUnmounted, reactive, readonly, ref } from 'vue'
import { errorMessage as listErrorMessage } from '../utils/errors.js'

const copy = value => JSON.parse(JSON.stringify(value))

export function useListPage(fetchFn, options = {}) {
  const { pageSize: initialPageSize = 20, immediate = true, searchForm: initialForm = {} } = options

  const loading = ref(false)
  const list = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(initialPageSize)
  const initialSnapshot = copy(initialForm)
  const searchForm = reactive(copy(initialSnapshot))
  const appliedSearchForm = ref(copy(initialSnapshot))
  const appliedSort = ref(copy(options.sortParams || {}))
  const error = ref(null)
  const errorMessage = computed(() => error.value ? listErrorMessage(error.value) : '')
  const hasLoaded = ref(false)
  const hasData = computed(() => list.value.length > 0)
  const isEmpty = computed(() => hasLoaded.value && !loading.value && !error.value && !hasData.value)
  const isStale = computed(() => hasLoaded.value && !!error.value)
  const hasPendingSearch = computed(() => JSON.stringify(searchForm) !== JSON.stringify(appliedSearchForm.value))
  // Retained rows can belong to a different page after a failed query/page change.
  const dataPage = ref(1)
  let latestRequest = 0
  let activeController

  // A read failure is represented by error + false, not a rejected mutation flow.
  async function fetchList({ adjustPage = false } = {}) {
    const requestId = ++latestRequest
    activeController?.abort()
    const controller = new AbortController()
    activeController = controller
    const isCurrent = () => requestId === latestRequest && !controller.signal.aborted
    const requestedPage = page.value
    const requestedSize = pageSize.value
    loading.value = true
    error.value = null
    try {
      const result = await fetchFn(
        { ...copy(appliedSearchForm.value), ...copy(appliedSort.value), page: requestedPage, page_size: requestedSize },
        { signal: controller.signal, isCurrent },
      )
      if (!isCurrent()) return false
      const resultTotal = result?.total ?? result?.items?.length ?? 0
      const lastPage = Math.max(1, Math.ceil(resultTotal / requestedSize))
      if (adjustPage && requestedPage > lastPage) {
        page.value = lastPage
        return fetchList({ adjustPage: true })
      }
      list.value = result?.items ?? []
      total.value = resultTotal
      dataPage.value = requestedPage
      hasLoaded.value = true
      return true
    } catch (failure) {
      if (isCurrent()) error.value = failure
      return false
    } finally {
      if (isCurrent()) {
        loading.value = false
        activeController = null
      }
    }
  }

  function handleSearch() {
    appliedSearchForm.value = copy(searchForm)
    page.value = 1
    return fetchList()
  }

  function handleReset({ sortParams } = {}) {
    Object.keys(searchForm).forEach(key => { delete searchForm[key] })
    Object.assign(searchForm, copy(initialSnapshot))
    if (sortParams !== undefined) appliedSort.value = copy(sortParams || {})
    return handleSearch()
  }

  function handlePageChange(newPage) {
    page.value = newPage
    return fetchList()
  }

  function handleSizeChange(newSize) {
    pageSize.value = newSize
    page.value = 1
    return fetchList()
  }

  function handleSortChange(sortParams) {
    appliedSort.value = copy(sortParams || {})
    page.value = 1
    return fetchList()
  }

  function refreshCreate({ firstPage = true } = {}) {
    if (firstPage) page.value = 1
    return fetchList({ adjustPage: true })
  }

  const refreshUpdate = () => fetchList({ adjustPage: true })
  const refreshRemove = () => fetchList({ adjustPage: true })
  function cancel() {
    latestRequest += 1
    activeController?.abort()
    loading.value = false
  }

  if (getCurrentInstance()) {
    if (immediate) onMounted(fetchList)
    onUnmounted(cancel)
  }

  return {
    loading, list, total, page, pageSize, searchForm,
    appliedSearchForm: readonly(appliedSearchForm),
    appliedSort: readonly(appliedSort),
    error, errorMessage, hasLoaded, hasData, isEmpty, isStale, hasPendingSearch, dataPage,
    fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange, handleSortChange,
    refreshCreate, refreshUpdate, refreshRemove, cancel,
  }
}
