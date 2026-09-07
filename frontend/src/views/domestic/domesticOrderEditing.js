const HEADER_FIELDS = ['order_no', 'order_date', 'required_ship_date', 'order_type', 'order_channel', 'remark']
const ITEM_FIELDS = ['order_qty', 'unit_price', 'hairstyle', 'hairstyle_images', 'color', 'color_images',
  'style_requirement', 'style_images', 'remark', 'remark_images']
const PRODUCTION_EXCLUDED = new Set(['unit_price', 'hairstyle', 'hairstyle_images', 'style_requirement', 'style_images'])

export function orderHeaderForm(detail) {
  return Object.fromEntries(HEADER_FIELDS.map(key => [key, detail?.[key] || '']))
}

export function buildHeaderPatch(detail, form) {
  const fields = detail.order_kind === 'production' ? ['order_date', 'remark'] : HEADER_FIELDS
  return Object.fromEntries(fields.filter(key => (detail[key] || '') !== form[key])
    .map(key => [key, key === 'remark' ? (form[key] || null) : form[key]]))
}

export function orderItemForm(item) {
  return Object.fromEntries(ITEM_FIELDS.map(key => [key,
    key.endsWith('_images') ? [...(item[key] || [])]
      : ['order_qty', 'unit_price'].includes(key) ? Number(item[key] || 0) : (item[key] || ''),
  ]))
}

export function buildItemPatch(detail, item, form) {
  const previous = orderItemForm(item)
  return Object.fromEntries(ITEM_FIELDS.filter(key => detail.order_kind !== 'production' || !PRODUCTION_EXCLUDED.has(key))
    .filter(key => JSON.stringify(previous[key]) !== JSON.stringify(form[key]))
    .map(key => [key, typeof form[key] === 'string' ? (form[key] || null) : form[key]]))
}

export function itemEditDelta(item, form) {
  return (Math.round(Number(form.unit_price) * 100) * Number(form.order_qty)
    - Math.round(Number(item.unit_price) * 100) * Number(item.order_qty)) / 100
}

export function itemPriceError(item, patch) {
  if (!Object.hasOwn(patch, 'unit_price')) return ''
  const goodsPrice = Math.round(Number(patch.unit_price) * 100) - Math.round(Number(item.labor_fee || 0) * 100)
  if (!Number.isFinite(goodsPrice) || goodsPrice <= 0) return '成交单价必须高于手工费'
  if (goodsPrice > Math.round(Number(item.original_price || 0) * 100)) return '优惠后商品单价不能高于原价'
  return ''
}
