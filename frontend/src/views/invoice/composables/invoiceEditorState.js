import { normalizeDiscount } from './invoiceSettlement.js'

export function emptyInvoiceForm() {
  return {
    id: null, invoice_no: '', order_type: 'stock', customer_id: '', customer_name: '',
    contact_name: '', contact_phone: '', contact_email: '', delivery_address: '',
    sales_user_name: '', sales_phone: '', sales_email: '',
    invoice_date: new Date().toISOString().slice(0, 10), currency: 'USD', express_channel: '',
    shipping_fee: 0, surcharge_name: '', surcharge_amount: 0, payment_term: '',
    internal_payment_method: '', internal_discount: 0, packaging_quantity: 0,
    internal_accessory: 0, internal_received: null, internal_balance: null,
    internal_shipping_type: '', okki_new_deal: 1, okki_free_shipping: 1,
    okki_first_return: 0, remark: '', items: [],
  }
}

export function normalizeHairRow(line = {}) {
  return {
    id: line.id || null,
    product_kind: 'hair',
    item_type: line.item_type || 'stock',
    product_id: line.product_id || null,
    sku_id: line.sku_id || null,
    custom_product_id: line.custom_product_id || null,
    product_name: line.product_name || '',
    product_display: line.product_display || '',
    net_weight_grams: line.net_weight_grams || '',
    curl: line.curl || '',
    model: line.model || '',
    color: line.color || '',
    length: line.length || '',
    quantity: Number(line.quantity || 1),
    standard_price: line.standard_price == null ? null : Number(line.standard_price),
    customer_price: line.customer_price == null ? null : Number(line.customer_price),
    color_type_source: line.color_type_source || '',
    price_per_piece: line.price_per_piece == null ? null : Number(line.price_per_piece),
    discount_amount: normalizeDiscount(line.discount_amount),
    total_price: Number(line.total_price || 0),
    price_source: line.price_source || 'manual',
    _importBatchFingerprint: line._importBatchFingerprint || '',
    options: { models: [], colors: [], sizes: [], units: [] },
    matching: false,
  }
}

export function buildInvoicePayload(form, hairDiscount) {
  return {
    invoice_no: (form.invoice_no || '').trim() || null,
    order_type: form.order_type, customer_id: form.customer_id, customer_name: form.customer_name,
    contact_name: form.contact_name || null, contact_phone: form.contact_phone || null,
    contact_email: form.contact_email || null, delivery_address: form.delivery_address || null,
    sales_user_name: form.sales_user_name || null, sales_phone: form.sales_phone || null,
    sales_email: form.sales_email || null, invoice_date: form.invoice_date,
    currency: form.currency || 'USD', express_channel: form.express_channel || null,
    shipping_fee: Number(form.shipping_fee || 0),
    surcharge_name: Number(form.surcharge_amount || 0) ? 'Handling Fee' : null,
    surcharge_amount: Number(form.surcharge_amount || 0), payment_term: form.payment_term || null,
    internal_payment_method: form.internal_payment_method || null, internal_discount: hairDiscount,
    packaging_quantity: Number(form.packaging_quantity || 0),
    internal_accessory: Number(form.internal_accessory || 0), internal_received: form.internal_received,
    internal_balance: form.internal_balance, internal_shipping_type: form.internal_shipping_type || null,
    okki_new_deal: form.okki_new_deal ?? null, okki_free_shipping: form.okki_free_shipping ?? null,
    okki_first_return: form.okki_first_return ?? null, remark: form.remark,
    items: form.items.map(line => ({
      id: line.id || null, product_kind: line.product_kind || 'hair', item_type: line.item_type,
      product_id: line.product_id, sku_id: line.sku_id, product_name: line.product_name,
      product_display: line.product_display, net_weight_grams: line.net_weight_grams,
      curl: line.curl || null, model: line.model || null, color: line.color,
      length: line.length, quantity: line.quantity, price_per_piece: line.price_per_piece,
      discount_amount: normalizeDiscount(line.discount_amount), price_source: line.price_source || 'manual',
    })),
  }
}
