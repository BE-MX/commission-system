export const deliveryStatuses = { queued: '待发送', retry: '等待重试', preparing: '准备中', sending: '发送中', sent: '推送成功', failed: '推送失败', uncertain: '结果不确定', cancelled: '已取消' }
export function deliveryLabel(rows = []) {
  if (!rows.length) return '—'
  const latest = rows[0].source_key
  const statuses = rows.filter(r => r.source_key === latest).map(r => r.status)
  for (const state of ['uncertain', 'failed', 'sending', 'preparing', 'retry', 'queued', 'cancelled']) {
    if (statuses.includes(state)) return deliveryStatuses[state]
  }
  return '推送成功'
}
