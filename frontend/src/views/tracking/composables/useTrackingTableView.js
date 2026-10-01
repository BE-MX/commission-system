/**
 * 物流跟踪列表的表格视图状态（列显隐 + 行密度 + 全屏，Action Bar Spec）。
 * 列配置数组只作 TableTools 列显隐面板的数据源；模板列保持静态 + v-if（推广期约定，不做配置化渲染）。
 */
import { useTableView } from '@/composables/useTableView'

const columnDefs = [
  { key: 'waybill-no', label: '运单号' },
  { key: 'carrier-name', label: '物流商' },
  { key: 'receiver-name', label: '收件人' },
  { key: 'receiver-country', label: '国家' },
  { key: 'current-status', label: '状态' },
  { key: 'current-status-text', label: '最新动态' },
  { key: 'current-location', label: '当前位置' },
  { key: 'estimated-delivery', label: '预计送达' },
  { key: 'last-event-time', label: '最新时间' },
  { key: 'dingtalk-user-name', label: '提交人' },
  { key: 'short-link', label: '短链接' },
  { key: 'tracking-active', label: '跟踪' },
]

export function useTrackingTableView() {
  const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
    useTableView('tracking-list', columnDefs)
  return { columnDefs, density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen }
}
