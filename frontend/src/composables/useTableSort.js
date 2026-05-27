import { ref, computed } from 'vue'

/**
 * 列表排序 composable
 * 配合 el-table 的 sortable="custom" + @sort-change 使用
 *
 * @param {string} defaultField - 默认排序字段
 * @param {string} defaultOrder - 默认排序方向 ('asc' | 'desc')
 */
export function useTableSort(defaultField = '', defaultOrder = '') {
  const sortField = ref(defaultField)
  const sortOrder = ref(defaultOrder)

  function onSortChange({ prop, order }) {
    if (!order) {
      sortField.value = ''
      sortOrder.value = ''
    } else {
      sortField.value = prop
      sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
    }
  }

  function reset() {
    sortField.value = ''
    sortOrder.value = ''
  }

  const sortParams = computed(() => {
    if (!sortField.value) return {}
    return {
      sort_field: sortField.value,
      sort_order: sortOrder.value,
    }
  })

  return { sortField, sortOrder, onSortChange, reset, sortParams }
}
