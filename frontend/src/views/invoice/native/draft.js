import { currentBeijingDate } from '@/utils/datetime'
import { requireAmount, toUnits, lineAmount, orderPreview } from '@/views/finance/native/decimal'

let lineIdentity = 0
export function newOrderLine(item = {}) {
  return {
    key: ++lineIdentity, id: item.id || null, local_sku_id: item.local_sku_id || null,
    label: [item.product_display || item.product_name, item.model, item.color, item.length, item.curl].filter(Boolean).join(' / '),
    quantity: item.quantity ?? 1, price_per_piece: String(item.price_per_piece ?? '0'),
    discount_amount: String(item.discount_amount ?? '0'), commercial_kind: item.commercial_kind || 'bulk',
    stock_reserved_quantity: item.stock_reserved_quantity || 0,
    stock_shipped_quantity: item.stock_shipped_quantity || 0,
    production_pending_quantity: item.production_pending_quantity || 0,
  }
}
export function makeOrderDraft(invoice) {
  const source = invoice || {}, commercial = source.local_commercial || {}
  return {
    expected_version: source.commerce_version || 0,
    invoice_no: source.invoice_no || '', local_customer_id: source.local_customer_id || null,
    customer_name: source.customer_name || '', sales_user_id: source.sales_user_id || null,
    merchandiser_id: source.merchandiser_id || null, order_type: source.order_type || 'stock',
    invoice_date: source.invoice_date || currentBeijingDate(), currency: source.currency || '',
    contact_name: source.contact_name || '', contact_phone: source.contact_phone || '',
    contact_email: source.contact_email || '', delivery_address: source.delivery_address || '',
    express_channel: source.express_channel || '', shipping_fee: String(source.shipping_fee ?? '0'),
    surcharge_name: source.surcharge_name || '', surcharge_amount: String(source.surcharge_amount ?? '0'),
    packaging_quantity: source.packaging_quantity ?? 0, internal_accessory: String(source.internal_accessory ?? '0'),
    local_deposit_amount: String(source.local_deposit_amount ?? '0'), local_deposit_charge: String(source.local_deposit_charge ?? '0'),
    payment_term: source.payment_term || '', remark: source.remark || '',
    commercial_source: commercial.commercial_source || 'unknown',
    is_new_deal: commercial.is_new_deal ?? '', is_first_return: commercial.is_first_return ?? '',
    is_private_order: commercial.is_private_order || false,
    department_allocations: (commercial.department_allocations || []).map(d => ({ department_id: d.department_id, rate: String(d.rate) })),
    items: source.items?.length ? source.items.map(newOrderLine) : [newOrderLine()],
    business_date: currentBeijingDate(), warehouse_id: null, reason: '',
  }
}
export function draftPayload(form, amend = false) {
  if (!form.local_customer_id || !form.sales_user_id || !form.currency || !form.invoice_date) throw new Error('请选择客户、业务员、币种和订单日期')
  if (!form.items.length || form.items.length > 200) throw new Error('订单必须有 1 至 200 行商品')
  const body = {}
  for (const key of ['expected_version', 'local_customer_id', 'sales_user_id', 'order_type', 'invoice_date', 'currency', 'packaging_quantity', 'is_private_order', 'commercial_source']) body[key] = form[key]
  body.invoice_no = form.invoice_no.trim() || null
  body.merchandiser_id = form.merchandiser_id || null
  for (const key of ['contact_name', 'contact_phone', 'contact_email', 'delivery_address', 'express_channel', 'surcharge_name', 'payment_term', 'remark']) body[key] = form[key] || null
  for (const key of ['shipping_fee', 'surcharge_amount', 'internal_accessory', 'local_deposit_amount', 'local_deposit_charge']) body[key] = requireAmount(form[key], '费用')
  if (!Number.isInteger(body.packaging_quantity) || body.packaging_quantity < 0) throw new Error('包装数量必须为非负整数')
  for (const key of ['is_new_deal', 'is_first_return']) body[key] = typeof form[key] === 'boolean' ? form[key] : null
  body.department_allocations = form.department_allocations.map(d => ({ department_id: d.department_id, rate: requireAmount(d.rate, '部门比例', { precision: 4, maxIntegerDigits: 3, allowZero: false }) }))
  if (body.department_allocations.length) {
    if (body.department_allocations.some(d => !d.department_id) || new Set(body.department_allocations.map(d => d.department_id)).size !== body.department_allocations.length) throw new Error('部门必须已选择且不能重复')
    if (body.department_allocations.reduce((sum, d) => sum + toUnits(d.rate, 4), 0n) !== 1000000n) throw new Error('部门分摊合计必须为 100%')
  }
  body.items = form.items.map((line, index) => {
    if (!line.local_sku_id) throw new Error(`第 ${index + 1} 行请选择商品 SKU`)
    if (!Number.isInteger(line.quantity) || line.quantity < 1 || line.quantity > 2147483647) throw new Error(`第 ${index + 1} 行数量必须为有效正整数`)
    const price = requireAmount(line.price_per_piece, `第 ${index + 1} 行单价`, { precision: 4, maxIntegerDigits: 8 })
    const discount = requireAmount(line.discount_amount, `第 ${index + 1} 行折扣`, { allowNegative: true })
    if (toUnits(discount) > 0n) throw new Error('折扣金额须为零或负数')
    const total = lineAmount(line)
    if (total < 0n || total > 99999999999999n) throw new Error(`第 ${index + 1} 行金额超出允许范围`)
    return { id: line.id || null, local_sku_id: line.local_sku_id, quantity: line.quantity, price_per_piece: price, discount_amount: discount, commercial_kind: line.commercial_kind }
  })
  const preview = orderPreview(form)
  if (!preview || toUnits(preview.total) > 99999999999999n) throw new Error('订单总额超出允许范围')
  if (form.order_type === 'presale' && toUnits(body.shipping_fee) !== 0n) throw new Error('预售主单不登记运费，请在分批结算时登记')
  if (form.order_type !== 'presale' && (toUnits(body.local_deposit_amount) !== 0n || toUnits(body.local_deposit_charge) !== 0n)) throw new Error('仅预售订单可以约定首款')
  if (toUnits(body.local_deposit_charge) > toUnits(body.local_deposit_amount) || toUnits(body.local_deposit_charge) > toUnits(body.surcharge_amount)) throw new Error('首款费用不能超过首款总额或合同附加费')
  if (amend) {
    if (!form.reason.trim() || !form.business_date) throw new Error('请填写变更日期及原因')
    Object.assign(body, { business_date: form.business_date, reason: form.reason.trim(), warehouse_id: form.warehouse_id || null })
  }
  return body
}
