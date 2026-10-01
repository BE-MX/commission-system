export const DELIVERY_STATUS = {
  queued: { label: '待发送', tone: 'info' }, retry: { label: '等待重试', tone: 'warning' },
  preparing: { label: '准备中', tone: 'info' }, sending: { label: '发送中', tone: 'warning' },
  sent: { label: '推送成功', tone: 'success' }, failed: { label: '推送失败', tone: 'danger' },
  uncertain: { label: '结果不确定', tone: 'warning' }, cancelled: { label: '已取消', tone: 'info' },
}
export const WEEKLY_STATUS = {
  queued: { label: '待生成', tone: 'info' }, generating: { label: '生成中', tone: 'warning' },
  ready: { label: '已生成', tone: 'success' }, degraded: { label: '目录版本', tone: 'warning' },
  failed: { label: '生成失败', tone: 'danger' },
}
export const deliveryStatuses = Object.fromEntries(Object.entries(DELIVERY_STATUS).map(([code, item]) => [code, item.label]))
export function deliveryLabel(rows = []) {
  if (!rows.length) return '—'
  const latest = rows[0].source_key
  const statuses = rows.filter(r => r.source_key === latest).map(r => r.status)
  for (const state of ['uncertain', 'failed', 'sending', 'preparing', 'retry', 'queued', 'cancelled']) {
    if (statuses.includes(state)) return deliveryStatuses[state]
  }
  return '推送成功'
}
