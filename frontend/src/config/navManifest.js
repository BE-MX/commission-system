/**
 * 导航配置 → 任务中心模块清单（纯函数）。
 * 构建期由 scripts/navManifestPlugin.js 调用并写出 dist/nav-manifest.json，后端启动时同步到
 * ark_task_modules。模块键用路由 name（唯一且稳定）；sort = 分组序号*1000 + 组内 order，
 * 后端按 sort 排序即可还原导航顺序。
 */
export const NAV_MANIFEST_VERSION = 1

export function buildNavManifest(menuGroups, navEntries, gitSha = null) {
  const groupKeys = Object.keys(menuGroups)
  const entries = navEntries
    .filter(entry => entry.menu && !entry.hideInMenu && !entry.external && entry.name)
    .map(entry => {
      const groupKey = entry.menu.group || 'top'
      const groupIndex = entry.menu.group ? groupKeys.indexOf(groupKey) + 1 : 0
      return {
        key: entry.name,
        title: entry.menu.title ?? entry.title,
        group_key: groupKey,
        group_title: entry.menu.group ? (menuGroups[groupKey]?.title ?? groupKey) : '一级页面',
        route: entry.path,
        sort: groupIndex * 1000 + (entry.menu.order ?? 999),
      }
    })
  const seen = new Set()
  for (const entry of entries) {
    if (seen.has(entry.key)) throw new Error(`导航路由 name 重复：${entry.key}`)
    seen.add(entry.key)
  }
  // Separate from task modules, including external menus. Permissions still have
  // one source: navigation.js. Backend validates newly added favorites with this.
  const favoriteAccess = Object.fromEntries(navEntries
    .filter(entry => entry.menu && !entry.hideInMenu)
    .map(entry => {
      const group = entry.menu.group ? menuGroups[entry.menu.group] : null
      if (entry.menu.group && !group) throw new Error(`未知导航分组：${entry.menu.group}`)
      const rules = [entry, entry.menu, group].filter(Boolean).map(rule => ({
        ...(rule.permission ? { permission: rule.permission } : {}),
        ...(rule.anyPermission ? { anyPermission: rule.anyPermission } : {}),
      }))
      return [entry.name || entry.path, rules]
    }))
  return { version: NAV_MANIFEST_VERSION, git_sha: gitSha, entries, favorite_access: favoriteAccess }
}
