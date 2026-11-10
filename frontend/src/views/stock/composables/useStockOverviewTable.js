/**
 * 销量备货一览的表格视图状态（列显隐/密度/全屏），Action Bar Spec 配套。
 * columnDefs 只供 TableTools 列显隐面板使用，模板列保持静态（推广期不做配置化渲染）。
 */
import { useTableView } from '@/composables/useTableView'

const columnDefs = [
  { key: 'model', label: '型号' },
  { key: 'type', label: '类型', defaultVisible: false },
  { key: 'size', label: '尺寸', defaultVisible: false },
  { key: 'color', label: '颜色', defaultVisible: false },
  { key: 'weight', label: '克重', defaultVisible: false },
  { key: 'sales-30d', label: '30天销量' },
  { key: 'sales-90d', label: '90天销量', defaultVisible: false },
  { key: 'avg-daily-sales', label: '日均销量', defaultVisible: false },
  { key: 'effective-enable-count', label: '可用库存' },
  { key: 'free-stock', label: '自由库存' },
  { key: 'enable-count', label: '可用库存(小满)', defaultVisible: false },
  { key: 'real-count', label: '实时库存(小满)', defaultVisible: false },
  { key: 'production-in-transit', label: '生产在途' },
  { key: 'safety-stock', label: '安全库存' },
  { key: 'suggested-qty', label: '建议备货量' },
  { key: 'stock-status', label: '备货状态' },
  { key: 'status', label: '状态' },
  { key: 'source', label: '来源', defaultVisible: false },
]

const storageKey = 'stock-overview-table-view'
const legacyDefaultColumns = [
  'model', 'type', 'size', 'color', 'weight', 'sales-30d', 'sales-90d', 'avg-daily-sales',
  'enable-count', 'free-stock', 'real-count', 'effective-enable-count', 'production-in-transit',
  'stock-status', 'safety-stock', 'suggested-qty', 'status', 'source',
]
const defaultVisibleKeys = columnDefs.filter(column => column.defaultVisible !== false).map(column => column.key)
const preferenceKeys = new Set(['version', 'knownColumnKeys', 'density', 'visibleKeys'])

function readSavedPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
    return saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : null
  } catch { return null }
}

function isLegacyDefaultSnapshot(saved) {
  const keys = saved?.visibleKeys
  if (!Array.isArray(keys) || keys.length !== legacyDefaultColumns.length) return false
  const unique = new Set(keys)
  return unique.size === legacyDefaultColumns.length && legacyDefaultColumns.every(key => unique.has(key))
}

export function useStockOverviewTable() {
  const saved = readSavedPreferences()
  const view = useTableView('stock-overview', columnDefs)
  if (isLegacyDefaultSnapshot(saved)) view.visibleKeys.value = [...defaultVisibleKeys]
  if (saved && Object.keys(saved).some(key => !preferenceKeys.has(key))) {
    try {
      const persisted = JSON.parse(localStorage.getItem(storageKey) || 'null')
      if (persisted) localStorage.setItem(storageKey, JSON.stringify({ ...saved, ...persisted }))
    } catch { /* 本地偏好不可写时保留内存迁移结果 */ }
  }
  return { columnDefs, ...view }
}
