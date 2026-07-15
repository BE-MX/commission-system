export const PAYMENT_METHOD_OPTIONS = ['PayPal', '大莱莎信保', '小莱莎信保', '新莱莎信保', 'TT']
export const EXPRESS_CHANNEL_OPTIONS = ['DHL', 'FEDEX', '其他']

function toCents(value) {
  return Math.round(Number(value || 0) * 100)
}

export function normalizeDiscount(value) {
  const cents = Math.abs(toCents(value))
  return cents === 0 ? 0 : -cents / 100
}

export function calculateLineTotal(quantity, pricePerPiece, discount = 0) {
  const gross = Math.round(Number(quantity || 0) * Number(pricePerPiece || 0) * 100)
  return (gross + toCents(normalizeDiscount(discount))) / 100
}

export function calculateInvoiceTotal(productTotal, packaging, shippingFee, handlingFee) {
  return (
    toCents(productTotal)
    + toCents(packaging)
    + toCents(shippingFee)
    + toCents(handlingFee)
  ) / 100
}

export function calculateBalance(total, prepayment) {
  if (prepayment == null || prepayment === '') return null
  return (toCents(total) - toCents(prepayment)) / 100
}

export function settlementMatchesTotal(total, prepayment, balance) {
  if (prepayment == null && balance == null) return true
  if (prepayment == null || balance == null) return false
  if (toCents(prepayment) < 0 || toCents(balance) < 0) return false
  return toCents(prepayment) + toCents(balance) === toCents(total)
}
