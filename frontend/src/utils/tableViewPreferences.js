export const TABLE_VIEW_VERSION = 1
export const DEFAULT_TABLE_DENSITY = 'default'
export const TABLE_DENSITIES = ['compact', 'default', 'comfort']

export function normalizeTableColumns(columns) {
  const seen = new Set()
  return (Array.isArray(columns) ? columns : []).filter(column => {
    if (typeof column?.key !== 'string' || !column.key || seen.has(column.key)) return false
    seen.add(column.key)
    return true
  })
}

export function defaultTableColumnKeys(columns) {
  const available = normalizeTableColumns(columns)
  const defaults = available.filter(column => column.defaultVisible !== false).map(column => column.key)
  return defaults.length ? defaults : available.slice(0, 1).map(column => column.key)
}

export function normalizeTableVisibleKeys(keys, columns) {
  const known = new Set(normalizeTableColumns(columns).map(column => column.key))
  const visible = [...new Set(Array.isArray(keys) ? keys : [])].filter(key => known.has(key))
  return visible.length ? visible : defaultTableColumnKeys(columns)
}

export function restoreTablePreferences(saved, columns) {
  const available = normalizeTableColumns(columns)
  const defaults = { density: DEFAULT_TABLE_DENSITY, visibleKeys: defaultTableColumnKeys(available) }
  if (!saved || !Array.isArray(saved.visibleKeys)) return defaults
  const legacy = saved.version === undefined
  if (!legacy && (saved.version !== TABLE_VIEW_VERSION || !Array.isArray(saved.knownColumnKeys))) return defaults

  // Legacy preferences did not record the column schema. Treat current keys as
  // known on the first upgrade so previously hidden columns stay hidden.
  const known = new Set(legacy ? available.map(column => column.key) : saved.knownColumnKeys)
  const visibleKeys = saved.visibleKeys.filter(key => known.has(key))
  visibleKeys.push(...available.filter(column => !known.has(column.key) && column.defaultVisible !== false).map(column => column.key))
  return {
    density: TABLE_DENSITIES.includes(saved.density) ? saved.density : DEFAULT_TABLE_DENSITY,
    visibleKeys: normalizeTableVisibleKeys(visibleKeys, available),
  }
}

// TableTools may receive only the active tab's columns while its v-model holds
// all tabs' keys. Reset/repair that subset without erasing other tabs' choices.
export function resetTableColumnSubset(keys, columns) {
  const available = new Set(normalizeTableColumns(columns).map(column => column.key))
  const outside = (Array.isArray(keys) ? keys : []).filter(key => typeof key === 'string' && !available.has(key))
  return [...new Set([...outside, ...defaultTableColumnKeys(columns)])]
}
