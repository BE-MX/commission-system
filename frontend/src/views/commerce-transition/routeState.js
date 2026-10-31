export const routeLabel = value => ({ legacy: '小满流程', local: '方舟独立' }[value] || '待核验')
export const businessLabel = value => ({ draft: '草稿', confirmed: '已确认', partially_shipped: '部分出库', shipped: '已出库', cancelled: '已取消', opening: '承接待放行' }[value] || value || '待核验')
export const shadowLabel = value => ({ consistent: '已覆盖一致', observed: '已观察 · 待独立核对', unknown: '原结果待核对', running: '核对中', differences: '存在差异', incomplete: '覆盖不足', lagging: '对比滞后', not_observed: '尚未观察', blocked: '核对阻塞', queued: '等待核对' }[value] || value || '尚未核对')
export function invoiceIsLocal(invoice) { return (invoice?.transaction_route || invoice?.transaction_mode) === 'local' }
export function routeEditable(invoice) { return !invoice.id || (invoice.capabilities?.change_route === true || invoice.capabilities?.can_change_route === true) }
