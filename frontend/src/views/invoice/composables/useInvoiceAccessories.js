import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listAccessoryPrices } from '@/api/invoice'
import {
  accessoryDiscount,
  accessoryGross,
  normalizeAccessoryRow,
  calculateAccessoryTotal,
  createLatestRequestGate,
} from './accessoryPricing.js'
import { normalizeDiscount } from './invoiceSettlement.js'

export function useInvoiceAccessories(form) {
  const accessoryOptions = ref([])
  const accessoryLoading = ref(false)
  const hairItems = computed(() => form.items.filter(item => item.product_kind !== 'accessory'))
  const accessoryItems = computed(() => form.items.filter(item => item.product_kind === 'accessory'))
  const hairAmount = computed(() => hairItems.value.reduce(
    (sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.price_per_piece) || 0), 0,
  ))
  const hairDiscount = computed(() => hairItems.value.reduce(
    (sum, row) => sum + normalizeDiscount(row.discount_amount), 0,
  ))
  const accessoryAmount = computed(() => accessoryGross(accessoryItems.value))
  const accessoryDiscountTotal = computed(() => accessoryDiscount(accessoryItems.value))
  const searchGate = createLatestRequestGate()
  const priceGate = createLatestRequestGate()

  function invalidateCustomerContext() {
    searchGate.invalidate()
    priceGate.invalidate()
    accessoryOptions.value = []
    accessoryLoading.value = false
  }

  async function searchAccessoryOptions(keyword = '') {
    const customerId = form.customer_id || ''
    const token = searchGate.issue(customerId)
    accessoryLoading.value = true
    try {
      const result = await listAccessoryPrices({
        keyword: keyword.trim() || undefined,
        customer_id: customerId || undefined,
      })
      if (!searchGate.isCurrent(token, form.customer_id || '')) return
      accessoryOptions.value = (result.items || []).map(option => ({
        ...option,
        customer_price: customerId ? option.customer_price : null,
        _customer_id: customerId,
      }))
    } finally {
      if (searchGate.isCurrent(token, form.customer_id || '')) accessoryLoading.value = false
    }
  }

  function addAccessory() {
    form.items.push(normalizeAccessoryRow())
  }

  function selectAccessory(row, option) {
    if (!option) return
    if (option._customer_id == null || String(option._customer_id) !== String(form.customer_id || '')) {
      ElMessage.warning('客户已变化，请重新搜索并选择配件')
      return
    }
    const id = row.id
    Object.assign(row, normalizeAccessoryRow({
      ...option,
      id,
      quantity: row.quantity,
      discount_amount: row.discount_amount,
      customer_price: form.customer_id ? option.customer_price : null,
    }))
  }

  function removeAccessory(row) {
    const index = form.items.indexOf(row)
    if (index >= 0) form.items.splice(index, 1)
  }

  function updateAccessoryTotal(row) {
    row.discount_amount = normalizeDiscount(row.discount_amount)
    row.total_price = calculateAccessoryTotal(row.quantity, row.price_per_piece, row.discount_amount)
    row.price_source = row.customer_price != null && Number(row.price_per_piece) === Number(row.customer_price)
      ? 'customer_rule'
      : 'manual'
  }

  async function refreshAccessoryPrices() {
    const customerId = form.customer_id || ''
    const token = priceGate.issue(customerId)
    if (!accessoryItems.value.length) return
    try {
      const result = await listAccessoryPrices({ customer_id: customerId || undefined })
      if (!priceGate.isCurrent(token, form.customer_id || '')) return
      const options = result.items || []
      let invalidCount = 0
      for (const row of accessoryItems.value) {
        const option = options.find(item =>
          String(item.product_id) === String(row.product_id)
          && String(item.sku_id) === String(row.sku_id))
        if (!option) {
          row.standard_price = null
          row.customer_price = null
          row.price_source = 'missing_std'
          invalidCount++
          continue
        }
        row.standard_price = Number(option.standard_price)
        row.customer_price = customerId ? Number(option.customer_price) : null
        row.price_per_piece = row.customer_price ?? row.standard_price
        updateAccessoryTotal(row)
      }
      if (invalidCount) {
        ElMessage.warning(`${invalidCount} 条配件价格已失效，请到“价格与产品配置 → 标准价格表”重新配置`)
      }
    } catch {
      // API interceptor already gives the recovery message; keep the transaction snapshot unchanged.
    }
  }

  return {
    accessoryAmount,
    accessoryDiscountTotal,
    accessoryItems,
    accessoryLoading,
    accessoryOptions,
    hairAmount,
    hairDiscount,
    hairItems,
    addAccessory,
    invalidateCustomerContext,
    refreshAccessoryPrices,
    removeAccessory,
    searchAccessoryOptions,
    selectAccessory,
    updateAccessoryTotal,
  }
}
