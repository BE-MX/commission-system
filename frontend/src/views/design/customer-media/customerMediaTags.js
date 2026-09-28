// 客户素材标签的纯函数工具：统一 tags 结构 {dimension_id, dimension_label, tag_value_id, value}
// 与后端契约一致：asset.tags / tags_json / PATCH body 均由此处函数归一化。

/** 归一化单个标签项（兼容 {tag_value_id} 与素材库风格的 {id}） */
export function normalizeTag(tag, dimensions = []) {
  const tagValueId = tag.tag_value_id ?? tag.id
  const dim = dimensions.find(d => d.id === tag.dimension_id)
  const dimValue = dim?.values?.find(v => v.id === tagValueId)
  return {
    dimension_id: tag.dimension_id,
    dimension_label: tag.dimension_label || dim?.label || '',
    tag_value_id: tagValueId,
    value: tag.value ?? dimValue?.value ?? String(tagValueId ?? ''),
  }
}

/** 拍平标签数组 → 契约 tags_json / PATCH body 结构 [{dimension_id, tag_value_ids}] */
export function groupTagsByDimension(tags) {
  const grouped = new Map()
  for (const tag of tags || []) {
    const tagValueId = tag.tag_value_id ?? tag.id
    if (tag.dimension_id == null || tagValueId == null) continue
    if (!grouped.has(tag.dimension_id)) grouped.set(tag.dimension_id, [])
    const ids = grouped.get(tag.dimension_id)
    if (!ids.includes(tagValueId)) ids.push(tagValueId)
  }
  return [...grouped.entries()].map(([dimension_id, tag_value_ids]) => ({ dimension_id, tag_value_ids }))
}

/** 维度选择状态（{dimId: [ids] | id}）→ 拍平标签数组（带维度/值文案，供 chip 展示与上传） */
export function flattenSelection(selection, dimensions = []) {
  const flat = []
  for (const dim of dimensions) {
    const raw = selection?.[dim.id]
    const ids = (Array.isArray(raw) ? raw : [raw]).filter(v => v != null && v !== '')
    for (const id of ids) {
      const value = dim.values?.find(v => v.id === id)
      flat.push({
        dimension_id: dim.id,
        dimension_label: dim.label || '',
        tag_value_id: id,
        value: value?.value ?? String(id),
      })
    }
  }
  return flat
}

/** 从标签数组还原维度选择状态（TagPicker 回填用） */
export function selectionFromTags(tags, dimensions = []) {
  const selection = {}
  for (const dim of dimensions) {
    selection[dim.id] = dim.is_single_select ? null : []
  }
  for (const tag of tags || []) {
    const tagValueId = tag.tag_value_id ?? tag.id
    if (tag.dimension_id == null || tagValueId == null) continue
    const dim = dimensions.find(d => d.id === tag.dimension_id)
    if (!dim) continue
    if (dim.is_single_select) selection[dim.id] = tagValueId
    else if (!selection[dim.id].includes(tagValueId)) selection[dim.id].push(tagValueId)
  }
  return selection
}
