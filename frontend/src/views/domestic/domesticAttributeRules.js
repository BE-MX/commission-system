const CAP_FIELDS = ['craft', 'length', 'net_color', 'size', 'hair_style_series']
const PIECE_FIELDS = ['craft', 'length']

export function visibleAttributeFields(attrs) {
  if (attrs.product_type === 'piece') return PIECE_FIELDS
  return attrs.length === '15厘米' ? [...CAP_FIELDS, 'density'] : CAP_FIELDS
}

export function requiredAttributeFields(attrs) {
  if (attrs.product_type === 'piece') return PIECE_FIELDS
  const fields = ['craft', 'length', 'size', 'hair_style_series']
  return attrs.length === '15厘米' ? [...fields, 'density'] : fields
}

export function attributeOptions(options, orderCategory, productType, field) {
  const standardType = options.attr_dicts?.[productType]?.[field]
  if (!standardType) return []
  const standard = options.standard_values?.[standardType] || []
  if (orderCategory !== 'special') return standard
  const specialType = options.special_attr_dicts?.[productType]?.[field]
  const special = specialType ? (options.special_values?.[specialType] || []) : []
  return [...new Set([...standard, ...special])]
}

export function clearNonstandardAttributes(attrs, options) {
  for (const field of visibleAttributeFields(attrs)) {
    const value = attrs[field]
    if (!value) continue
    const standardType = options.attr_dicts?.[attrs.product_type]?.[field]
    const standardValues = options.standard_values?.[standardType] || []
    if (!standardValues.includes(value)) attrs[field] = ''
  }
  if (attrs.product_type === 'cap' && attrs.length !== '15厘米') attrs.density = ''
  return attrs
}

export function normalizeItemAttrs(attrs) {
  return Object.fromEntries([
    ['product_type', attrs.product_type],
    ...visibleAttributeFields(attrs).map(field => [field, attrs[field]]),
  ].filter(([, value]) => value !== '' && value !== null && value !== undefined))
}

export function clearInapplicableAttributes(attrs) {
  const applicable = new Set(visibleAttributeFields(attrs))
  for (const field of ['craft', 'length', 'net_color', 'size', 'density', 'hair_style_series']) {
    if (!applicable.has(field)) attrs[field] = ''
  }
  return attrs
}

export function routeForItem(item, orderCategory, craftRoutes, defaultRoutes, standardCrafts = []) {
  const { product_type: productType, craft } = item.attrs
  if (!craft) return null
  const exact = craftRoutes.find(route => (
    route.product_type === productType && route.craft === craft
  ))
  if (exact) return exact
  const isCustomCraft = !standardCrafts.includes(craft)
  const fallback = orderCategory === 'special' && isCustomCraft
    ? defaultRoutes?.[productType]
    : null
  return fallback ? {
    route_id: fallback.id,
    route_name: fallback.name,
    step_count: fallback.step_count,
    is_default: true,
  } : null
}
