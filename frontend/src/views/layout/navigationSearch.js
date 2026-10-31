import { canConfigureNavigation } from './favoriteNavigationState.js'

export function normalizeNavigationQuery(query) {
  return String(query || '').trim().toLocaleLowerCase()
}

export function filterNavigationSections(topLevelItems, groups, query) {
  const keyword = normalizeNavigationQuery(query)
  if (!keyword) return { topLevelItems, groups }

  const matches = title => String(title).toLocaleLowerCase().includes(keyword)
  return {
    topLevelItems: topLevelItems.filter(item => matches(item.title)),
    groups: groups
      .map(group => ({
        ...group,
        items: matches(group.title)
          ? group.items
          : group.items.filter(item => matches(item.title)),
      }))
      .filter(group => group.items.length > 0),
  }
}


// One authorized source for sidebar, favorites and the command panel.
export function accessibleNavigationSections(entries, groups, auth) {
  const allowed = entries.filter(entry => canConfigureNavigation(entry, groups, auth))
  const items = group => allowed.filter(entry => (entry.menu.group || '') === group)
    .sort((a, b) => (a.menu.order ?? 999) - (b.menu.order ?? 999))
    .map(entry => ({ path: entry.path, name: entry.name, title: entry.menu.title ?? entry.title, icon: entry.menu.icon, external: entry.external === true, badge: entry.menu.badge, anomalyDomain: entry.menu.anomalyDomain }))
  return { topLevelItems: items(''), groups: Object.entries(groups).map(([key, group]) => ({ key, ...group, items: items(key) })).filter(group => group.items.length) }
}
export function quickNavigationItems(sections, query = '') {
  const words = normalizeNavigationQuery(query).split(/\s+/).filter(Boolean)
  return [
    ...sections.topLevelItems.map(item => ({ ...item, groupTitle: '一级页面' })),
    ...sections.groups.flatMap(group => group.items.map(item => ({ ...item, groupTitle: group.title }))),
  ].filter(item => words.every(word => normalizeNavigationQuery(`${item.title} ${item.groupTitle}`).includes(word)))
}
export function isQuickNavigationShortcut(event) {
  return !event.defaultPrevented && !event.repeat && !event.isComposing && event.keyCode !== 229 && !event.altKey
    && (event.ctrlKey || event.metaKey) && event.key?.toLowerCase() === 'k'
}
