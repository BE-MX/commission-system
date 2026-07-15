import { normalizeDiscount } from './invoiceSettlement.js'

const cents = value => Math.round((Number(value) || 0) * 100)
const money = value => cents(value) / 100

export function createLatestRequestGate() {
  let sequence = 0
  return {
    issue(context = '') { return { sequence: ++sequence, context: String(context) } },
    isCurrent(token, context = token.context) {
      return token.sequence === sequence && token.context === String(context)
    },
    invalidate() { sequence++ },
  }
}

export function calculateAccessoryTotal(quantity, pricePerPiece, discountAmount = 0) {
  const grossCents = Math.round((Number(quantity) || 0) * cents(pricePerPiece))
  return (grossCents + cents(normalizeDiscount(discountAmount))) / 100
}

export function normalizeAccessoryRow(row = {}) {
  const standardPrice = row.standard_price == null ? null : Number(row.standard_price)
  const customerPrice = row.customer_price == null ? null : Number(row.customer_price)
  const pricePerPiece = row.price_per_piece == null
    ? (customerPrice ?? standardPrice)
    : Number(row.price_per_piece)
  const normalized = {
    id: row.id || null,
    product_kind: 'accessory',
    item_type: 'stock',
    product_id: row.product_id || null,
    sku_id: row.sku_id || null,
    product_name: row.product_name || row.accessory_name || '',
    product_display: row.product_display || row.accessory_name || '',
    model: row.model || row.accessory_model || '',
    color: row.color || row.accessory_color || '',
    length: null,
    net_weight_grams: null,
    curl: null,
    quantity: Number(row.quantity || 1),
    standard_price: standardPrice,
    customer_price: customerPrice,
    price_per_piece: pricePerPiece,
    discount_amount: normalizeDiscount(row.discount_amount),
    price_source: row.price_source || (customerPrice == null ? 'standard' : 'customer_rule'),
  }
  normalized.total_price = calculateAccessoryTotal(
    normalized.quantity,
    normalized.price_per_piece,
    normalized.discount_amount,
  )
  return normalized
}

export function accessoryGross(rows) {
  return money(rows.reduce((sum, row) => sum + Math.round((Number(row.quantity) || 0) * cents(row.price_per_piece)), 0) / 100)
}

export function accessoryDiscount(rows) {
  return money(rows.reduce((sum, row) => sum + cents(normalizeDiscount(row.discount_amount)), 0) / 100)
}

export function accessoryNet(rows) {
  return money(accessoryGross(rows) + accessoryDiscount(rows))
}
