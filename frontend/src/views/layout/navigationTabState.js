export const HOME_TAB = Object.freeze({
  key: 'Dashboard',
  title: '工作台',
  fullPath: '/dashboard',
  closable: false,
})

export function getTabButtonId(key) {
  return `navigation-tab-${encodeURIComponent(key)}`
}

export function getTabPanelId(key) {
  return `navigation-panel-${encodeURIComponent(key)}`
}

export function getRouteTabKey(route) {
  const routeKey = String(route.name || route.path || route.fullPath)
  const params = Object.entries(route.params || {})
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join('/') : value}`)

  return params.length ? `${routeKey}:${params.join('&')}` : routeKey
}

export function createRouteTab(route) {
  const key = getRouteTabKey(route)
  return {
    key,
    title: String(route.meta?.title || '未命名页面'),
    fullPath: String(route.fullPath || route.path || HOME_TAB.fullPath),
    closable: key !== HOME_TAB.key,
  }
}

export function upsertRouteTab(tabs, route) {
  const nextTab = createRouteTab(route)
  const existingIndex = tabs.findIndex(tab => tab.key === nextTab.key)

  if (existingIndex === -1) return [...tabs, nextTab]

  return tabs.map((tab, index) => (
    index === existingIndex ? { ...tab, ...nextTab } : tab
  ))
}

export function getAdjacentTab(tabs, closingKey) {
  const closingIndex = tabs.findIndex(tab => tab.key === closingKey)
  if (closingIndex === -1) return null
  return tabs[closingIndex + 1] || tabs[closingIndex - 1] || HOME_TAB
}
