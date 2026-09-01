const CAP_FIELDS = ['craft', 'length', 'net_color', 'size', 'hair_style_series']
const PIECE_FIELDS = ['craft', 'length']
const ATTRIBUTE_FIELDS = ['craft', 'length', 'net_color', 'size', 'density', 'hair_style_series']
const ATTRIBUTE_MAX_LENGTHS = {
  craft: 64,
  net_color: 64,
  size: 64,
  length: 32,
  density: 32,
  hair_style_series: 64,
}

function cleanValue(value) {
  return typeof value === 'string' ? value.trim() : value
}

export function attributeFieldLabel(productType, field) {
  if (field === 'craft') return productType === 'piece' ? '工艺/尺寸' : '头套工艺'
  return {
    length: '发长',
    net_color: '网帽颜色',
    size: '头套尺码',
    density: '发量',
    hair_style_series: '发型系列',
  }[field] || field
}

export function visibleAttributeFields(attrs) {
  if (attrs.product_type === 'piece') return PIECE_FIELDS
  return cleanValue(attrs.length) === '15厘米' ? [...CAP_FIELDS, 'density'] : CAP_FIELDS
}

export function requiredAttributeFields(attrs) {
  if (attrs.product_type === 'piece') return PIECE_FIELDS
  const fields = ['craft', 'length', 'size', 'hair_style_series']
  return cleanValue(attrs.length) === '15厘米' ? [...fields, 'density'] : fields
}

export function attributeOptions(options, orderCategory, productType, field) {
  const standardType = options.attr_dicts?.[productType]?.[field]
  if (!standardType) return []
  const standard = (options.standard_values?.[standardType] || []).map(cleanValue)
  if (orderCategory !== 'special') return standard
  const specialType = options.special_attr_dicts?.[productType]?.[field]
  const special = specialType
    ? (options.special_values?.[specialType] || []).map(cleanValue)
    : []
  return [...new Set([...standard, ...special])]
}

export function clearNonstandardAttributes(attrs, options) {
  const removedFields = []
  for (const field of visibleAttributeFields(attrs)) {
    const value = cleanValue(attrs[field])
    attrs[field] = value || ''
    if (!value) continue
    const standardType = options.attr_dicts?.[attrs.product_type]?.[field]
    const standardValues = (options.standard_values?.[standardType] || []).map(cleanValue)
    if (!standardValues.includes(value)) {
      attrs[field] = ''
      removedFields.push(field)
    }
  }
  if (attrs.product_type === 'cap' && cleanValue(attrs.length) !== '15厘米') {
    if (cleanValue(attrs.density) && !removedFields.includes('density')) removedFields.push('density')
    attrs.density = ''
  }
  return removedFields
}

export function validateItemAttributes(attrs) {
  for (const field of visibleAttributeFields(attrs)) {
    attrs[field] = cleanValue(attrs[field]) || ''
  }
  for (const field of requiredAttributeFields(attrs)) {
    if (!attrs[field]) return `${attributeFieldLabel(attrs.product_type, field)}不能为空`
  }
  for (const field of visibleAttributeFields(attrs)) {
    const maxLength = ATTRIBUTE_MAX_LENGTHS[field]
    if (attrs[field] && attrs[field].length > maxLength) {
      return `${attributeFieldLabel(attrs.product_type, field)}最多输入${maxLength}个字符`
    }
  }
  return ''
}

export function normalizeItemAttrs(attrs) {
  return Object.fromEntries([
    ['product_type', attrs.product_type],
    ...visibleAttributeFields(attrs).map(field => [field, cleanValue(attrs[field])]),
  ].filter(([, value]) => value !== '' && value !== null && value !== undefined))
}

export function clearInapplicableAttributes(attrs) {
  for (const field of ATTRIBUTE_FIELDS) attrs[field] = cleanValue(attrs[field]) || ''
  const applicable = new Set(visibleAttributeFields(attrs))
  for (const field of ATTRIBUTE_FIELDS) {
    if (!applicable.has(field)) attrs[field] = ''
  }
  return attrs
}

export function routeForItem(item, orderCategory, craftRoutes, defaultRoutes, standardCrafts = []) {
  const { product_type: productType } = item.attrs
  const craft = cleanValue(item.attrs.craft)
  if (!craft) return null
  const exact = craftRoutes.find(route => (
    route.product_type === productType && cleanValue(route.craft) === craft
  ))
  if (exact) return exact
  const isCustomCraft = !standardCrafts.map(cleanValue).includes(craft)
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
