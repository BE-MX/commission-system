/**
 * 表格视图状态（列显隐 + 行密度 + 全屏），Action Bar Spec 配套基建。
 *
 * 用法：
 *   const { density, densityClass, visibleKeys, visibleColumns, panelRef, isFullscreen, toggleFullscreen } =
 *     useTableView('invoice-manage', columnDefs)
 *
 * - 状态持久化到 localStorage 的 `<pageKey>-table-view`（页面级，不入全局 store）
 * - panelRef 挂在表格卡片元素上，toggleFullscreen 配合 TableTools 的全屏图标
 * - densityClass 直接挂到 el-table 的 :class，密度档位样式由 app.css 全局类消费 tokens.css 令牌
 * - 列默认显示；defaultVisible: false 可默认隐藏。v1 记录 knownColumnKeys，新增列按默认策略加入。
 * - TableTools 的恢复默认通过现有 v-model 恢复当前列集合与默认密度，无需额外页面事件。
 */
import { computed, onDeactivated, onMounted, onUnmounted, ref, toValue, watch } from 'vue'
import {
  DEFAULT_TABLE_DENSITY, TABLE_DENSITIES, TABLE_VIEW_VERSION,
  normalizeTableColumns, normalizeTableVisibleKeys, restoreTablePreferences,
} from '../utils/tableViewPreferences.js'

let closeActiveFullscreen = null

export function useTableView(pageKey, columnDefs = []) {
  const storageKey = `${pageKey}-table-view`
  const columns = computed(() => normalizeTableColumns(toValue(columnDefs)))
  let saved = null
  try {
    saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
  } catch { /* 本地偏好损坏时忽略，使用默认视图 */ }
  const restored = restoreTablePreferences(saved, columns.value)
  const density = ref(restored.density)
  const visibleKeys = ref(restored.visibleKeys)

  watch(columns, (current, previous) => {
    const known = new Set(previous.map(column => column.key))
    visibleKeys.value = normalizeTableVisibleKeys([
      ...visibleKeys.value,
      ...current.filter(column => !known.has(column.key) && column.defaultVisible !== false).map(column => column.key),
    ], current)
  }, { flush: 'sync' })

  watch([density, visibleKeys, columns], () => {
    const validKeys = normalizeTableVisibleKeys(visibleKeys.value, columns.value)
    if (!Array.isArray(visibleKeys.value) || validKeys.length !== visibleKeys.value.length || validKeys.some((key, index) => key !== visibleKeys.value[index])) {
      visibleKeys.value = validKeys
      return
    }
    if (!TABLE_DENSITIES.includes(density.value)) {
      density.value = DEFAULT_TABLE_DENSITY
      return
    }
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        version: TABLE_VIEW_VERSION,
        knownColumnKeys: columns.value.map(column => column.key),
        density: density.value,
        visibleKeys: visibleKeys.value,
      }))
    } catch { /* 隐私模式等写入失败时忽略 */ }
  }, { deep: true, immediate: true, flush: 'sync' })

  const densityClass = computed(() => `density-${density.value}`)
  const visibleColumns = computed(() => columns.value.filter(column => visibleKeys.value.includes(column.key)))

  const panelRef = ref(null)
  const isFullscreen = ref(false)
  let previousBodyOverflow = ''
  let fullscreenAncestors = []
  function closeFullscreen() {
    if (!isFullscreen.value) return
    panelRef.value?.classList.remove('table-card--fullscreen')
    fullscreenAncestors.forEach(element => element.classList.remove('table-fullscreen-ancestor'))
    fullscreenAncestors = []
    isFullscreen.value = false
    document.body.style.overflow = previousBodyOverflow
    if (closeActiveFullscreen === closeFullscreen) closeActiveFullscreen = null
  }
  function toggleFullscreen() {
    if (isFullscreen.value) return closeFullscreen()
    if (!panelRef.value) return
    closeActiveFullscreen?.()
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    for (let element = panelRef.value.parentElement; element && element !== document.body; element = element.parentElement) {
      element.classList.add('table-fullscreen-ancestor')
      fullscreenAncestors.push(element)
    }
    panelRef.value.classList.add('table-card--fullscreen')
    isFullscreen.value = true
    closeActiveFullscreen = closeFullscreen
  }
  function onKeydown(event) {
    const visibleOverlay = [...document.querySelectorAll('.el-overlay')].some(element =>
      element.getClientRects().length > 0 && document.defaultView?.getComputedStyle(element).visibility !== 'hidden',
    )
    if (event.key === 'Escape' && !visibleOverlay) closeFullscreen()
  }
  onMounted(() => document.addEventListener('keydown', onKeydown))
  onDeactivated(closeFullscreen)
  onUnmounted(() => {
    document.removeEventListener('keydown', onKeydown)
    closeFullscreen()
  })

  return { density, densityClass, visibleKeys, visibleColumns, panelRef, isFullscreen, toggleFullscreen }
}
