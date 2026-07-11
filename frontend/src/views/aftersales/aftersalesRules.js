export const STATUS_LABELS = {
  draft: '草稿',
  ai_analyzing: 'AI 分析中',
  ai_failed: 'AI 分析失败',
  awaiting_sales_decision: '待选择措施',
  awaiting_evidence_waiver: '待主管确认取证豁免',
  awaiting_supervisor: '待主管初审',
  awaiting_director: '待总监终审',
  returned: '已退回补充',
  rejected: '已拒绝',
  approved: '审批完成',
  processing: '处理中',
  closed: '已关闭',
  cancelled: '已作废',
}

const EDITABLE = new Set(['draft', 'ai_failed', 'awaiting_sales_decision', 'returned'])
const COPYABLE = new Set(['approved', 'processing', 'closed'])

export function canEditCase(status) {
  return EDITABLE.has(status)
}

export function canCopyReply(status) {
  return COPYABLE.has(status)
}

export function compensationRatio(compensation, goodsValue) {
  const cost = Number(compensation)
  const value = Number(goodsValue)
  if (!Number.isFinite(cost) || !Number.isFinite(value) || value <= 0) return '—'
  return `${((cost / value) * 100).toFixed(1)}%`
}

export function validateEnglishReply(hasCompensation, reply) {
  if (!String(reply || '').trim()) return '请填写英文客户回复话术'
  if (hasCompensation && !String(reply).toLowerCase().includes('subject to final internal approval')) {
    return '赔偿话术必须包含 subject to final internal approval'
  }
  return ''
}

const ACTION_REPLY_PHRASES = {
  explanation: 'provide a clear explanation of the product characteristics and expected performance',
  care_guidance: 'share tailored care guidance to help prevent the issue from recurring',
  return_inspection: 'ask you to return the affected product for inspection before we confirm the final solution',
  paid_rework: 'arrange a paid rework service after confirming the service fee and shipping details with you',
  free_rework: 'arrange rework at our cost',
  replacement: 'arrange a replacement for the affected product',
  resend: 'resend the affected quantity',
  cash_refund: 'provide a refund for the approved amount',
  discount: 'provide an agreed discount',
  order_credit: 'apply an approved credit to a future order',
  freight_subsidy: 'cover the approved freight cost',
  custom: 'provide the tailored solution described by your account manager',
}

const COMPENSATION_ACTIONS = new Set([
  'free_rework', 'replacement', 'resend', 'cash_refund', 'discount', 'order_credit', 'freight_subsidy',
])

export function buildEnglishReply(actions = []) {
  const phrases = actions.map(action => ACTION_REPLY_PHRASES[action.code]).filter(Boolean)
  const proposal = phrases.length
    ? phrases.join('; and ')
    : 'confirm the most appropriate next step after reviewing the available evidence'
  const hasCompensation = actions.some(action => (
    COMPENSATION_ACTIONS.has(action.code)
    || (['return_inspection', 'paid_rework'].includes(action.code) && action.freight_payer === 'company')
    || (action.code === 'custom' && action.company_bears_cost)
  ))
  const approvalCaveat = hasCompensation ? ', subject to final internal approval' : ''
  return `Thank you for sharing the details and supporting evidence. We understand your concern and have reviewed the information currently available. Based on this review, we propose to ${proposal}${approvalCaveat}. We will keep you updated on the next steps and timing.`
}

export function validateActionDetails(actions = []) {
  const missing = (action, field, label) => !String(action[field] ?? '').trim() ? `${label}不能为空` : ''
  const positive = (action, field, label) => Number(action[field]) > 0 ? '' : `${label}必须大于 0`
  for (const action of actions) {
    let error = ''
    if (action.code === 'care_guidance') error = missing(action, 'care_plan', '护理方案')
    else if (action.code === 'return_inspection') error = missing(action, 'return_address', '退回地址') || missing(action, 'freight_payer', '运费承担方') || missing(action, 'expected_completion_date', '预计完成日') || (action.freight_payer === 'company' ? positive(action, 'freight_cost_usd', '公司承担运费') : '')
    else if (action.code === 'paid_rework') error = positive(action, 'service_fee_usd', '二次处理费') || missing(action, 'freight_payer', '运费承担方') || (action.freight_payer === 'company' ? positive(action, 'freight_cost_usd', '公司承担运费') : '')
    else if (action.code === 'free_rework') error = positive(action, 'estimated_cost_usd', '二次处理估算成本') || (action.freight_cost_usd == null ? '请填写二次处理运费' : '')
    else if (['replacement', 'resend'].includes(action.code)) error = positive(action, 'quantity', '换货/补发数量') || missing(action, 'product', '换货/补发产品') || positive(action, 'estimated_cost_usd', '换货/补发估算成本') || (action.code === 'resend' && action.freight_cost_usd == null ? '请填写补发运费' : '') || missing(action, 'delivery_date', '预计交付日期')
    else if (action.code === 'cash_refund') error = positive(action, 'amount_usd', '退款金额') || missing(action, 'currency', '退款币种')
    else if (action.code === 'discount') error = (Number(action.amount_usd) > 0 || Number(action.discount_percent) > 0 ? '' : '折扣比例或折扣金额必须大于 0') || missing(action, 'applicable_order', '折扣适用订单')
    else if (action.code === 'order_credit') error = positive(action, 'amount_usd', '抵扣金额') || missing(action, 'expiry_date', '抵扣有效期')
    else if (action.code === 'freight_subsidy') error = positive(action, 'amount_usd', '运费补贴金额') || missing(action, 'currency', '运费补贴币种')
    else if (action.code === 'custom') error = missing(action, 'description', '自定义措施说明') || (action.company_bears_cost ? positive(action, 'estimated_cost_usd', '自定义措施估算成本') : '')
    if (error) return error
  }
  return ''
}

export function approvalSteps(caseData = {}) {
  const status = caseData.current_status || 'draft'
  const hasCompensation = Boolean(caseData.has_compensation)
  const sequence = [
    { code: 'draft', label: '登记信息' },
    { code: 'ai', label: 'AI 分析' },
    { code: 'decision', label: '业务选择措施' },
    { code: 'supervisor', label: status === 'awaiting_evidence_waiver' ? '证据豁免确认' : '直属主管初审' },
    { code: 'director', label: hasCompensation ? '销售总监终审' : '无需终审' },
    { code: 'closed', label: '执行并关闭' },
  ]
  const activeIndex = {
    draft: 0,
    ai_analyzing: 1,
    ai_failed: 1,
    awaiting_sales_decision: 2,
    returned: 2,
    awaiting_evidence_waiver: 3,
    awaiting_supervisor: 3,
    awaiting_director: 4,
    approved: 5,
    processing: 5,
    closed: 6,
    rejected: 3,
    cancelled: 0,
  }[status] ?? 0
  return sequence.map((step, index) => {
    let state = index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending'
    if (step.code === 'director' && !hasCompensation) state = activeIndex > 3 ? 'skipped' : 'pending'
    if (status === 'closed') state = 'done'
    return { ...step, state }
  })
}
