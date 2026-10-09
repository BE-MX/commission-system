export function proposalLine(item, existing) {
  if (existing.length >= 100 || existing.some(line => line.item_id === item.item_id)) throw new Error('最多 100 行，同一商品不能重复添加。')
  const minimum = item.min_order_qty, step = item.step_qty
  if (!Number.isInteger(minimum) || minimum < 1 || !Number.isInteger(step) || step < 1) throw new Error('商品数量规则需要复核。')
  const quantity = Math.ceil(minimum / step) * step
  if (quantity > 10000) throw new Error('该商品起订量超过单行上限，请联系管理员复核。')
  const display = item.display_snapshot
  return { item_id: item.item_id, quantity, min_order_qty: quantity, step_qty: step,
    label: `${display.model_name} / ${display.color_name} / ${display.length} / ${display.weight}` }
}

export function validateProposalPreview(result, requestId, version, body, currency) {
  const money = value => typeof value === 'string' && /^(0|[1-9][0-9]*)\.[0-9]{2}$/.test(value)
  const price = value => typeof value === 'string' && /^(0|[1-9][0-9]*)\.[0-9]{4}$/.test(value)
  if (result?.request_id !== requestId || result.row_version !== version || result.currency !== currency || result.binding !== false || result.requires_customer_acceptance !== true || !Array.isArray(result.items) || !Array.isArray(result.changes) || !money(result.total_amount) || !money(result.product_amount)) throw new Error('预览回执不完整，请重新预览。')
  const expected = new Map(body.items.map(line => [line.item_id, line.quantity]))
  if (result.items.length !== expected.size || new Set(result.items.map(line => line.item_id)).size !== expected.size || result.items.some(line => expected.get(line.item_id) !== line.quantity || line.display_snapshot?.item_id !== line.item_id || !price(line.unit_price) || !money(line.line_amount))) throw new Error('预览商品与当前草稿不一致，请重新预览。')
  if (result.changes.some(row => !['added', 'removed', 'changed', 'unchanged'].includes(row.kind) || !Array.isArray(row.changed_fields) || (!row.before && !row.after))) throw new Error('预览差异不完整，请重新预览。')
  return result
}
