export function proposalNotice(order) {
  if (!['awaiting_customer', 'ready_for_review'].includes(order.status) || !order.proposal) return ''
  if (order.proposal.expired) return '当前提案已过期，建 PI 前需要重新确认。'
  return order.proposal.accepted ? '客户已接受当前提案，等待最终审核。' : '当前提案等待客户确认。'
}

export function piNotice(order) {
  if (order.status !== 'invoice_created') return ''
  return ({ current: '当前 PI 已确认并发布。', voided: 'PI 已作废。下方为最近发布的历史快照。', withdrawn: 'PI 已撤回，修改内容尚未重新发布。下方为最近发布的历史快照。', pending_customer: 'PI 修改提案等待客户确认。下方为最近发布的历史快照。', accepted: '客户已接受 PI 修改，尚待发布。下方为最近发布的历史快照。', rejected: '客户已拒绝 PI 修改。下方为最近发布的历史快照。' })[order.pi_amendment?.status] || '当前 PI 状态待核实。下方金额不作为当前有效 PI 的证明。'
}

export function snapshotTitle(order) {
  if (order.status === 'invoice_created') return '最近发布的商品快照'
  return order.proposal?.accepted ? '客户已确认的商品信息' : '当前请求 / 提案商品信息'
}
