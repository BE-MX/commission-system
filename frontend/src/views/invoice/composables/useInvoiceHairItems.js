import { ElMessage } from 'element-plus'
import {
  getInvoiceEntryOptions,
  getInvoiceProductOptions,
  matchInvoiceProduct,
  resolveInvoicePrice,
} from '@/api/invoice'
import { calculateLineTotal, normalizeDiscount } from './invoiceSettlement.js'
import { createLatestRequestGate } from './accessoryPricing.js'
import { hasImportedBatch, mapPreviewRowToInvoiceLine } from './useInvoicePasteImport.js'
import { normalizeHairRow } from './invoiceEditorState.js'

export function useInvoiceHairItems(form, hairItems, isProduction, entryOptions) {
  const linePriceGates = new WeakMap()
  const linePriceContext = row => [
    form.customer_id || '', row.product_display || '', row.color || '',
    row.length || '', row.net_weight_grams || '',
  ].join('|')
  const linePriceGate = row => {
    if (!linePriceGates.has(row)) linePriceGates.set(row, createLatestRequestGate())
    return linePriceGates.get(row)
  }
  async function loadEntryOptions() { Object.assign(entryOptions.value, await getInvoiceEntryOptions()) }
  function addLine() {
    const last = hairItems.value.at(-1)
    if (last) {
      const { options, matching, id, ...data } = last
      form.items.push(normalizeHairRow(data))
    } else {
      form.items.push(normalizeHairRow({ quantity: 1, item_type: isProduction.value ? 'custom' : 'stock' }))
    }
  }
  function removeLine(rowOrIndex) {
    const row = typeof rowOrIndex === 'number' ? hairItems.value[rowOrIndex] : rowOrIndex
    const index = form.items.indexOf(row)
    if (index >= 0) form.items.splice(index, 1)
  }
  async function loadLineOptions(row) {
    const result = await getInvoiceProductOptions({
      model: row.model || undefined, color: row.color || undefined,
      size: row.length || undefined, unit: row.net_weight_grams || undefined,
    })
    row.options = {
      models: result.models || [], colors: result.colors || [],
      sizes: result.sizes || [], units: result.units || [],
    }
  }
  async function onLineFilterChange(row) {
    Object.assign(row, { product_id: null, sku_id: null, product_name: '', product_display: '' })
    await loadLineOptions(row)
    if (!row.model || !row.color || !row.length || !row.net_weight_grams) return
    row.matching = true
    try {
      const result = await matchInvoiceProduct({ model: row.model, color: row.color, size: row.length, unit: row.net_weight_grams })
      if (!result.is_unique) {
        ElMessage.warning((result.matches || []).length ? '当前条件匹配到多个产品，请继续确认规格' : '当前条件未匹配到产品')
        return
      }
      Object.assign(row, {
        product_id: result.item.product_id, sku_id: result.item.sku_id,
        product_name: result.item.product_name, product_display: result.item.product_display,
      })
      await refreshLinePrice(row)
    } finally { row.matching = false }
  }
  async function onCustomFieldChange(row) {
    row.product_name = ''
    if (row.product_display && row.color && row.length && row.net_weight_grams) await refreshLinePrice(row)
  }
  async function refreshLinePrice(row) {
    if (!row.product_display || !row.color || !row.length || !row.net_weight_grams) return
    const context = linePriceContext(row)
    const gate = linePriceGate(row)
    const token = gate.issue(context)
    const result = await resolveInvoicePrice({
      customer_id: form.customer_id || undefined, product_display: row.product_display,
      length: row.length, unit: row.net_weight_grams, color: row.color,
    })
    if (!gate.isCurrent(token, linePriceContext(row))) return
    row.standard_price = result.standard_price == null ? null : Number(result.standard_price)
    row.customer_price = result.customer_price == null ? null : Number(result.customer_price)
    row.color_type_source = result.color_type_source || ''
    if (row.customer_price != null) {
      if (!row._importBatchFingerprint) row.price_per_piece = row.customer_price
      row.price_source = Number(row.price_per_piece) === row.customer_price ? 'customer_rule' : 'manual'
    } else row.price_source = 'missing_std'
    updateLineTotal(row)
  }
  function updateLineTotal(row) { row.total_price = calculateLineTotal(row.quantity, row.price_per_piece, row.discount_amount) }
  function onPriceInput(row) {
    if (row.customer_price != null) row.price_source = Number(row.price_per_piece) === row.customer_price ? 'customer_rule' : 'manual'
    updateLineTotal(row)
  }
  function onLineDiscountChange(row) {
    row.discount_amount = normalizeDiscount(row.discount_amount)
    updateLineTotal(row)
  }
  function appendImportedLines(rows, fingerprint) {
    if (hasImportedBatch(form.items, fingerprint)) return false
    form.items.push(...rows.map(row => normalizeHairRow(mapPreviewRowToInvoiceLine(row, fingerprint, form.order_type))))
    return true
  }
  return {
    addLine, appendImportedLines, loadEntryOptions, loadLineOptions, onCustomFieldChange,
    onLineDiscountChange, onLineFilterChange, onPriceInput, refreshLinePrice, removeLine,
    updateLineTotal,
  }
}
