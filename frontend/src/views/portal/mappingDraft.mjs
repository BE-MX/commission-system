export const mappingKinds = { model: '型号别名', color: '颜色别名', sku: '单规格型号名 / 客户货号' }
export const mappingConflicts = { COLOR_AMBIGUOUS: '不同标准颜色映射为同一颜色名', SPEC_AMBIGUOUS: '不同 SKU 的展示规格完全相同', CUSTOMER_SKU_DUPLICATE: '客户货号重复' }
export function sourceOptions(sources, kind) {
  const unique = new Map()
  for (const item of sources) {
    const value = kind === 'sku' ? item.item_id : item[`${kind}_key`]
    if (!unique.has(value)) unique.set(value, { value, label: kind === 'sku'
      ? `${item.model_name} / ${item.color_name} · 长度 ${item.length} · 重量 ${item.weight} · ${item.unit} · ${item.item_id}`
      : `${item[`${kind}_name`]} · ${value}` })
  }
  return [...unique.values()]
}
export function invalidEntries(sources, entries) {
  const allowed = Object.fromEntries(['model', 'color', 'sku'].map(kind => [kind, new Set(sourceOptions(sources, kind).map(option => option.value))]))
  return entries.map((entry, index) => ({ entry, index })).filter(({ entry }) => !allowed[entry.kind]?.has(entry.source_key))
}
export function mappingPayload(baseVersion, entries) {
  return { base_version: baseVersion, entries: entries.map(entry => ({ kind: entry.kind, source_key: entry.source_key, display_value: entry.display_value,
    ...(entry.kind === 'sku' ? { item_id: entry.source_key, ...(entry.customer_sku ? { customer_sku: entry.customer_sku } : {}) } : {}) })) }
}
