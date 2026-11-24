// 付款方式（2026-07-24）：3 个店铺信保各拆「便捷发货」「报关」两档，共 8 项。
// 2026-09-23 增补：现金/支付宝/微信/对公转账（莱莎/旭和），均无自动费率、手续费手填。
// 便捷发货按比例自动算手续费、报关及新增项手填。选项文本即 internal_payment_method 存值。
export const PAYMENT_METHOD_OPTIONS = [
  'PayPal',
  '大莱莎信保（便捷发货）', '大莱莎信保（报关）',
  '小莱莎信保（便捷发货）', '小莱莎信保（报关）',
  '新莱莎信保（便捷发货）', '新莱莎信保（报关）',
  'TT',
  '现金', '支付宝', '微信', '对公转账（莱莎）', '对公转账（旭和）',
]
// 付款方式 → 手续费费率。命中即按 费率×订单总金额 自动填手续费（仍可手改）。
// 未登记的方式（报关各项、未选）返回 null = 不自动计算、由用户手填。
export const PAYMENT_METHOD_RATES = {
  PayPal: 0.05,
  '大莱莎信保（便捷发货）': 0.03,
  '小莱莎信保（便捷发货）': 0.03,
  '新莱莎信保（便捷发货）': 0.03,
  TT: 0,
}
// 快递渠道（2026-09-23 必填单选；2026-11-24 按付款方式分组）。
// 付款方式 → 可选渠道。后端 app/invoice/shipping_policy.py 有同一张表，测试锁定两边一致。
export const ANY_EXPRESS_CHANNEL = '其他快递'
export const PAYMENT_CHANNEL_GROUPS = [
  { key: 'normal', label: '普通付款', short: '普货',
    methods: ['PayPal', 'TT', '现金', '支付宝', '微信'],
    channels: ['DHL普货', 'FEDEX普货', '顺丰', '自提', '货代/海运'] },
  { key: 'convenient', label: '信保便捷发货', short: '9610',
    methods: ['大莱莎信保（便捷发货）', '小莱莎信保（便捷发货）', '新莱莎信保（便捷发货）'],
    channels: ['DHL9610', 'FEDEX9610'] },
  { key: 'customs', label: '信保报关 / 对公转账', short: '报关',
    methods: ['大莱莎信保（报关）', '小莱莎信保（报关）', '新莱莎信保（报关）', '对公转账（莱莎）', '对公转账（旭和）'],
    channels: ['DHL报关', 'FEDEX报关'] },
]
export const EXPRESS_CHANNEL_OPTIONS = [...PAYMENT_CHANNEL_GROUPS.flatMap(group => group.channels), ANY_EXPRESS_CHANNEL]

// 存量订单使用旧文本存值，打开编辑时回显到新的普货选项。
export function normalizeStoredExpressChannel(channel) {
  if (channel === 'DHL') return 'DHL普货'
  if (channel === 'FEDEX') return 'FEDEX普货'
  return channel || ''
}

const CONVENIENT = PAYMENT_CHANNEL_GROUPS[1]
const CUSTOMS = PAYMENT_CHANNEL_GROUPS[2]

// 未登记的付款方式沿用「含便捷发货」关键字口径，其余返回 null（不限制渠道）
export function paymentGroupOf(method) {
  const value = String(method || '').trim()
  return PAYMENT_CHANNEL_GROUPS.find(group => group.methods.includes(value))
    || (value.includes('便捷发货') ? CONVENIENT : null)
}

// keywords=false：未选付款方式时「报关」自由文本不算报关渠道（门户/集成原样保存）
export function channelGroupOf(channel, { keywords = true } = {}) {
  const value = normalizeStoredExpressChannel(String(channel || '').trim())
  return PAYMENT_CHANNEL_GROUPS.find(group => group.channels.includes(value))
    || (value.includes('9610') ? CONVENIENT : keywords && value.includes('报关') ? CUSTOMS : null)
}

