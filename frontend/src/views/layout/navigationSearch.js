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
