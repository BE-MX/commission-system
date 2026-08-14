/**
 * 最近使用导航 — 工作台「快速跳转」的数据源。
 *
 * 纯 util（不依赖 vue/pinia），由 router/index.js 的 afterEach 写入，
 * 工作台 QuickNav 读取。localStorage 持久化，按 name 去重、最近访问在前。
 */

const STORAGE_KEY = 'ark_recent_nav_v1'
const MAX_ITEMS = 16

export function recordRecentNav(entry) {
  if (!entry?.name || !entry?.path) return
  try {
    const list = getRecentNav().filter(item => item.name !== entry.name)
    list.unshift({ name: entry.name, path: entry.path, ts: Date.now() })
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_ITEMS)))
  } catch { /* 隐私模式等场景写入失败直接忽略 */ }
}

export function getRecentNav() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}
