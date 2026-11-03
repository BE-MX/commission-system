import { canConfigureNavigation } from './favoriteNavigationState.js'

export function normalizeNavigationQuery(query) {
  return String(query || '').trim().toLocaleLowerCase()
}

export function filterNavigationSections(topLevelItems, groups, query) {
  const keyword = normalizeNavigationQuery(query)
  if (!keyword) return { topLevelItems, groups }
  const matches = title => normalizeNavigationQuery(title).includes(keyword)
  const filterGroup = group => ({ ...group, items: matches(group.title) ? group.items : group.items
    .map(item => item.items ? filterGroup(item) : item)
    .filter(item => item.items ? item.items.length : matches(item.title)) })
  return { topLevelItems: topLevelItems.filter(item => matches(item.title)), groups: groups.map(filterGroup).filter(group => group.items.length) }
}

// Authorize immutable source entries before applying any editable presentation parent.
export function accessibleNavigationSections(entries, groups, auth, context = {}, nodes = [], icons = {}) {
  const overrides = new Map((Array.isArray(nodes) ? nodes : []).map(node => [node.id, node]))
  const decoration = (source, override = {}) => ({
    title: override.label ?? source.title,
    icon: typeof override.icon === 'string' ? (icons[override.icon] || source.icon) : source.icon,
    textBadge: override.badge ?? '', badgePlace: override.badgePlace || 'label', badgeTone: override.badgeTone || 'gold',
  })
  const groupNodes = new Map(Object.entries(groups).map(([key, group], order) => {
    const override = overrides.get(key) || {}
    return [key, { key, ...group, ...decoration(group, override), iconBadge: override.badge === undefined ? group.iconBadge : undefined,
      parent: override.parent ?? null, order: override.order ?? order, visible: override.visible !== false, items: [] }]
  }))
  for (const node of overrides.values()) {
    if (node.kind === 'group' && !groupNodes.has(node.id) && node.id.startsWith('custom-')) groupNodes.set(node.id,
      { key: node.id, ...decoration({}, node), parent: node.parent ?? null, order: node.order ?? 999, visible: node.visible !== false, items: [] })
  }
  const visibleParent = key => {
    const seen = new Set()
    while (key) {
      const group = groupNodes.get(key)
      if (!group || !group.visible || seen.has(key) || seen.size >= 2) return false
      seen.add(key); key = group.parent
    }
    return true
  }
  const topLevelItems = []
  for (const entry of entries) {
    if (!canConfigureNavigation(entry, groups, auth, context)) continue
    const override = overrides.get(entry.name || entry.path) || {}
    const parent = Object.hasOwn(override, 'parent') ? override.parent : entry.menu.group || null
    if (override.visible === false || !visibleParent(parent)) continue
    const item = { path: entry.path, name: entry.name, ...decoration({ title: entry.menu.title ?? entry.title, icon: entry.menu.icon }, override),
      external: entry.external === true, badge: entry.menu.badge, anomalyDomain: entry.menu.anomalyDomain, order: override.order ?? entry.menu.order ?? 999 }
    if (parent) groupNodes.get(parent).items.push(item)
    else topLevelItems.push(item)
  }
  for (const group of groupNodes.values()) {
    if (group.parent && visibleParent(group.key)) groupNodes.get(group.parent).items.push(group)
  }
  const sortAndPrune = items => items.filter(item => !item.items || (item.items = sortAndPrune(item.items)).length)
    .sort((a, b) => (a.order ?? 999) - (b.order ?? 999))
  return { topLevelItems: sortAndPrune(topLevelItems), groups: sortAndPrune([...groupNodes.values()].filter(group => !group.parent && group.visible)) }
}
export function quickNavigationItems(sections, query = '') {
  const words = normalizeNavigationQuery(query).split(/\s+/).filter(Boolean)
  const flatten = (items, ancestors) => items.flatMap(item => item.items
    ? flatten(item.items, [...ancestors, item.title])
    : [{ ...item, groupTitle: ancestors.join(' / ') || '一级页面' }])
  return [...flatten(sections.topLevelItems, []), ...flatten(sections.groups, [])]
    .filter(item => words.every(word => normalizeNavigationQuery(`${item.title} ${item.groupTitle}`).includes(word)))
}
export function isQuickNavigationShortcut(event) {
  return !event.defaultPrevented && !event.repeat && !event.isComposing && event.keyCode !== 229 && !event.altKey
    && (event.ctrlKey || event.metaKey) && event.key?.toLowerCase() === 'k'
}