// 当前付款方式可选的渠道；未选付款方式返回 null（显示全部）
export function channelsForPayment(method) {
  const group = paymentGroupOf(method)
  return group ? [...group.channels, ANY_EXPRESS_CHANNEL] : null
}

export function paymentChannelError(method, channel) {
  const value = String(channel || '').trim()
  const methodGroup = paymentGroupOf(method)
  const allowed = group => [...group.channels, ANY_EXPRESS_CHANNEL].join('、')
  if (!value) return methodGroup === CONVENIENT ? `付款方式「${method}」须选择快递渠道：${allowed(methodGroup)}` : ''
  if (value === ANY_EXPRESS_CHANNEL) return ''
  const channelGroup = channelGroupOf(value, { keywords: Boolean(methodGroup) })
  if (methodGroup) {
    return channelGroup === methodGroup ? '' : `付款方式「${method}」只能选择快递渠道：${allowed(methodGroup)}，请修改快递渠道`
  }
  if (channelGroup && channelGroup.key !== 'normal') {
    return `快递渠道「${value}」须配合付款方式「${channelGroup.label}」，请选择对应付款方式`
  }
  return ''
}

// 用户改付款方式后修正已选渠道：同承运商自动切换，对不上则清空。返回 { channel, notice }
export function reconcileChannelForPayment(method, channel) {
  const allowed = channelsForPayment(method)
  if (!channel || !allowed || !paymentChannelError(method, channel)) return { channel, notice: '' }
  const carrier = (normalizeStoredExpressChannel(channel).match(/^(DHL|FEDEX)/) || [])[1]
  const match = carrier && allowed.find(option => option.startsWith(carrier))
  if (match) return { channel: match, notice: `快递渠道已从「${channel}」自动改为「${match}」` }
  return { channel: '', notice: `「${channel}」不适用于付款方式「${method}」，已清空，请重新选择快递渠道` }
}

// 付款方式下拉分组：已选渠道时把适用的组排前面
export function paymentMethodGroupsFor(channel) {
  const value = String(channel || '').trim()
  const fit = value && value !== ANY_EXPRESS_CHANNEL ? channelGroupOf(value) : null
  const ordered = fit ? [fit, ...PAYMENT_CHANNEL_GROUPS.filter(group => group !== fit)] : PAYMENT_CHANNEL_GROUPS
  return ordered.map(group => ({
    label: fit ? `${group.label}${group === fit ? `（适用「${value}」）` : '（选了会改渠道）'}` : group.label,
    methods: group.methods,
  }))
}

// 命中返回费率（含 0），未登记返回 null（手填，不自动算）。
export function handlingFeeRate(method) {
  return Object.prototype.hasOwnProperty.call(PAYMENT_METHOD_RATES, method)
    ? PAYMENT_METHOD_RATES[method]
    : null
}

export function computeHandlingFee(rate, base) {
  return toMoneyCents(Number(rate || 0) * Number(base || 0)) / 100
}

export function toMoneyCents(value) {
  const number = Number(value || 0)
  const sign = number < 0 ? -1 : 1
  return sign * Math.floor(Math.abs(number) * 100 + 0.5 + 1e-8)
}

export function normalizeDiscount(value) {
  const cents = Math.abs(toMoneyCents(value))
  return cents === 0 ? 0 : -cents / 100
}

// 价格框只显示两位，成交价仍按四位存（规则价如 21.1919、导入价如 30.048）。
// 用户重输的两位值与规则价四舍五入后一致时，视为「没改」，还原成四位规则价：
// 否则一敲键盘就把 21.1919 截成 21.19，行被误标手改且再也回不到规则价。
export function snapPriceToRule(price, rulePrice) {
  if (price == null || rulePrice == null) return price
  return toMoneyCents(price) === toMoneyCents(rulePrice) && isWholeCents(price)
    ? Number(rulePrice)
    : price
}

