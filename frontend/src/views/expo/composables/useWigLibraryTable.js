/**
 * 试戴发型库表格视图状态（列显隐/密度/全屏 + 筛选重置），List Page Spec / Action Bar Spec 配套。
 * columnDefs 只供 TableTools 列显隐面板，模板列保持静态（推广期不配置化渲染）。
 */
import { computed } from 'vue'
import { useTableView } from '@/composables/useTableView'

const columnDefs = [
  { key: 'cover', label: '封面' },
  { key: 'model-no', label: '型号' },
  { key: 'name', label: '名称' },
  { key: 'series', label: '系列' },
  { key: 'fit-tags', label: '适配标签' },
  { key: 'sell-positions', label: '销售定位' },
  { key: 'priority', label: '优先级' },
  { key: 'must-recommend', label: '主推' },
  { key: 'is-active', label: '启用' },
]

export function useWigLibraryTable(keyword, reload) {
  const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
    useTableView('wig-library', columnDefs)
  const hasActiveFilters = computed(() => Boolean(keyword.value.trim()))
  function resetFilters() {
    keyword.value = ''
    reload()
  }
  return { columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen, hasActiveFilters, resetFilters }
}
