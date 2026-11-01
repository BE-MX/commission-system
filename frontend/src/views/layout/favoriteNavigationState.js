export function normalizeFavoriteKeys(keys) {
  return Array.isArray(keys) ? [...new Set(keys.filter(key => typeof key === 'string' && key.length > 0))] : []
}

// context.commercePhase: the platform trading phase (null while unknown). Callers that
// only check permissions (manifest parity, role tooling) omit it and skip the phase rule.
export function canConfigureNavigation(entry, groups, auth, context = {}) {
  if (!auth.user || !entry?.menu || entry.hideInMenu) return false
  const phases = entry.menu.commercePhases
  if (phases && 'commercePhase' in context && !phases.includes(context.commercePhase)) return false
  const group = entry.menu.group ? groups[entry.menu.group] : null
  if (entry.menu.group && !group) return false
  // Route guards check both declarations; a permissive menu must not widen them.
  return [entry, entry.menu, group].every(rule => !rule || (
    (!rule.permission || auth.hasPermission(rule.permission))
    && (!rule.anyPermission || auth.hasAnyPermission(rule.anyPermission))
  ))
}

export function resolveFavoriteItems(keys, available) {
  const entries = new Map(available.map(item => [item.name, item]))
  return normalizeFavoriteKeys(keys).map(key => entries.get(key)).filter(Boolean)
}

// Reorder only visible slots; temporarily inaccessible saved entries retain their places.
export function reorderFavoriteKeys(keys, visibleOrder) {
  const visible = new Set(visibleOrder)
  let index = 0
  return normalizeFavoriteKeys(keys).map(key => visible.has(key) ? visibleOrder[index++] : key)
}
