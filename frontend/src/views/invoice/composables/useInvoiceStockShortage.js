import { computed, onScopeDispose, ref, watch } from 'vue'

function numeric(value) {
  if (value == null || typeof value === 'boolean' || String(value).trim() === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function invoiceOutboundStatus(row, snapshot) {
  const saved = row.id != null
  const entry = saved ? snapshot?.items?.find(item => String(item.invoice_item_id) === String(row.id)) : null
  const changedProduct = entry && (String(entry.product_id) !== String(row.product_id) || String(entry.sku_id) !== String(row.sku_id))
  const previousAllocated = numeric(entry?.outbound_quantity)
  const previousShipped = numeric(entry?.shipped_quantity)
  const allocated = !saved ? 0 : changedProduct ? (previousAllocated === 0 ? 0 : null) : previousAllocated
  const shipped = !saved ? 0 : changedProduct ? (previousShipped === 0 ? 0 : null) : previousShipped
  const quantity = numeric(row.quantity)
  const known = allocated != null && shipped != null
  const quantityLabel = quantity == null ? '—' : quantity
  let code = 'unknown'
  let label = '状态待核对'
  if (known && allocated <= 0 && shipped <= 0) {
    code = 'none'
    label = '未加入'
  } else if (known && quantity > 0 && shipped > 0 && shipped >= quantity) {
    code = 'shipped'
    label = `已发货 ${shipped}/${quantityLabel}`
  } else if (known && shipped > 0) {
    code = 'partial'
    label = `已发 ${shipped}/${quantityLabel}`
  } else if (known && allocated > 0) {
    code = 'allocated'
    label = `已加入 ${allocated}/${quantityLabel}`
  }
  return {
    code, label, allocated, shipped, quantity,
    linked: known && (allocated > 0 || shipped > 0),
    references: known && saved && !changedProduct ? (entry?.outbounds || []) : [],
  }
}

export function invoiceStockStatus(row, snapshot) {
  const saved = row.id != null
  const entry = saved ? snapshot?.items?.find(item => String(item.invoice_item_id) === String(row.id)) : null
  const changedProduct = entry && (String(entry.product_id) !== String(row.product_id) || String(entry.sku_id) !== String(row.sku_id))
  const available = numeric(saved && !changedProduct ? entry?.available_stock : row.available_stock)
  // A newly matched SKU has no shipments only when the saved line is known
  // to be unshipped. Never transfer old-SKU shipments onto a replacement SKU.
  const previousShipped = numeric(entry?.shipped_quantity)
  const shipped = !saved ? 0 : changedProduct ? (previousShipped === 0 ? 0 : null) : previousShipped
  const quantity = numeric(row.quantity)
  const remaining = quantity != null && Number.isSafeInteger(quantity) && quantity > 0
    && shipped != null && Number.isSafeInteger(shipped) && shipped >= 0
    ? Math.max(0, quantity - shipped) : null
  const usable = saved && !changedProduct && entry?.order_available_stock != null
    ? numeric(entry.order_available_stock) : available
  return { available, remaining, shortage: remaining > 0 && usable != null && usable < remaining }
}

export function useInvoiceStockShortage(props, loadInventory) {
  const onlyShortage = ref(false)
  const snapshot = ref(null)
  const loading = ref(false)
  const error = ref('')
  let sequence = 0
  const context = () => JSON.stringify([props.invoiceId, props.active,
    props.items.map(row => [row.id, row.product_id, row.sku_id])])
  async function refreshInventory() {
    const request = ++sequence
    const key = context()
    snapshot.value = null
    error.value = ''
    loading.value = false
    if (!props.invoiceId || props.active === false) return
    loading.value = true
    try {
      const result = await loadInventory(props.invoiceId)
      if (request !== sequence || key !== context()) return
      if (String(result?.invoice_id) !== String(props.invoiceId) || !Array.isArray(result.items)) {
        throw new Error('库存回执与当前订单不一致')
      }
      snapshot.value = result
    } catch (cause) {
      if (request === sequence && key === context()) error.value = cause?.message || '库存读取失败，请重试'
    } finally {
      if (request === sequence) loading.value = false
    }
  }
  watch([() => props.items, context], refreshInventory, { immediate: true })
  watch(() => props.invoiceId, () => { onlyShortage.value = false })
  watch(() => props.active, () => { onlyShortage.value = false })
  onScopeDispose(() => { sequence++ })
  const stockStatus = row => {
    const state = invoiceStockStatus(row, snapshot.value)
    if (!row.product_id || !row.sku_id) return state
    const same = props.items.filter(item => String(item.product_id) === String(row.product_id) && String(item.sku_id) === String(row.sku_id))
    const states = same.map(item => invoiceStockStatus(item, snapshot.value))
    const remaining = states.every(item => item.remaining != null) ? states.reduce((sum, item) => sum + item.remaining, 0) : null
    const entry = snapshot.value?.items?.find(item => String(item.product_id) === String(row.product_id) && String(item.sku_id) === String(row.sku_id))
    const usable = numeric(entry?.order_available_stock ?? state.available)
    return { ...state, shortage: remaining > 0 && usable != null && usable < remaining }
  }
  const filteredItems = computed(() => onlyShortage.value ? props.items.filter(row => stockStatus(row).shortage) : props.items)
  const unknownCount = computed(() => props.items.filter(row => {
    const state = stockStatus(row)
    return row.quantity > 0 && (state.remaining == null || (state.remaining > 0 && state.available == null))
  }).length)
  const outboundStatus = row => invoiceOutboundStatus(row, snapshot.value)
  return { onlyShortage, stockStatus, outboundStatus, filteredItems, unknownCount, loading, error, refreshInventory }
}
