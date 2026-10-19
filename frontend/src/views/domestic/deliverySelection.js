/** Keep cross-page quantities and explicit unit choices independent of table rendering. */
export function deliveryUnitPrice(row, selected) {
  const value = selected[row.item_id]?.unit_price
  if (value === undefined) return Number(row.unit_price)
  const text = String(value ?? '').trim()
  if (!/^\d+(\.\d{0,2})?$/.test(text)) return NaN
  const price = Number(text)
  return price <= 999999999999.99 ? price : NaN
}

export function deliveryTotal(rows, selected) {
  return rows.reduce((total, row) => {
    const qty = selected[row.item_id]?.quantity || 0
    total.lines += qty > 0 ? 1 : 0
    total.quantity += qty
    if (qty > 0) total.cents += Math.round(deliveryUnitPrice(row, selected) * 100) * qty
    return total
  }, { lines: 0, quantity: 0, cents: 0 })
}

export function deliveryPayload(rows, selected) {
  return rows.filter(row => selected[row.item_id]?.quantity > 0).map(row => {
    const choice = selected[row.item_id]
    if (!Number.isInteger(choice.quantity) || choice.quantity > row.available_qty) {
      throw new Error(`${row.guest_name || row.line_code} 的本次发货数量超出可发数量`)
    }
    if (choice.unit_ids && (choice.unit_ids.length !== choice.quantity
      || new Set(choice.unit_ids).size !== choice.quantity
      || choice.unit_ids.some(id => !row.units.some(unit => unit.id === id)))) {
      throw new Error('指定单件已变化，请重新选择')
    }
    const unitPrice = deliveryUnitPrice(row, selected)
    if (!Number.isFinite(unitPrice)) throw new Error(`${row.guest_name || row.line_code} 的本批单价须为非负金额，最多两位小数且不超过系统上限`)
    return { item_id: row.item_id, quantity: choice.quantity, unit_ids: choice.unit_ids || null,
      ...(choice.unit_price === undefined ? {} : { unit_price: unitPrice }) }
  })
}

export function filterDeliveryRows(rows, keyword, selected, onlySelected) {
  const needle = keyword.trim().toLocaleLowerCase()
  return rows.filter(row => (!onlySelected || selected[row.item_id]?.quantity > 0)
    && (!needle || [row.guest_name, row.domestic_no, row.order_no, row.line_code, row.product_name]
      .some(value => String(value || '').toLocaleLowerCase().includes(needle))))
}
