import { computed, ref } from 'vue'

export function customerOptionKey(row) {
  return row.option_key || `customer:${row.company_id}`
}

export function customerOptionLabel(row) {
  if (!row) return ''
  const company = row.country_name ? `${row.company_name} (${row.country_name})` : row.company_name
  return row.kind === 'contact' ? `${row.name} — ${company} · 联系人` : `${company} · 客户`
}

export function groupCustomerOptions(options) {
  const groups = new Map()
  for (const row of options) {
    const id = String(row.company_id)
    if (!groups.has(id)) groups.set(id, { company_id: id, company_name: row.company_name, country_name: row.country_name, options: [] })
    const group = groups.get(id)
    if (!group.options.some(option => customerOptionKey(option) === customerOptionKey(row))) group.options.push(row)
  }
  for (const group of groups.values()) group.options.sort((a, b) => Number(a.kind === 'contact') - Number(b.kind === 'contact'))
  return [...groups.values()]
}

export function useVerifiedCustomerSelection({ current, verify, onSelect }) {
  const checking = ref(false)
  const error = ref('')
  const unavailable = ref(new Set())
  let sequence = 0
  const isUnavailable = id => unavailable.value.has(String(id))
  function cancel() { sequence++; checking.value = false; error.value = '' }
  function reset() { cancel(); error.value = ''; unavailable.value = new Set() }
  async function choose(row) {
    const seq = ++sequence
    const previous = current()
    error.value = ''
    checking.value = false
    if (!row) { onSelect(null); return true }
    if (isUnavailable(row.company_id)) {
      error.value = '该客户在小满中已不存在，请选择其他客户或同步最新资料'
      return false
    }
    checking.value = true
    try {
      const result = await verify(row)
      if (seq !== sequence || current() !== previous) return false
      if (String(result?.company_id) !== String(row.company_id)) throw new Error('Unverified customer identity')
      if (result.status === 'missing') {
        unavailable.value = new Set([...unavailable.value, String(row.company_id)])
        error.value = '该客户在小满中已不存在，请选择其他客户或同步最新资料'
        return false
      }
      if (result.status === 'out_of_scope') {
        error.value = '该客户已不在当前业务员私海，请同步最新客户资料后重新搜索'
        return false
      }
      if (result.status !== 'active' || !String(result.company_name || '').trim()) throw new Error('Incomplete customer identity')
      onSelect({ ...row, company_name: result.company_name })
      return true
    } catch {
      if (seq === sequence && current() === previous) error.value = '暂时无法核对小满客户，请重新选择以重试；当前填写内容已保留'
      return false
    } finally {
      if (seq === sequence) checking.value = false
    }
  }
  return { checking, error, isUnavailable, choose, cancel, reset }
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
