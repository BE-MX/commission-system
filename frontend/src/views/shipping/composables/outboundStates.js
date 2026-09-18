export const OUTBOUND_STATE_LABELS = {
  ready: '已生成', waiting_stock: '部分库存不足', pending: '等待生成',
  running: '正在处理', awaiting_sync: '待同步', failed: '生成失败', uncertain: '待核对',
}
export const OUTBOUND_STATE_TAGS = {
  ready: 'success', waiting_stock: 'warning', failed: 'danger', uncertain: 'warning',
}
export function outboundPendingHint(state) {
  if (state === 'waiting_stock') return '库存满足后可打印、下载'
  if (state === 'awaiting_sync') return '单据同步后可打印、下载'
  if (state === 'failed' || state === 'uncertain') return '请联系管理员核对'
  return '出库单生成后可打印、下载'
}
