const PRODUCT_NAMES = new Set(['customer_product_type', 'product_type_customer', 'product_type'])
const isProductLabel = label => ['产品类型', 'product type'].includes(String(label || '').trim().toLowerCase())

export function groupMediaByTags(assets = [], dimensions = []) {
  const productDimension = dimensions.find(dim => PRODUCT_NAMES.has(dim.name) || isProductLabel(dim.label))
  const productId = productDimension?.id
  const groups = new Map()
  for (const asset of assets) {
    const productTags = (asset.tags || []).filter(tag =>
      productId != null ? tag.dimension_id === productId : isProductLabel(tag.dimension_label))
    for (const tag of productTags.length ? productTags : [null]) {
      const id = tag?.tag_value_id ?? 'unassigned'
      if (!groups.has(id)) groups.set(id, { id, label: tag?.value || '未设置产品类型', assets: [] })
      if (!groups.get(id).assets.some(item => item.id === asset.id)) groups.get(id).assets.push(asset)
    }
  }
  const rank = new Map(dimensions.map((dim, index) => [dim.id, index]))
  const result = [...groups.values()].map(group => {
    const filters = new Map()
    for (const asset of group.assets) {
      for (const tag of asset.tags || []) {
        if (tag.dimension_id === productId || isProductLabel(tag.dimension_label)) continue
        if (!filters.has(tag.dimension_id)) {
          const dimension = dimensions.find(dim => dim.id === tag.dimension_id)
          filters.set(tag.dimension_id, { id: tag.dimension_id, label: tag.dimension_label || dimension?.label || '客户标签', values: new Map() })
        }
        filters.get(tag.dimension_id).values.set(tag.tag_value_id, { id: tag.tag_value_id, value: tag.value })
      }
    }
    return { ...group, filters: [...filters.values()]
      .sort((a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity) || a.id - b.id)
      .map(filter => ({ ...filter, values: [...filter.values.values()] })) }
  })
  return result.sort((a, b) => (a.id === 'unassigned') - (b.id === 'unassigned'))
}

export function filterMediaByTags(assets = [], selectedIds = []) {
  if (!selectedIds.length) return assets
  const ids = new Set(selectedIds)
  const selectedByDimension = new Map()
  for (const asset of assets) {
    for (const tag of asset.tags || []) {
      if (ids.has(tag.tag_value_id)) {
        if (!selectedByDimension.has(tag.dimension_id)) selectedByDimension.set(tag.dimension_id, new Set())
        selectedByDimension.get(tag.dimension_id).add(tag.tag_value_id)
      }
    }
  }
  const known = [...selectedByDimension.values()].reduce((sum, values) => sum + values.size, 0)
  if (known < ids.size) return []
  return assets.filter(asset => [...selectedByDimension.entries()].every(([dimensionId, values]) =>
    (asset.tags || []).some(tag => tag.dimension_id === dimensionId && values.has(tag.tag_value_id))))
}
