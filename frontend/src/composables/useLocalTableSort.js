import { computed, ref, toValue } from 'vue'
import { sortTableRows } from '../utils/tableSort.js'

/** Only for complete data sets already loaded into memory. */
export function useLocalTableSort(rows, fields = {}) {
  const sortField = ref('')
  const sortOrder = ref(null)
  function toggleSort(field) {
    sortOrder.value = field !== sortField.value || !sortOrder.value ? 'ascending'
      : sortOrder.value === 'ascending' ? 'descending' : null
    sortField.value = sortOrder.value ? field : ''
  }
  const sortedRows = computed(() => sortTableRows(toValue(rows) || [], sortField.value, sortOrder.value, fields[sortField.value]))
  function ariaSort(field) { return field === sortField.value ? sortOrder.value || 'none' : 'none' }
  return { sortField, sortOrder, toggleSort, sortedRows, ariaSort }
}
