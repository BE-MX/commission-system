// 付款方式（2026-07-24）：3 个店铺信保各拆「便捷发货」「报关」两档，共 8 项。
// 便捷发货按比例自动算手续费、报关手填。选项文本即 internal_payment_method 存值。
export const PAYMENT_METHOD_OPTIONS = [
  'PayPal',
  '大莱莎信保（便捷发货）', '大莱莎信保（报关）',
  '小莱莎信保（便捷发货）', '小莱莎信保（报关）',
  '新莱莎信保（便捷发货）', '新莱莎信保（报关）',
  'TT',
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
export const EXPRESS_CHANNEL_OPTIONS = ['DHL', 'FEDEX', '其他']

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

export function settlementMatchesTotal(total, prepayment, balance) {
  if (prepayment == null && balance == null) return true
  if (prepayment == null || balance == null) return false
  if (toMoneyCents(prepayment) < 0 || toMoneyCents(balance) < 0) return false
  return toMoneyCents(prepayment) + toMoneyCents(balance) === toMoneyCents(total)
}
