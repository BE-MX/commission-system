// Build-time presentation catalog. Executable routes and source access rules stay in navigation.js.
export function buildNavigationCatalog(groups, entries, icons) {
  const iconName = component => {
    const key = Object.keys(icons).find(key => icons[key] === component)
      || component?.name
      || Object.keys(icons).find(key => component?.__name && icons[key]?.__name === component.__name)
    if (!key || !icons[key]) throw new Error(`Unregistered navigation icon: ${component?.name || component?.__name || 'missing'}`)
    return key
  }
  const nodes = Object.entries(groups).map(([id, group], index) => ({
    id, kind: 'group', label: group.title, icon: iconName(group.icon), parent: '', order: index + 20,
    visible: true, builtin: true, protected: id === 'system', badge: group.iconBadge || '',
    badgePlace: group.iconBadge ? 'icon' : 'text', badgeTone: 'gold', titleSync: false,
  }))
  for (const entry of entries.filter(e => e.menu && !e.hideInMenu)) {
    nodes.push({
      id: entry.name || entry.path, kind: 'page', label: entry.menu.title || entry.title,
      icon: iconName(entry.menu.icon), parent: entry.menu.group || '', order: entry.menu.order ?? 999,
      visible: true, builtin: true, protected: ['Dashboard', 'NavigationManagement'].includes(entry.name),
      badge: '', badgePlace: 'text', badgeTone: 'gold', titleSync: false,
      path: entry.path, external: entry.external === true, rule: [entry.permission, ...(entry.anyPermission || []), entry.menu.permission,
        ...(entry.menu.anyPermission || []), ...(groups[entry.menu.group]?.anyPermission || [])].filter(Boolean).join(' / '),
      business: entry.menu.badge || entry.menu.anomalyDomain || '', phase: Boolean(entry.menu.commercePhases),
    })
  }
  return { nodes, icons: Object.keys(icons).filter(key => /^[A-Z]/.test(key)).sort() }
}
