export const productionStates = { 0: { label: '生产中', type: 'warning' }, 1: { label: '已终止', type: 'info' }, 2: { label: '已完工', type: 'success' } }
export const qualityLabels = { sellable: '合格', quarantine: '待检', damaged: '损坏' }
export const productionActions = {
  complete: { label: '登记完工', permission: 'production:admin', hint: '登记本次实际完工件数，库存须通过仓库验收增加。' },
  receive: { label: '验收入库', permission: 'inventory:write', hint: '按本次实物验收数量入库；分配给销售的合格产品会同时预占库存。' },
  supplies: { label: '计划供货', permission: 'production:write', hint: '将未入库生产量计划供给同 SKU 的销售订单。' },
  release: { label: '释放供货', permission: 'production:write', hint: '释放尚未验收入库的计划供货责任，已交付件数保留。' },
  terminate: { label: '终止生产', permission: 'production:admin', hint: '未交付供货及已完工实物须先处理完毕。历史记录保留。' },
  reverse: { label: '冲销验收', permission: 'inventory:admin', hint: '完整冲销这次验收并恢复原供货责任。已使用的库存不能冲销。' },
  issue: { label: '领料', permission: 'semifinished:write', hint: '按实际领用克数扣减半成品库存。' },
  return: { label: '退料', permission: 'semifinished:write', hint: '退回尚未报损的已领物料，增加半成品库存。' },
  loss: { label: '登记损耗', permission: 'semifinished:write', hint: '从已领用物料中记录损耗，不再次扣减库存。' },
}
