import { isAmount } from '@/utils/validators'

// Native ledger arithmetic and display remain decimal strings/BigInt throughout.
// The shared Number formatter cannot retain every cent for wide decimal values.
export function toUnits(value, precision = 2) {
  const text = String(value ?? '').trim()
  if (!isAmount(text, { precision, allowNegative: true, allowZero: true })) throw new Error('金额格式不正确')
  const negative = text.startsWith('-')
  const [integer, fraction = ''] = (negative ? text.slice(1) : text).split('.')
  const units = BigInt(integer) * 10n ** BigInt(precision) + BigInt(fraction.padEnd(precision, '0') || '0')
  return negative ? -units : units
}
export function fromUnits(value, precision = 2) {
  const negative = value < 0n
  const digits = (negative ? -value : value).toString().padStart(precision + 1, '0')
  return `${negative ? '-' : ''}${precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits}`
}
export function formatNativeMoney(value, precision = 2) {
  try {
    const normalized = fromUnits(toUnits(value, precision), precision)
    const [integer, fraction] = normalized.split('.')
    return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction === undefined ? '' : `.${fraction}`)
  } catch { return '—' }
}
export function requireAmount(value, label, options = {}) {
  const settings = { precision: 2, maxIntegerDigits: 12, allowZero: true, ...options }
  if (!isAmount(value, settings)) throw new Error(`${label}格式不正确，请使用最多 ${settings.precision} 位小数的十进制金额`)
  return String(value).trim()
}
export function positive(value) {
  try { return toUnits(value) > 0n } catch { return false }
}
export function lineAmount(line) {
  const price = toUnits(line.price_per_piece, 4)
  if (!Number.isInteger(line.quantity) || line.quantity < 1) throw new Error('数量必须为正整数')
  return (price * BigInt(line.quantity) + 50n) / 100n + toUnits(line.discount_amount)
}
export function orderPreview(form) {
  try {
    const goods = form.items.reduce((sum, line) => sum + lineAmount(line), 0n)
    const total = goods + toUnits(form.shipping_fee) + toUnits(form.surcharge_amount) + toUnits(form.internal_accessory)
    return { goods: fromUnits(goods), total: fromUnits(total) }
  } catch { return null }
}
