/**
 * 销量备货一览的表格视图状态（列显隐/密度/全屏），Action Bar Spec 配套。
 * columnDefs 只供 TableTools 列显隐面板使用，模板列保持静态（推广期不做配置化渲染）。
 */
import { useTableView } from '@/composables/useTableView'

const columnDefs = [
  { key: 'model', label: '型号' },
  { key: 'type', label: '类型' },
  { key: 'size', label: '尺寸' },
  { key: 'color', label: '颜色' },
  { key: 'weight', label: '克重' },
  { key: 'sales-30d', label: '30天销量' },
  { key: 'sales-90d', label: '90天销量' },
  { key: 'avg-daily-sales', label: '日均销量' },
  { key: 'enable-count', label: '可用库存(小满)' },
  { key: 'real-count', label: '实时库存(小满)' },
  { key: 'effective-enable-count', label: '可用库存' },
  { key: 'production-in-transit', label: '生产在途' },
  { key: 'stock-status', label: '备货状态' },
  { key: 'safety-stock', label: '安全库存' },
  { key: 'suggested-qty', label: '建议备货量' },
  { key: 'status', label: '状态' },
  { key: 'source', label: '来源' },
]

export function useStockOverviewTable() {
  const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
    useTableView('stock-overview', columnDefs)
  return { columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen }
}
