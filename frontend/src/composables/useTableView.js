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
 */
import { computed, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'

const DENSITIES = ['compact', 'default', 'comfort']
let closeActiveFullscreen = null

export function useTableView(pageKey, columnDefs = []) {
  const storageKey = `${pageKey}-table-view`
  const density = ref('default')
  const visibleKeys = ref(columnDefs.map(column => column.key))

  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
    if (Array.isArray(saved?.visibleKeys)) {
      const known = new Set(columnDefs.map(column => column.key))
      const restored = saved.visibleKeys.filter(key => known.has(key))
      if (restored.length) visibleKeys.value = restored
    }
    if (DENSITIES.includes(saved?.density)) density.value = saved.density
  } catch { /* 本地偏好损坏时忽略，使用默认视图 */ }

  watch([density, visibleKeys], () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ density: density.value, visibleKeys: visibleKeys.value }))
    } catch { /* 隐私模式等写入失败时忽略 */ }
  }, { deep: true })

  const densityClass = computed(() => `density-${density.value}`)
  const visibleColumns = computed(() => columnDefs.filter(column => visibleKeys.value.includes(column.key)))

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
    if (event.key === 'Escape' && !document.querySelector?.('.el-overlay')) closeFullscreen()
  }
  onMounted(() => document.addEventListener('keydown', onKeydown))
  onDeactivated(closeFullscreen)
  onUnmounted(() => {
    document.removeEventListener('keydown', onKeydown)
    closeFullscreen()
  })

  return { density, densityClass, visibleKeys, visibleColumns, panelRef, isFullscreen, toggleFullscreen }
}
