/**
 * 列表页编排 composable（2026-07-03 治理 F-2）。
 *
 * 统一 loading / 分页 / 搜索 / 重置 的样板逻辑，新列表页必须使用（宪法 14 配套）。
 * 与 useTableSort / useTableMaxHeight 自由组合；标杆用例：views/expo/ExpoLeads.vue。
 *
 * @param {Function} fetchFn  async ({ page, page_size, ...searchForm }) => ({ items, total })
 *                            —— 调用方负责把接口响应适配成 { items, total }
 * @param {Object}   options  { pageSize=20, immediate=true, searchForm={} }
 */
import { onMounted, reactive, ref } from 'vue'

export function useListPage(fetchFn, options = {}) {
  const { pageSize: initialPageSize = 20, immediate = true, searchForm: initialForm = {} } = options

  const loading = ref(false)
  const list = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(initialPageSize)
  const searchForm = reactive({ ...initialForm })
  const initialSnapshot = JSON.parse(JSON.stringify(initialForm))

  async function fetchList() {
    loading.value = true
    try {
      const result = await fetchFn({ page: page.value, page_size: pageSize.value, ...searchForm })
      list.value = result?.items ?? []
      total.value = result?.total ?? list.value.length
    } finally {
      loading.value = false
    }
  }

  function handleSearch() {
    page.value = 1
    return fetchList()
  }

  function handleReset() {
    Object.keys(searchForm).forEach(k => { searchForm[k] = initialSnapshot[k] })
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

  if (immediate) onMounted(fetchList)

  return {
    loading, list, total, page, pageSize, searchForm,
    fetchList, handleSearch, handleReset, handlePageChange, handleSizeChange,
  }
}
