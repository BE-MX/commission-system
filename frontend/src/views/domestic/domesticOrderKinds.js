import { normalizeItemAttrs } from './domesticAttributeRules.js'

export function detailSectionsForKind(orderKind, sections) {
  return orderKind === 'production'
    ? sections.filter(section => !['hairstyle', 'style_requirement'].includes(section.key))
      .map(section => section.key === 'remark' ? { ...section, placeholder: '填写本批次备货或工艺要求' } : section)
    : sections
}

export function routeForOrder(item, orderKind, orderCategory, orderRoutes) {
  if (!item.attrs.craft) return null
  const group = orderKind === 'production' ? 'production' : orderCategory
  return orderRoutes?.[group]?.[item.attrs.product_type] || null
}

export function buildProductionPayload(form) {
  const paths = images => (images || []).map(image => typeof image === 'string' ? image : image.path)
  return {
    order_kind: 'production',
    customer_id: form.customer_id || null,
    order_date: form.order_date,
    remark: form.remark || null,
    items: form.items.map(item => ({
      client_key: item.key,
      attrs: normalizeItemAttrs(item.attrs, 'production'),
      order_qty: item.order_qty,
      color: item.color || null,
      color_images: paths(item.color_images),
      remark: item.remark || null,
      remark_images: paths(item.remark_images),
    })),
  }
}
