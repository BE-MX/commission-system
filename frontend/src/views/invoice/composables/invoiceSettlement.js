export const PAYMENT_METHOD_OPTIONS = ['PayPal', '大莱莎信保', '小莱莎信保', '新莱莎信保', 'TT']
export const EXPRESS_CHANNEL_OPTIONS = ['DHL', 'FEDEX', '其他']

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
