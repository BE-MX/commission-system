export function stockRows(snapshot, invoiceId, lines) {
  if (snapshot?.invoice_id !== invoiceId || snapshot.source !== 'okki_live' || !Array.isArray(snapshot.items)) throw new Error('库存回执与当前订单不一致，请刷新库存')
  const result = new Map()
  for (const item of snapshot.items) {
    const row = lines.find(line => line.id === item.invoice_item_id)
    if (!row || result.has(row.id) || String(row.product_id ?? '') !== String(item.product_id ?? '') || String(row.sku_id ?? '') !== String(item.sku_id ?? '')) throw new Error('库存产品映射已变化，请重新打开出库窗口')
    const amount = item.available_stock
    const valid = typeof amount === 'string' && /^(0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(amount)
      && BigInt(amount.split('.')[0]) <= BigInt(Number.MAX_SAFE_INTEGER)
    // Floor the decimal string before Number conversion; 0.999... must never
    // round up to one and permit an extra physical unit.
    result.set(row.id, { available: valid ? amount.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '') : null,
      limit: valid ? Number(amount.split('.')[0]) : 0, reason: item.reason })
  }
  return result
}

export function shipmentQuantityLimit(row, stocks) {
  const stock = stocks.get(row.id)
  return stock?.available == null ? 0 : Math.max(0, Math.min(row.remaining, stock.limit))
}

export function shipmentStockError(lines, stocks) {
  const requested = new Map()
  for (const row of lines.filter(line => line.requested > 0)) {
    const stock = stocks.get(row.id)
    if (stock?.available == null) return '所选产品可用库存待核对，请刷新库存'
    if (!Number.isSafeInteger(row.requested) || row.requested > shipmentQuantityLimit(row, stocks)) return '本批数量不能超过剩余待出库或可用库存，请调整数量'
    const key = String(row.sku_id), previous = requested.get(key)
    if (previous && previous.available !== stock.limit) return '同一 SKU 库存不一致，请刷新库存'
    requested.set(key, { quantity: (previous?.quantity || 0) + row.requested, available: stock.limit })
  }
  return [...requested.values()].some(row => row.quantity > row.available) ? '同一产品本批数量合计超过可用库存，请调整数量' : ''
}

export function fillShipmentQuantities(lines, stocks) {
  const budgets = new Map()
  for (const row of lines) {
    const stock = stocks.get(row.id)
    if (stock?.available == null) continue
    const key = String(row.sku_id), previous = budgets.get(key)
    if (previous && (previous.limit !== stock.limit || previous.product !== String(row.product_id))) previous.invalid = true
    else if (!previous) budgets.set(key, { limit: stock.limit, remaining: stock.limit, product: String(row.product_id) })
  }
  // Use the original order rows, independent of the table's visual sort.
  return lines.map(row => {
    const budget = budgets.get(String(row.sku_id))
    if (stocks.get(row.id)?.available == null || !budget || budget.invalid || !Number.isSafeInteger(row.remaining)) return 0
    const quantity = Math.max(0, Math.min(row.remaining, budget.remaining))
    budget.remaining -= quantity
    return quantity
  })
}
