export const orderTypes = { stock: '现货订单', production: '生产订单', presale: '预售订单' }
export const orderStates = {
  opening: { label: '承接待放行', type: 'warning' }, closed: { label: '已结束', type: 'info' },
  draft: { label: '草稿', type: 'info' }, confirmed: { label: '已确认', type: 'success' },
  partially_shipped: { label: '部分出库', type: 'warning' }, shipped: { label: '已出库', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
}
export const commercialSources = {
  alibaba_inquiry: '阿里询盘', alibaba_ecosystem: '阿里生态', social_owned: '自拓社媒',
  social_assigned: '分配社媒', referral: '转介绍', website: '官网', other: '其他', unknown: '未标记',
}
export const settlementStates = {
  awaiting_payment: { label: '待资金核销', type: 'warning' }, ready: { label: '资金已放行', type: 'success' },
  shipped: { label: '已出库', type: 'success' }, cancelled: { label: '已取消', type: 'info' },
}
