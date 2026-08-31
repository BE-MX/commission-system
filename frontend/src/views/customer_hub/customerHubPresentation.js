const FIELD_LABELS = {
  legal_name: '法定名称',
  identity: '客户身份',
  business: '业务画像',
  engagement: '互动情况',
  preferences: '客户偏好',
  contacts: '联系人',
  company_name: '公司名称',
  display_name: '客户名称',
  country: '国家/地区',
  country_code: '国家/地区代码',
  primary_market: '主要市场',
  industry: '行业',
  role: '角色',
  name: '姓名',
  email: '邮箱',
  phone: '电话',
  title: '标题',
  products: '产品',
  product: '产品',
  color: '颜色偏好',
  colors: '颜色偏好',
  cadence: '周期',
  action: '建议动作',
  risks: '风险',
  order_summary: '订单摘要',
  order_count: '订单数',
  count: '数量',
  total_amount: '总金额',
  currency: '币种',
  status: '状态',
  source: '来源',
  summary: '摘要',
  description: '说明',
  fact_id: '事实 ID',
  reference_type: '引用类型',
}

export function profileFieldLabel(key) {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key]
  const normalized = String(key).replaceAll('_', ' ')
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

export function getProfileValueKind(value) {
  if (value == null) return 'empty'
  if (Array.isArray(value)) return 'list'
  if (typeof value === 'object') return 'record'
  return 'scalar'
}
