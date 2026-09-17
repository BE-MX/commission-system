import { computed, ref } from 'vue'

export function customerOptionKey(row) {
  return row.option_key || `customer:${row.company_id}`
}

export function customerOptionLabel(row) {
  if (!row) return ''
  const company = row.country_name ? `${row.company_name} (${row.country_name})` : row.company_name
  return row.kind === 'contact' ? `${row.name} — ${company} · 联系人` : `${company} · 客户`
}

export function useInvoiceCustomerSearch({ request, scope, selected, onBound }) {
  const rows = ref([])
  const loading = ref(false)
  const total = ref(0)
  const hasMore = ref(false)
  let keyword = ''
  let sequence = 0
  const options = computed(() => {
    const current = selected.value
    if (!current || rows.value.some(row => customerOptionKey(row) === customerOptionKey(current))) return rows.value
    return [{ ...current, option_key: customerOptionKey(current) }, ...rows.value]
  })

  function reset() {
    sequence++
    rows.value = []
    total.value = 0
    hasMore.value = false
    loading.value = false
  }

  async function search(value = '', append = false) {
    if (append && (loading.value || !hasMore.value)) return
    if (!append) {
      reset()
      keyword = value || ''
    }
    const seq = ++sequence
    const offset = append ? rows.value.length : 0
    loading.value = true
    try {
      const result = await request({ ...scope(), keyword, offset, limit: 50 })
      if (seq !== sequence) return
      rows.value = append ? [...rows.value, ...result.items] : result.items
      total.value = result.total
      hasMore.value = result.has_more
      if (typeof result.okki_bound === 'boolean') onBound(result.okki_bound)
    } finally {
      if (seq === sequence) loading.value = false
    }
  }

  const findCustomer = id => rows.value.find(row => row.kind === 'customer' && String(row.company_id) === String(id))
  return { options, loading, total, hasMore, search, reset, findCustomer, loadMore: () => search(keyword, true) }
}
