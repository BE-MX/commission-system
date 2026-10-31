export const OUTBOUND_STATE_LABELS = {
  ready: '已生成', waiting_stock: '部分库存不足', pending: '等待生成',
  running: '正在处理', retrying: '重新生成中', awaiting_sync: '待同步', failed: '生成失败', uncertain: '待核对',
  local_pending: '待资金放行', local_ready: '待正式出库', local_shipped: '已正式出库',
}
export const OUTBOUND_STATE_TAGS = {
  ready: 'success', waiting_stock: 'warning', retrying: 'warning', failed: 'danger', uncertain: 'warning',
  local_pending: 'warning', local_ready: 'info', local_shipped: 'success',
}
export function outboundPendingHint(state) {
  if (state === 'waiting_stock') return '库存满足后可打印、下载'
  if (state === 'awaiting_sync') return '单据同步后可打印、下载'
  if (state === 'retrying') return '系统正在重新生成，请稍后刷新查看'
  if (state === 'failed' || state === 'uncertain') return '请联系管理员核对'
  return '出库单生成后可打印、下载'
}
