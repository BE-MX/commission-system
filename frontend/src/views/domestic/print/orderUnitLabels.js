// Preserve product order and paginate the existing 200-unit API without truncation.
export async function loadOrderUnitLabels(order, fetchUnits, isCurrent = () => true) {
  const groups = []
  const items = [...(order.items || [])].sort((a, b) => a.line_no - b.line_no || a.id - b.id)
  for (const item of items) {
    let count = 0
    const maximum = item.max_unit_no || item.order_qty
    for (let start = 1; start <= maximum; start += 200) {
      if (!isCurrent()) return null
      const end = Math.min(maximum, start + 199)
      const { data } = await fetchUnits(item.id, { start_no: start, end_no: end })
      if (!isCurrent()) return null
      if (data?.order_qty !== item.order_qty || !Array.isArray(data?.units) || (data.max_unit_no && data.max_unit_no !== maximum)) throw new Error('订单数量已变化，请重新打开打印窗口')
      count += data.units.length
      if (data.units.length) groups.push(data)
    }
    if (count !== item.order_qty) throw new Error('订单数量已变化，请重新打开打印窗口')
  }
  if (!groups.length) throw new Error('订单没有可打印的产品')
  return { domestic_no: order.domestic_no, groups }
}
