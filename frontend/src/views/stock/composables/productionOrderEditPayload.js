// 生产订单编辑：明细行状态判断与保存载荷组装（纯函数，供弹窗与测试共用）。

export function isLineChanged(line) {
  if (line.id === null || line.deleted) return true
  if (!line.editable) return false
  return Boolean(line.product) || line.quantity !== line.originalQuantity
}

export function buildEditPayload(order, form, lines) {
  const payload = { item_updates: [], new_items: [] }
  if (form.batch_no !== order.batch_no) payload.batch_no = form.batch_no
  if (form.status !== order.status) payload.status = form.status
  if (form.remark !== (order.remark || '')) payload.remark = form.remark
  if (!order.items_editable) return { payload }

  const deleted = []
  for (const line of lines) {
    if (!isLineChanged(line)) continue
    if (line.deleted) {
      deleted.push({ item_id: line.id, expected_order_qty: line.originalQuantity })
      continue
    }
    if (line.id === null && !line.product) return { error: '请选择新增产品的型号', line }
    if (!Number.isInteger(line.quantity) || line.quantity < Math.max(1, line.receivedQty) || line.quantity > 999999) {
      return { error: '请填写有效的下单数量', line }
    }
    const productId = line.product?.product_id_text
    if (line.id === null) payload.new_items.push({ product_id: productId, order_qty: line.quantity })
    else payload.item_updates.push({
      item_id: line.id, expected_order_qty: line.originalQuantity,
      order_qty: line.quantity, ...(productId ? { product_id: productId } : {}),
    })
  }
  if (deleted.length) payload.deleted_items = deleted
  return { payload }
}

export function payloadChangesItems(payload) {
  return Boolean(payload.item_updates.length || payload.new_items.length || payload.deleted_items?.length)
}
