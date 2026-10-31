export const paymentStates = {
  registered: { label: '待财务确认', type: 'warning' }, confirmed: { label: '已确认', type: 'success' },
  voided: { label: '已作废', type: 'info' },
}
export const receiptStates = { active: { label: '有效', type: 'success' }, reversed: { label: '已冲回', type: 'info' } }
export const paymentTypes = { bank_transfer: '银行转账', cash: '现金', card: '银行卡', online: '线上付款' }
export const receivableKinds = { goods: '商品及合同费用', freight: '运费' }
export const purposes = { ordinary: '普通 / 批次款', presale_deposit: '预售首款', freight: '运费' }
export const eventActions = {
  register: '登记收款', confirm: '财务确认', void_registration: '作废登记', allocate: '核销应收',
  reverse_allocation: '核销冲回', refund: '实际退款', adjust_receivable: '调整应收',
  receivable_terms: '修改到期日', create_freight: '生成批次运费应收',
}
export const agingBuckets = { undated: '未设到期日', not_due: '未到期', '1_30': '逾期 1–30 天', '31_60': '逾期 31–60 天', '61_90': '逾期 61–90 天', over_90: '逾期超过 90 天', total: '合计' }
export const reconciliationFields = { net_amount: '净到账', allocated_amount: '已核销', bank_charge_total: '分摊费用', refunded_amount: '已退款', allocation_events: '核销事件合计', overdrawn: '余额透支', paid_amount: '应收已核销', adjustment_amount: '应收调整' }
