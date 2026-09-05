export const operationLabels = { complete: '登记结果', snooze: '延后', dismiss: '忽略', feedback: '仅评价建议' }
export const channelLabels = { alibaba: '阿里巴巴', email: '邮件', whatsapp: 'WhatsApp', phone: '电话', linkedin: '领英', offline: '线下', internal: '内部' }
export const actionLabels = { call: '电话沟通', email: '邮件跟进', message: '消息沟通', meeting: '会议', research: '补充研究', review: '内部复核' }
export const outcomeLabels = { contacted: '已联系', replied: '客户已回复', no_response: '尚未回复', meeting_booked: '已约会议', wrong_contact: '联系人有误', other: '其他' }
export const statusLabels = { pending: '待处理', done: '已完成', completed: '已完成', snoozed: '已延后', dismissed: '已忽略', cancelled: '已取消', contacted: '已联系', replied: '已回复', quoted: '已报价', won: '已成交', lost: '已流失', accepted: '质量已通过', revision_requested: '待修订', rejected: '已驳回' }
export const reasonLabels = { user_dismissed: '暂不执行', duplicate: '重复', no_longer_relevant: '已不适用', wrong_customer: '客户不符', completed_elsewhere: '已在其他渠道完成', policy_suppressed: '策略不适用', other: '其他', order_confirmed: '订单已确认', manual_confirmed: '人工确认成交', no_response: '未回复', price: '价格', product_mismatch: '产品不匹配', timing: '时机未到', competitor: '选择竞争对手', budget: '预算', risk_rejected: '风险不通过', not_qualified: '不符合资格', no_opportunity: '暂无机会', dnc: '禁止联系' }
export const statusLabel = value => statusLabels[value] || value || '待确认'
export const identityLabel = value => ({ verified: '身份已核验', identified: '主体已识别', provisional: '主体待核验', disputed: '身份有争议' }[value] || '主体待核验')
export const researchTypeLabels = { identity_enrichment: '主体信息补充', public_pool: '公海客户研究', high_score_candidate: '高匹配客户研究', full_research: '完整背调' }
export const classificationLabels = { public_business: '公开业务资料', internal_business: '内部业务资料', personal_contact: '个人联系资料', restricted_internal: '受限内部资料' }
export const sourceLabels = { website: '官网', manual: '人工记录', opportunity: '客户机会', qualification: '资格审核', okki: 'OKKI', sales_automation: '获客研究' }
export const factLayerLabels = { source: '信源事实', expressed: '客户表达', observed: '行为观察', inferred: '研究推断', confirmed: '人工确认' }
export const verificationLabels = { unverified: '未核实', candidate: '待核实', verified: '已核实', disputed: '有争议', rejected: '已驳回', superseded: '已替代' }
export function readableValue(value) {
  if (value == null) return '未提供'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map(readableValue).join('；') || '暂无'
  if (typeof value === 'object') return Object.values(value).map(readableValue).join('；') || '暂无'
  return String(value)
}
