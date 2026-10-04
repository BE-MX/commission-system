import { computed } from 'vue'

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
  if (form.sort_field && form.sort_order) {
    params.sort_field = form.sort_field
    params.sort_order = form.sort_order
  }
  for (const key of ['keyword', 'customer_name', 'owner_user_id', 'order_kind', ...BUSINESS_FILTERS.map(f => f.key)]) {
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

export function useDomesticOrderFilters(form, getOptions, search, getAppliedForm) {
  const advancedTags = computed(() => {
    const applied = getAppliedForm()
    const tags = []
    if (applied.dateRange?.length === 2) {
      tags.push({ key: 'dateRange', label: `下单日期：${applied.dateRange.join(' 至 ')}` })
    }
    if (applied.order_kind !== 'production') {
      for (const field of BUSINESS_FILTERS) {
        if (!applied[field.key]) continue
        const label = getOptions()[field.options]?.find(o => o.value === applied[field.key])?.label || applied[field.key]
        tags.push({ key: field.key, label: `${field.label}：${label}` })
      }
    }
    return tags
  })
  function removeAdvanced(key) {
    form[key] = key === 'dateRange' ? [] : ''
    return search()
  }
  function resetFilters() {
    Object.assign(form, emptyAdvancedFilters(), { keyword: '', customer_name: '', owner_user_id: '', status: '' })
    return search()
  }
  return { advancedTags, removeAdvanced, resetFilters }
}
