<template>
  <div class="decision-table" tabindex="0" :aria-label="caption">
    <table>
      <caption v-if="caption" class="sr-only">{{ caption }}</caption>
      <thead><tr><th v-if="selectable" scope="col">对比</th><th v-for="column in columns" :key="column.key" scope="col" :aria-sort="column.sortable === false ? undefined : ariaSort(column.key)" :class="{ numeric: column.format === 'money' || column.format === 'number' || column.format === 'percent' }"><TableSortHeader v-if="column.sortable !== false" :label="column.label" :order="sortField === column.key ? sortOrder : null" @sort="sortColumn(column.key)" /><span v-else>{{ column.label }}</span></th><th v-if="action" scope="col">操作</th></tr></thead>
      <tbody><tr v-for="(row, index) in visibleRows" :key="row[idKey] ?? index">
        <td v-if="selectable"><input type="checkbox" :checked="selection.includes(row[idKey])" :disabled="!selection.includes(row[idKey]) && selection.length >= 4" :aria-label="`对比 ${row.shop_name || row.name || index + 1}`" @change="$emit('select', row[idKey])"></td>
        <td v-for="column in columns" :key="column.key" :class="{ numeric: ['money', 'number', 'percent'].includes(column.format) }">
          <button v-if="column.link" class="table-link" @click="$emit('open', row)">{{ display(row, column) }}</button>
          <span v-else>{{ display(row, column) }}</span>
        </td>
        <td v-if="action"><GlassButton variant="link" @click="$emit('open', row)">{{ action }}</GlassButton></td>
      </tr><tr v-if="!rows.length"><td :colspan="columns.length + Number(!!action) + Number(selectable)" class="table-empty">{{ emptyText }}</td></tr></tbody>
    </table>
    <div v-if="paginate && rows.length > 20" class="table-pager"><el-pagination layout="total, sizes, prev, pager, next" :page-sizes="[20, 50, 100]" :total="rows.length" v-model:page-size="pageSize" v-model:current-page="page" @size-change="page = 1" /></div>
  </div>
</template>
<script setup>
import { computed, inject, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import TableSortHeader from '@/components/TableSortHeader.vue'
import { useLocalTableSort } from '@/composables/useLocalTableSort'
import { getSortValue } from '@/utils/tableSort'
import { ORDER_STATUS_LABELS } from '@/api/domestic'
import { label, money, number, percent } from '../state'
const props = defineProps({ rows: { type: Array, default: () => [] }, columns: { type: Array, default: () => [] }, caption: String, action: String, idKey: { type: String, default: 'id' }, emptyText: { type: String, default: '当前范围暂无记录。可调整时间或筛选条件。' }, paginate: { type: Boolean, default: true }, remoteSort: Boolean, sortState: Object, selectable: Boolean, selection: { type: Array, default: () => [] } })
const emit = defineEmits(['open', 'select', 'sort-change'])
const page = ref(1), pageSize = ref(20)
const dictionaries = inject('decisionDictionaries', null)
const sortAccessors = {}
const { sortField, sortOrder, toggleSort, sortedRows, ariaSort } = useLocalTableSort(() => props.rows, sortAccessors)
watch(() => props.columns, columns => {
  Object.keys(sortAccessors).forEach(key => delete sortAccessors[key])
  columns.forEach(column => { sortAccessors[column.key] = column.get || (row => getSortValue(row, column.key)) })
  sortField.value = ''; sortOrder.value = null; page.value = 1
}, { immediate: true })
watch(() => props.sortState, state => { if (props.remoteSort) { sortField.value = state?.prop || ''; sortOrder.value = state?.order || null } }, { immediate: true })
watch(() => props.rows, () => { page.value = 1 })
const orderedRows = computed(() => props.remoteSort ? props.rows : sortedRows.value)
const visibleRows = computed(() => props.paginate ? orderedRows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value) : orderedRows.value)
function sortColumn(field) {
  toggleSort(field); page.value = 1
  if (props.remoteSort) emit('sort-change', { prop: sortField.value || field, order: sortOrder.value })
}
function display(row, column) {
  const value = column.get ? column.get(row) : column.key.split('.').reduce((data, part) => data?.[part], row)
  if (column.format === 'money') return money(value)
  if (column.format === 'number') return number(value, 1)
  if (column.format === 'percent') return percent(value)
  if (value != null && typeof value === 'object') return Array.isArray(value) ? value.map(label).join('、') : Object.entries(value).map(([key, item]) => `${label(key)} ${label(item)}`).join(' · ')
  const field = column.key.split('.').at(-1), dictionary = dictionaries?.value?.[`domestic_${field}`]
  if (field === 'status' && (row.domestic_no || row.order_kind)) return ORDER_STATUS_LABELS[value] || label(value)
  return dictionary?.find(item => item.value === String(value))?.label || label(value)
}
</script>
