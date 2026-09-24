// A media file can appear under more than one customer label. Grouping reuses
// references to the same file; it never creates another delivery or download.
export function groupMediaByTags(assets = [], dimensions = []) {
  const groups = new Map()
  const rank = new Map(dimensions.map((dim, index) => [dim.id, index]))
  const unlabeled = []
  for (const asset of assets) {
    const tags = asset.tags || []
    if (!tags.length) unlabeled.push(asset)
    for (const tag of tags) {
      if (!groups.has(tag.dimension_id)) {
        groups.set(tag.dimension_id, {
          id: tag.dimension_id,
          label: tag.dimension_label || dimensions.find(dim => dim.id === tag.dimension_id)?.label || '客户标签',
          buckets: new Map(),
        })
      }
      const group = groups.get(tag.dimension_id)
      if (!group.buckets.has(tag.tag_value_id)) {
        group.buckets.set(tag.tag_value_id, { id: tag.tag_value_id, label: tag.value, assets: [] })
      }
      group.buckets.get(tag.tag_value_id).assets.push(asset)
    }
  }
  const result = [...groups.values()]
    .sort((a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity) || a.id - b.id)
    .map(group => ({ ...group, buckets: [...group.buckets.values()] }))
  if (unlabeled.length) result.push({ id: 'unlabeled', label: '未打标签', buckets: [{ id: 'unlabeled', label: '未打标签', assets: unlabeled }] })
  return result
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
  // Callers supply IDs from the visible dimension list. Unknown IDs match none.
  const known = [...selectedByDimension.values()].reduce((sum, values) => sum + values.size, 0)
  if (known < ids.size) return []
  return assets.filter(asset => [...selectedByDimension.entries()].every(([dimensionId, values]) =>
    (asset.tags || []).some(tag => tag.dimension_id === dimensionId && values.has(tag.tag_value_id))))
}
