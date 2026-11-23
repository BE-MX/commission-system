import { invoiceIsLocal } from '@/views/commerce-transition/routeState'
import { msgWarning, msgInfo } from '@/utils/feedback'
import {
  getInvoiceEntryOptions,
  getInvoiceProductOptions,
  matchInvoiceProduct,
  resolveInvoicePrice,
} from '@/api/invoice'
import { calculateLineTotal, normalizeDiscount, snapPriceToRule } from './invoiceSettlement.js'
import { createLatestRequestGate } from './accessoryPricing.js'
import { hasImportedBatch, isBlankInvoiceLine, mapPreviewRowToInvoiceLine } from './useInvoicePasteImport.js'
import { emptyHairRow, normalizeHairRow } from './invoiceEditorState.js'

const OPTIONS_TTL_MS = 30_000
const OPTIONS_CACHE_LIMIT = 32
const lineFilters = row => ({
  model: row.model || undefined,
  color: row.color || undefined,
  size: row.length || undefined,
  unit: row.net_weight_grams || undefined,
})

export function useInvoiceHairItems(form, hairItems, isProduction, entryOptions, groupOptions = {}) {
  const getTargetGroupKey = groupOptions.getTargetGroupKey || (() => '')
  const getSourceItems = groupOptions.getSourceItems || (() => hairItems.value)
  function targetGroupKey() {
    const key = getTargetGroupKey()
    if (key == null) msgWarning('请先选择或新建一个明细分组，再添加产品')
    return key
  }
  const linePriceGates = new WeakMap()
  const lineMatchGates = new WeakMap()
  const optionRequests = new Map()
  const linePriceContext = row => [
    form.customer_id || '', row.product_display || '', row.color || '',
    row.length || '', row.net_weight_grams || '',
  ].join('|')
  const linePriceGate = row => {
    if (!linePriceGates.has(row)) linePriceGates.set(row, createLatestRequestGate())
    return linePriceGates.get(row)
  }
  async function loadEntryOptions() { Object.assign(entryOptions.value, await getInvoiceEntryOptions()) }
  function addBlankLine() {
    const groupKey = targetGroupKey()
    if (groupKey == null) return false
    form.items.push({ ...emptyHairRow(isProduction.value), group_key: groupKey })
    return true
  }
  function copyLine() {
    const groupKey = targetGroupKey()
    if (groupKey == null) return false
    const last = getSourceItems(groupKey).at(-1)
    if (!last) return false
    if (last.matching || last.pricing) {
      msgWarning('请等待产品匹配和取价完成后再复制')
      return false
    }
    const { options, matching, id, created_at, ...data } = last
    const copied = { ...normalizeHairRow(data), group_key: groupKey, created_at: null,
      quantity: last.quantity, discount_amount: last.discount_amount,
      price_per_piece: last.price_per_piece, customer_price: last.customer_price }
    updateLineTotal(copied)
    form.items.push(copied)
    return true
  }
  function removeLine(rowOrIndex) {
    const row = typeof rowOrIndex === 'number' ? hairItems.value[rowOrIndex] : rowOrIndex
    const index = form.items.indexOf(row)
    if (index >= 0) form.items.splice(index, 1)
  }
  // 批量删除按引用过滤：配件行与产品行共用 form.items，只动传入的那些
  function removeLines(rows) {
    const doomed = new Set(rows)
    if (!doomed.size) return
    form.items = form.items.filter(item => !doomed.has(item))
  }
  function requestLineOptions(params, key) {
    const cached = optionRequests.get(key)
    if (cached && (!cached.expiresAt || cached.expiresAt > Date.now())) return cached.promise

    const entry = { expiresAt: 0 }
    entry.promise = getInvoiceProductOptions(params).then(result => {
      entry.expiresAt = Date.now() + OPTIONS_TTL_MS
      return {
        models: result.models || [], colors: result.colors || [],
        sizes: result.sizes || [], units: result.units || [],
        all_models: result.all_models || result.models || [],
        all_colors: result.all_colors || result.colors || [],
        all_sizes: result.all_sizes || result.sizes || [],
        all_units: result.all_units || result.units || [],
      }
    }).catch(() => {
      // API client reports the failure. Allow a retry without interrupting matching.
      if (optionRequests.get(key) === entry) optionRequests.delete(key)
      return null
    })
    optionRequests.delete(key)
    optionRequests.set(key, entry)
    if (optionRequests.size > OPTIONS_CACHE_LIMIT) {
      optionRequests.delete(optionRequests.keys().next().value)
    }
    return entry.promise
  }
  async function loadLineOptions(row) {
    if (invoiceIsLocal(form)) return
    const params = lineFilters(row)
    const key = JSON.stringify(params)
    const options = await requestLineOptions(params, key)
    if (options && !invoiceIsLocal(form) && form.items.includes(row) && key === JSON.stringify(lineFilters(row))) {
      row.options = options
    }
  }
  async function onLineFilterChange(row) {
    if (invoiceIsLocal(form)) return
    const params = lineFilters(row)
    const key = JSON.stringify(params)
    if (!lineMatchGates.has(row)) lineMatchGates.set(row, createLatestRequestGate())
    const gate = lineMatchGates.get(row)
    const token = gate.issue(key)
    const ready = Object.values(params).every(Boolean)
    linePriceGate(row).invalidate()
    Object.assign(row, {
      product_id: null, sku_id: null, product_name: '', product_display: '',
      stock_warning: '', available_stock: null, matching: ready, pricing: false,
    })
    if (!ready) return loadLineOptions(row)
    try {
      const match = matchInvoiceProduct(params)
      void loadLineOptions(row)
      const result = await match
      if (invoiceIsLocal(form) || !form.items.includes(row) || !gate.isCurrent(token, JSON.stringify(lineFilters(row)))) return
      if (!result.is_unique) {
        if ((result.matches || []).length) msgWarning('当前条件匹配到多个产品，请继续确认规格')
        else msgInfo('该组合暂无产品，请在其余下拉的「全部」分组继续调整颜色/长度/克重')
        return
      }
      Object.assign(row, {
        product_id: result.item.product_id, sku_id: result.item.sku_id,
        matching: false,
        stock_warning: result.item.stock_warning || '',
        available_stock: result.item.available_stock == null ? null : Number(result.item.available_stock),
        product_name: result.item.product_name, product_display: result.item.product_display,
      })
      await refreshLinePrice(row)
    } finally {
      if (gate.isCurrent(token)) row.matching = false
    }
  }
  async function onCustomFieldChange(row) {
    row.product_name = ''
    row.stock_warning = ''
    await refreshLinePrice(row)
  }
  async function refreshLinePrice(row) {
    if (invoiceIsLocal(form)) return
    const gate = linePriceGate(row)
    if (!row.product_display || !row.color || !row.length || !row.net_weight_grams) {
      gate.invalidate()
      row.pricing = false
      return
    }
    const token = gate.issue(linePriceContext(row))
    row.pricing = true
    try {
      const result = await resolveInvoicePrice({
        customer_id: form.customer_id || undefined, product_display: row.product_display,
        length: row.length, unit: row.net_weight_grams, color: row.color,
      })
      if (invoiceIsLocal(form) || !form.items.includes(row) || !gate.isCurrent(token, linePriceContext(row))) return
      row.standard_price = result.standard_price == null ? null : Number(result.standard_price)
      row.customer_price = result.customer_price == null ? null : Number(result.customer_price)
      row.color_type_source = result.color_type_source || ''
      if (row.customer_price != null) {
        if (!row._importBatchFingerprint) row.price_per_piece = row.customer_price
        row.price_source = Number(row.price_per_piece) === row.customer_price ? 'customer_rule' : 'manual'
      } else row.price_source = 'missing_std'
      updateLineTotal(row)
    } finally {
      if (gate.isCurrent(token)) row.pricing = false
    }
  }
  function updateLineTotal(row) { row.total_price = calculateLineTotal(row.quantity, row.price_per_piece, row.discount_amount) }
  function onPriceInput(row) {
    row.price_per_piece = snapPriceToRule(row.price_per_piece, row.customer_price)
    if (row.customer_price != null) row.price_source = Number(row.price_per_piece) === row.customer_price ? 'customer_rule' : 'manual'
    updateLineTotal(row)
  }
  function onLineDiscountChange(row) {
    row.discount_amount = normalizeDiscount(row.discount_amount)
    updateLineTotal(row)
  }
  function appendImportedLines(rows, fingerprint) {
    const groupKey = targetGroupKey()
    if (groupKey == null) return false
    if (hasImportedBatch(form.items, fingerprint)) return false
    for (let i = form.items.length - 1; i >= 0; i--) {
      if (form.items[i].group_key === groupKey && isBlankInvoiceLine(form.items[i])) form.items.splice(i, 1)
    }
    form.items.push(...rows.map(row => ({
      ...normalizeHairRow(mapPreviewRowToInvoiceLine(row, fingerprint, form.order_type)),
      group_key: groupKey,
    })))
    return true
  }
  return {
    addBlankLine, copyLine, appendImportedLines, loadEntryOptions, loadLineOptions, onCustomFieldChange,
    onLineDiscountChange, onLineFilterChange, onPriceInput, refreshLinePrice, removeLine, removeLines,
    updateLineTotal,
  }
}
