import { computed, reactive, ref, watch } from 'vue'
import { getLibraryCustomers, getLibrarySwatches } from '@/api/colorLibrary'
import { msgError } from '@/utils/feedback'

/** List state for the swatch library page: scope tabs, customer rail and grid filters. */
export function useSwatchLibrary() {
  const scope = ref('private')
  const customers = ref([])
  const customerKeyword = ref('')
  const customerId = ref(null)
  const customersLoading = ref(false)
  const customersError = ref('')

  const swatches = ref([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref('')
  const filters = reactive({ keyword: '', verdict: '', size: '' })

  const currentCustomer = computed(() => customers.value.find((c) => c.customer_id === customerId.value) || null)
  const sizeOptions = computed(() => {
    const set = new Set(swatches.value.map((s) => `${s.size_value}|${s.size_unit}`))
    return [...set].map((key) => {
      const [value, unit] = key.split('|')
      return { key, label: unit === 'inch' ? `${value}″` : `${value} cm`, value: Number(value) }
    }).sort((a, b) => a.value - b.value)
  })
  const visibleSwatches = computed(() => (filters.size
    ? swatches.value.filter((s) => `${s.size_value}|${s.size_unit}` === filters.size)
    : swatches.value))
  const warnCount = computed(() => swatches.value.filter((s) => s.verdict === 'warn').length)

  async function loadCustomers() {
    customersLoading.value = true
    customersError.value = ''
    try {
      const res = await getLibraryCustomers({ keyword: customerKeyword.value || undefined })
      customers.value = res.data?.items || []
      if (!customers.value.some((c) => c.customer_id === customerId.value)) {
        customerId.value = customers.value[0]?.customer_id ?? null
      }
    } catch (err) {
      customersError.value = err?.response?.data?.detail || '客户列表加载失败'
    } finally {
      customersLoading.value = false
    }
  }

  let seq = 0
  async function loadSwatches() {
    if (scope.value === 'private' && !customerId.value) {
      swatches.value = []
      total.value = 0
      return
    }
    const mine = ++seq
    loading.value = true
    error.value = ''
    try {
      const res = await getLibrarySwatches({
        scope: scope.value,
        customer_id: scope.value === 'private' ? customerId.value : undefined,
        keyword: filters.keyword || undefined,
        verdict: filters.verdict || undefined,
        page_size: 200,
      })
      if (mine !== seq) return
      swatches.value = res.data?.items || []
      total.value = res.data?.total || 0
    } catch (err) {
      if (mine !== seq) return
      error.value = err?.response?.data?.detail || '色板加载失败'
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  /** Replace one swatch card after a detail-level change without refetching the grid. */
  function patchSwatch(updated) {
    const idx = swatches.value.findIndex((s) => s.id === updated.id)
    if (idx >= 0) swatches.value.splice(idx, 1, { ...swatches.value[idx], ...updated })
    const cust = customers.value.find((c) => c.customer_id === updated.customer_id)
    if (cust && idx < 0) cust.swatch_count += 1
  }

  function removeSwatch(id) {
    const row = swatches.value.find((s) => s.id === id)
    swatches.value = swatches.value.filter((s) => s.id !== id)
    const cust = row && customers.value.find((c) => c.customer_id === row.customer_id)
    if (cust) cust.swatch_count = Math.max(0, cust.swatch_count - 1)
  }

  let keywordTimer = null
  watch(() => filters.keyword, () => {
    clearTimeout(keywordTimer)
    keywordTimer = setTimeout(loadSwatches, 300)
  })
  watch(() => filters.verdict, loadSwatches)
  watch([scope, customerId], () => {
    filters.size = ''
    loadSwatches()
  })

  let customerTimer = null
  watch(customerKeyword, () => {
    clearTimeout(customerTimer)
    customerTimer = setTimeout(loadCustomers, 300)
  })

  async function init() {
    try {
      await loadCustomers()
      await loadSwatches()
    } catch (err) {
      msgError('色板库加载失败', err)
    }
  }

  return {
    scope, customers, customerKeyword, customerId, customersLoading, customersError, currentCustomer,
    swatches, visibleSwatches, total, loading, error, filters, sizeOptions, warnCount,
    loadCustomers, loadSwatches, patchSwatch, removeSwatch, init,
  }
}
