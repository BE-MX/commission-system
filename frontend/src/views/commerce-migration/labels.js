export const importKinds = {
  catalog: '目录与历史归档', inventory: '库存与半成品期初', orders: '完整订单', finance: '资金与已付提成',
  fulfillment: '历史发货', production: '生产与供货', materials: '原半成品已扣责任', pendingMaterials: '原半成品未决结果核验',
  legacy_settlement: '旧路线责任结清',
}
export const recordKinds = {
  sku: '产品 SKU', order: '订单归档', payment: '回款归档', outbound: '发货归档', inspection: '检验归档', production: '生产归档',
  material: '物料归档', commission: '提成归档', stock_balance: '成品期初', material_balance: '半成品期初',
  payment_opening: '资金期初', order_binding: '完整订单', shipment_opening: '历史履约',
  production_opening: '生产责任', material_allocation: '已领半成品', material_resolution: '原未决物料处置',
}
export const recordRoles = { catalog: '目录映射', archive: '只读历史', opening: '期初责任' }

export function detectImportKind(body) {
  const kinds = new Set()
  for (const key of ['catalog', 'archives']) if (Object.hasOwn(body, key)) kinds.add('catalog')
  for (const key of ['stocks', 'materials']) if (Object.hasOwn(body, key)) kinds.add('inventory')
  if (Object.hasOwn(body, 'payments')) kinds.add('finance')
  if (Object.hasOwn(body, 'productions')) kinds.add('production')
  if (Object.hasOwn(body, 'allocations')) kinds.add('materials')
  if (Object.hasOwn(body, 'resolutions')) kinds.add('pendingMaterials')
  if (Object.hasOwn(body, 'invoices')) kinds.add('legacy_settlement')
  if (Object.hasOwn(body, 'orders')) {
    const rows = body.orders
    kinds.add(Array.isArray(rows) && rows.length && Object.hasOwn(rows[0], 'shipments') ? 'fulfillment' : 'orders')
  }
  if (kinds.size !== 1) throw new Error('清单类型不明确，请使用一份已核验的单类承接清单')
  return [...kinds][0]
}
