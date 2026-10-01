/**
 * 安全库存设置页的表格视图状态（列显隐/密度/全屏），Action Bar Spec 配套。
 * columnDefs 只供 TableTools 列显隐面板使用，模板列保持静态（推广期不做配置化渲染）。
 */
import { useTableView } from '@/composables/useTableView'

const columnDefs = [
  { key: 'model', label: '型号' },
  { key: 'type', label: '类型' },
  { key: 'size', label: '尺寸' },
  { key: 'color', label: '颜色' },
  { key: 'weight', label: '克重' },
  { key: 'sales-30d', label: '近30日销量' },
  { key: 'enable-count', label: '当前可用库存' },
  { key: 'production-in-transit', label: '生产在途' },
  { key: 'stock-status', label: '备货状态' },
  { key: 'safety-stock', label: '安全库存阈值' },
  { key: 'avg-daily-sales', label: '日均销量' },
  { key: 'suggested-qty', label: '建议备货量' },
]

export function useSafetyConfigTable() {
  const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
    useTableView('safety-config', columnDefs)
  return { columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen }
}
