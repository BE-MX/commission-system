import { computed, reactive, ref } from 'vue'

export const BUSINESS_FILTERS = [
  { key: 'order_category', label: '订单类别', options: 'order_categories' },
  { key: 'order_type', label: '订单类型', options: 'order_types' },
  { key: 'order_channel', label: '订单渠道', options: 'order_channels' },
  { key: 'customer_source', label: '客户来源', options: 'customer_sources' },
]

export function emptyAdvancedFilters() {
  return { dateRange: [], ...Object.fromEntries(BUSINESS_FILTERS.map(({ key }) => [key, ''])) }
}

export function buildOrderListParams({ page, page_size, ...form }) {
  const params = { page, page_size }
  for (const key of ['keyword', 'customer_name', 'order_kind', ...BUSINESS_FILTERS.map(f => f.key)]) {
    if (form.order_kind === 'production' && BUSINESS_FILTERS.some(f => f.key === key)) continue
    const value = typeof form[key] === 'string' ? form[key].trim() : form[key]
    if (value) params[key] = value
  }
  if (form.status !== '' && form.status != null) params.status = form.status
  if (form.dateRange?.length === 2) {
    ;[params.date_start, params.date_end] = form.dateRange
  }
  return params
}

export function useDomesticOrderFilters(form, getOptions, search) {
  const advancedVisible = ref(false)
  const draft = reactive(emptyAdvancedFilters())
  const advancedTags = computed(() => {
    const tags = []
    if (form.dateRange?.length === 2) {
      tags.push({ key: 'dateRange', label: `下单日期：${form.dateRange.join(' 至 ')}` })
    }
    if (form.order_kind !== 'production') {
      for (const field of BUSINESS_FILTERS) {
        if (!form[field.key]) continue
        const label = getOptions()[field.options]?.find(o => o.value === form[field.key])?.label || form[field.key]
        tags.push({ key: field.key, label: `${field.label}：${label}` })
      }
    }
    return tags
  })
  function openAdvanced() {
    Object.assign(draft, emptyAdvancedFilters(), ...BUSINESS_FILTERS.map(({ key }) => ({ [key]: form[key] || '' })))
    draft.dateRange = [...(form.dateRange || [])]
    advancedVisible.value = true
  }
  function clearDraft() {
    Object.assign(draft, emptyAdvancedFilters())
  }
  function applyAdvanced() {
    Object.assign(form, draft, { dateRange: [...(draft.dateRange || [])] })
    if (form.order_kind === 'production') BUSINESS_FILTERS.forEach(({ key }) => { form[key] = '' })
    advancedVisible.value = false
    return search()
  }
  function removeAdvanced(key) {
    form[key] = key === 'dateRange' ? [] : ''
    return search()
  }
  function resetFilters() {
    Object.assign(form, emptyAdvancedFilters(), { keyword: '', customer_name: '', status: '' })
    return search()
  }
  return { advancedVisible, draft, advancedTags, openAdvanced, clearDraft, applyAdvanced, removeAdvanced, resetFilters }
}