// 两位显示藏住的小数位：单价×数量与行合计对不上时，悬停能看到实际计价口径
export function hiddenPricePrecision(price) {
  if (price == null || price === '') return ''
  const number = Number(price)
  if (!Number.isFinite(number) || isWholeCents(number)) return ''
  return String(Number(number.toFixed(4)))
}

function isWholeCents(value) {
  const number = Number(value)
  return Math.abs(number - toMoneyCents(number) / 100) < 1e-9
}

export function calculateLineGross(quantity, pricePerPiece) {
  return toMoneyCents(Number(quantity || 0) * Number(pricePerPiece || 0)) / 100
}

export function calculateLineTotal(quantity, pricePerPiece, discount = 0) {
  return (
    toMoneyCents(calculateLineGross(quantity, pricePerPiece))
    + toMoneyCents(normalizeDiscount(discount))
  ) / 100
}

export function sumLineGross(rows) {
  return rows.reduce(
    (sum, row) => sum + toMoneyCents(calculateLineGross(row.quantity, row.price_per_piece)),
    0,
  ) / 100
}

export function sumLineDiscount(rows) {
  return rows.reduce(
    (sum, row) => sum + toMoneyCents(normalizeDiscount(row.discount_amount)),
    0,
  ) / 100
}

export function sumLineNet(rows) {
  return rows.reduce(
    (sum, row) => sum + toMoneyCents(calculateLineTotal(
      row.quantity,
      row.price_per_piece,
      row.discount_amount,
    )),
    0,
  ) / 100
}

export function calculateInvoiceTotal(productTotal, packaging, shippingFee, handlingFee) {
  return (
    toMoneyCents(productTotal)
    + toMoneyCents(packaging)
    + toMoneyCents(shippingFee)
    + toMoneyCents(handlingFee)
  ) / 100
}

export function calculateBalance(total, prepayment) {
  if (prepayment == null || prepayment === '') return null
  return (toMoneyCents(total) - toMoneyCents(prepayment)) / 100
}

// 总折扣均分（2026-09-23）：费用与结算的「折扣」录入框把总额按行数均分到产品行，
// 不能整除的余数计入最后一行。输入输出均为「分」（非负整数），调用方自行加负号。
export function splitDiscountCents(totalCents, count) {
  const total = Math.abs(Math.round(Number(totalCents) || 0))
  const n = Math.max(0, Math.floor(Number(count) || 0))
  if (!n) return []
  const per = Math.floor(total / n)
  const remainder = total - per * n
  return Array.from({ length: n }, (_, index) => (index === n - 1 ? per + remainder : per))
}

export function applyTotalDiscountToRows(hairItems, value) {
  const rows = hairItems.filter(line => Number(line.quantity) > 0 && Number(line.price_per_piece) > 0)
  const shares = splitDiscountCents(toMoneyCents(value), rows.length)
  rows.forEach((row, index) => {
    row.discount_amount = shares[index] ? -(shares[index] / 100) : 0
    row.total_price = calculateLineTotal(row.quantity, row.price_per_piece, row.discount_amount)
  })
  return rows.length
}

export function settlementMatchesTotal(total, prepayment, balance) {
  if (prepayment == null && balance == null) return true
  if (prepayment == null || balance == null) return false
  if (toMoneyCents(prepayment) < 0 || toMoneyCents(balance) < 0) return false
  return toMoneyCents(prepayment) + toMoneyCents(balance) === toMoneyCents(total)
}


export function alibabaOrderRequired(form) {
  return String(form.internal_payment_method || '').includes('便捷发货')
}

export function alibabaOrderError(form) {
  const value = String(form.alibaba_order_no || '').replace(/\s+/g, '')
  if (value && !/^[0-9]{15,20}$/.test(value)) return '阿里信保订单号须为15~20位数字'
  if (!value && alibabaOrderRequired(form)) return '便捷发货必须填写阿里信保订单号'
  return ''
}
