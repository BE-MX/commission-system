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

export function productTypeOptions(assets = [], dimensions = []) {
  return groupMediaByTags(assets, dimensions)
    .filter(group => group.id !== 'unassigned')
    .map(group => ({ id: group.id, value: group.label }))
}

export function filterProductGroups(groups = [], selectedIds = []) {
  if (!selectedIds.length) return groups
  const selected = new Set(selectedIds.map(String))
  return groups.filter(group => selected.has(String(group.id)))
}

export function filterMediaByProductTypes(assets = [], selectedIds = [], dimensions = []) {
  if (!selectedIds.length) return assets
  const visibleIds = new Set(filterProductGroups(groupMediaByTags(assets, dimensions), selectedIds)
    .flatMap(group => group.assets.map(asset => asset.id)))
  return assets.filter(asset => visibleIds.has(asset.id))
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

const normalizeDimension = value => String(value || '').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, '')
function findDimension(dimensions, names) {
  return dimensions.find(dim => names.some(name =>
    normalizeDimension(dim.name) === name || normalizeDimension(dim.label) === name))
}

export function groupMediaByColorAndTexture(assets = [], dimensions = []) {
  const color = findDimension(dimensions, ['colornames', 'colorname', '颜色名称'])
  const texture = findDimension(dimensions, ['texturestype', 'texturetype', '纹理类型'])
  const rows = new Map()
  for (const asset of assets) {
    const tags = asset.tags || []
    const colors = tags.filter(tag => color
      ? tag.dimension_id === color.id : ['colornames', 'colorname', '颜色名称'].includes(normalizeDimension(tag.dimension_label)))
    const textures = tags.filter(tag => texture
      ? tag.dimension_id === texture.id : ['texturestype', 'texturetype', '纹理类型'].includes(normalizeDimension(tag.dimension_label)))
    for (const colorTag of colors.length ? colors : [null]) {
      for (const textureTag of textures.length ? textures : [null]) {
        const id = `${colorTag?.tag_value_id ?? 'none'}:${textureTag?.tag_value_id ?? 'none'}`
        if (!rows.has(id)) rows.set(id, {
          id,
          colorName: colorTag?.value || '',
          textureType: textureTag?.value || '',
          assets: [],
        })
        if (!rows.get(id).assets.some(item => item.id === asset.id)) rows.get(id).assets.push(asset)
      }
    }
  }
  return [...rows.values()]
}
