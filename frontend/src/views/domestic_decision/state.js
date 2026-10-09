export const FIELD_LABELS = { product_type: '产品类型', craft: '工艺', net_color: '网色', size: '尺寸', length: '长度', density: '密度', hair_style_series: '发型系列', color: '颜色', province: '省份', city: '城市', customer_source: '客户来源', store_type: '门店类型', settle_mode: '结算方式', membership_level: '会员等级', order_category: '订单类别', order_type: '订单类型', order_channel: '订单渠道' }
export const METRIC_LABELS = { amount: '金额', quantity: '数量', order_count: '订单数', customer_count: '客户数' }
export const STATUS_LABELS = { todo: '待处理', in_progress: '推进中', done: '已完成', dismissed: '已关闭', queued: '排队中', running: '生成中', succeeded: '已完成', failed: '失败', available: '可用', insufficient_peer_sample: '同群样本不足', sample_accumulating: '样本积累中', active: '活跃', repurchase_window: '复购窗口', delayed: '周期延后', demand_check: '需核实需求', no_system_purchase: '无系统购买记录', not_applicable_credit: '赊销不适用', unknown: '待核验', insufficient_sample: '样本不足', reference: '同群参考', own: '客户自身', prepay: '先充值后下单', credit: '先下单后付款', cap: '头套', piece: '发片', first_observed_purchase_not_verified_new: '系统首次观察，未核验新客', historical_customer_entered_system: '历史客户迁入系统', system_first_purchase_in_confirmed_coverage: '已确认覆盖内系统首购', insufficient_history: '历史不足', baseline_zero: '对照为零', coverage_unknown: '历史覆盖未知' }
Object.assign(STATUS_LABELS, { account_unverified: '账户待核验', insufficient_buying_days: '有效购买日不足', incomplete_90day_history: '90天历史覆盖不足', no_valid_consumption_speed: '缺有效消费速率', refund_adjustment_variation: '退款调整波动较大', same_day_ordering_unknown: '同日先后未知', observed_next_buying_day: '已观察后续购买', not_observed_yet: '尚未观察到购买', peer_reference: '同群参考', individual: '客户自身证据', high: '较强证据', medium: '中等证据', low: '有限证据', limited: '有限样本', pending: '待审核', approved: '已通过', rejected: '已驳回', recharge: '充值', init: '初始化', adjust: '人工调整', order_charge: '订单扣款', order_adjustment: '订单调整', order_refund: '订单退款', level_adjust: '等级调整', business: '业务单', production: '生产单', preference: '常购偏好', observed_purchases: '已观察购买', insufficient_customer_or_support_sample: '共购样本不足' })
export const label = value => STATUS_LABELS[value] || FIELD_LABELS[value] || METRIC_LABELS[value] || (value == null || value === '' ? '—' : String(value))
import { formatMoney } from '../../utils/money.js'
export const number = (value, digits = 0) => formatMoney(value, { precision: digits, locale: 'zh-CN', missing: '—' }).replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1')
export const money = value => formatMoney(value, { precision: 2, currency: 'CNY', currencyDisplay: 'narrowSymbol', locale: 'zh-CN', missing: '—' })
export const percent = value => value == null ? '—' : `${number(value * 100, 1)}%`
export function evidenceRefs(refs, financeAllowed) {
  const types = ['orders', 'order', 'items', 'item', 'reports', ...(financeAllowed ? ['ledger', 'requests', 'request'] : [])]
  const valid = Array.isArray(refs) ? refs.filter(row => row?.id && types.includes(row.type)) : []
  return [...new Map(valid.map(row => [`${row.type}:${row.id}`, row])).values()]
}
export function defaultQuery(today) {
  return { start_date: `${today.slice(0, 7)}-01`, end_date: today, comparison_mode: 'previous', scope: 'mine', customer_ids: [], owner_ids: [], filters: {}, dimensions: ['craft', 'length'], metric: 'amount', finance_related_customers: false }
}
export function cleanQuery(query, options) {
  const allowed = Object.keys(options.dimensions || {})
  const result = { ...query, customer_ids: [...(query.customer_ids || [])], owner_ids: [...(query.owner_ids || [])], dimensions: [...(query.dimensions || [])].filter(field => allowed.includes(field)).slice(0, 2), filters: Object.fromEntries(Object.entries(query.filters || {}).filter(([key, values]) => allowed.includes(key) && values.length).map(([key, values]) => [key, [...values]])) }
  if (!options.permissions?.all) { result.scope = 'mine'; result.owner_ids = [] }
  if (!options.permissions?.finance) result.finance_related_customers = false
  return result
}
export function applySavedView(view, today, options) {
  const query = JSON.parse(JSON.stringify(view.query))
  if (view.time_mode === 'rolling') {
    const start = Date.parse(`${query.start_date}T00:00:00+08:00`)
    const end = Date.parse(`${query.end_date}T00:00:00+08:00`)
    const length = Math.round((end - start) / 86400000)
    const date = new Date(Date.parse(`${today}T00:00:00+08:00`) - length * 86400000)
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date)
    const map = Object.fromEntries(parts.map(part => [part.type, part.value]))
    query.start_date = `${map.year}-${map.month}-${map.day}`; query.end_date = today
  }
  return cleanQuery(query, options)
}
export function validateQuery(query) {
  const start = Date.parse(`${query.start_date}T00:00:00+08:00`), end = Date.parse(`${query.end_date}T00:00:00+08:00`)
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start || (end - start) / 86400000 > 1095) return '请选择 1 至 1096 天的有效时间范围'
  if (new Set(query.dimensions).size !== query.dimensions.length || query.dimensions.length > 2) return '分析维度最多两个，且不可重复'
  return ''
}
export function latestRequestGate() {
  let generation = 0
  return { next: () => ++generation, isCurrent: token => token === generation, invalidate: () => ++generation }
}
export function groupedInsights(insights = []) {
  const groups = new Map()
  for (const item of insights) {
    const key = item.customer_id ? `customer:${item.customer_id}` : `rule:${item.rule_key}`
    if (!groups.has(key)) groups.set(key, { key, customer_id: item.customer_id, reasons: [] })
    const group = groups.get(key)
    if (group.reasons.length < 3) group.reasons.push(item)
  }
  return [...groups.values()]
}
export function actionCompletionError(action) {
  return action.status === 'done' && (!action.result?.trim() || !action.result_type) ? '完成行动须填写实际结果和结果类型' : ''
}
export function comparisonText(change) {
  if (!change) return '未设置对照'
  if (change.rate == null) return change.previous === 0 ? '对照为零，仅展示绝对变化' : '历史不足，变化率未知'
  return `${change.rate >= 0 ? '+' : ''}${percent(change.rate)} 对照变化`
}

Object.assign(STATUS_LABELS, { sustained_repeat: '持续复购', losing_rhythm: '周期延后，核查流失', dormant: '长期未购，核查流失', repeat_observed: '已观察复购', inactive_store: '停止经营 / 联系', recharged: '充值客户', non_recharged: '非充值客户', recharge_and_discount: '曾充值并享折让', recharged_without_discount: '曾充值，本期未见折让', full_price_without_recharge: '未见充值，按原价下单', discount_without_recharge: '未见充值，存在折让', no_behavior_sample: '行为样本不足', unconfirmed: '待跟进确认', pending_recharge: '有待审充值申请', noncommercial_shipping: '仅售后 / 零价出货', steady_seller: '持续畅销观察', occasional_shipping: '偶发出货 / 样本待积累', ordered_not_shipped: '本期下单尚未出货', missing_cost: '缺成本，待核算', specification_unverified: '规格映射待核验', aged_production: '长期在制，核查积压', supply_build_up: '入库多于毛坯出库，核查积压', demand_supported: '有毛坯出库需求', faster_replenishment: '周期不高于同范围中位数', slower_replenishment: '周期高于同范围中位数' })
