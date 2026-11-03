export const editableFields = ['id', 'kind', 'label', 'icon', 'parent', 'order', 'visible', 'badge', 'badgePlace', 'badgeTone', 'titleSync']
export function writableNodes(nodes) {
  return nodes.map(node => Object.fromEntries(editableFields.map(key => [key, key === 'label' || key === 'badge' ? String(node[key] || '').trim() : node[key]])))
}
export function mergeNodes(catalog, draft) {
  const source = new Map(catalog.map(node => [node.id, node]))
  const result = draft.map(node => ({ ...source.get(node.id), ...node, originalLabel: source.get(node.id)?.label, external: source.get(node.id)?.external, builtin: source.get(node.id)?.builtin ?? false, protected: source.get(node.id)?.protected ?? false, missing: node.kind === 'page' && !source.has(node.id) }))
  const ids = new Set(result.map(node => node.id))
  return [...result, ...catalog.filter(node => !ids.has(node.id)).map(node => ({ ...node, originalLabel: node.label }))]
}
export function childrenOf(nodes, parent = '') {
  return nodes.filter(node => (node.parent || '') === parent).sort((a, b) => a.order - b.order)
}
export function nextSiblingOrder(nodes, parent = '', excludedId = '') {
  return Math.max(-1, ...nodes.filter(node => (node.parent || '') === parent && node.id !== excludedId).map(node => Number(node.order) || 0)) + 1
}
export function sameWritableNodes(left, right) {
  const canonical = nodes => JSON.stringify(writableNodes(nodes).sort((a, b) => a.id.localeCompare(b.id)))
  return canonical(left) === canonical(right)
}
export function descendantIds(nodes, id) {
  const found = new Set([id])
  for (let changed = true; changed;) {
    changed = false
    for (const node of nodes) if (found.has(node.parent) && !found.has(node.id)) { found.add(node.id); changed = true }
  }
  return found
}
export function validateNodes(nodes, icons) {
  const errors = []
  const ids = new Map(nodes.map(node => [node.id, node]))
  const names = new Set()
  for (const node of nodes) {
    const label = String(node.label || '').trim()
    const key = `${node.parent || ''}:${label.normalize('NFKC').toLocaleLowerCase()}`
    const fail = message => errors.push({ id: node.id, message: `${label || '未命名'}：${message}` })
    if (!label || [...label].length > 24 || /[\p{Cc}\p{Cf}]/u.test(label)) fail('名称需为 1–24 个字符')
    if (names.has(key)) fail('同级名称重复')
    names.add(key)
    if ([...String(node.badge || '').trim()].length > 8 || /[\p{Cc}\p{Cf}]/u.test(String(node.badge || ''))) fail('角标最多 8 个字符')
    if (node.icon && !icons.includes(node.icon)) fail('请选择目录中的图标')
    if (node.missing) fail('页面已下线，请移除失效引用')
    if (node.external && !node.parent) fail('外部入口必须归属分类')
    if (node.parent && (!ids.has(node.parent) || ids.get(node.parent).kind !== 'group')) fail('所属分类无效')
    const seen = new Set([node.id]); let parent = ids.get(node.parent); let depth = 0
    while (parent) {
      if (seen.has(parent.id)) { fail('分类不能循环'); break }
      seen.add(parent.id); depth++; parent = ids.get(parent.parent)
    }
    if (node.kind === 'group' && depth > 1 || node.kind === 'page' && depth > 2) fail('分类最多两级')
    if (node.protected && node.visible === false) fail('受保护节点必须显示')
  }
  return errors
}
export function reorderNode(nodes, id, targetId) {
  const source = nodes.find(node => node.id === id), target = nodes.find(node => node.id === targetId)
  if (!source || !target || source.parent !== target.parent || id === targetId) return false
  const siblings = childrenOf(nodes, source.parent)
  siblings.splice(siblings.indexOf(source), 1); siblings.splice(siblings.indexOf(target), 0, source)
  siblings.forEach((node, index) => { node.order = index })
  return true
}
export function diffNodes(before, after) {
  const fields = editableFields.filter(key => !['id', 'kind'].includes(key))
  const old = new Map(before.map(node => [node.id, node]))
  const names = { label: '名称', icon: '图标', parent: '归属分类', order: '顺序', visible: '显示', badge: '角标', badgePlace: '角标位置', badgeTone: '角标色调', titleSync: '同步标题' }
  const changes = []
  for (const node of after) {
    const previous = old.get(node.id)
    if (!previous) changes.push({ id: node.id, label: node.label, field: '新增', before: '—', after: node.kind === 'group' ? '分类' : '页面' })
    else for (const key of fields) if ((previous[key] ?? '') !== (node[key] ?? '')) changes.push({ id: node.id, label: node.label, field: names[key], before: String(previous[key] ?? '—'), after: String(node[key] ?? '—') })
    old.delete(node.id)
  }
  for (const node of old.values()) changes.push({ id: node.id, label: node.label, field: '删除', before: node.label, after: '—' })
  return changes
}
