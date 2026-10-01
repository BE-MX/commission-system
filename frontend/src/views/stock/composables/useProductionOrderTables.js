/**
 * 生产订单管理页两个维度（订单/明细）表格的视图状态（列显隐/密度/全屏），Action Bar Spec 配套。
 * columnDefs 只供 TableTools 列显隐面板使用，模板列保持静态（推广期不做配置化渲染）。
 */
import { useTableView } from '@/composables/useTableView'

const orderColumnDefs = [
  { key: 'order-no', label: '生产单号' },
  { key: 'batch-no', label: '生产批次号' },
  { key: 'created-by', label: '创建人' },
  { key: 'created-at', label: '创建时间' },
  { key: 'item-count', label: '明细数' },
  { key: 'total-order-qty', label: '总下单量' },
  { key: 'total-received-qty', label: '总入库量' },
  { key: 'in-transit-qty', label: '在途量' },
  { key: 'status', label: '状态' },
]

const itemColumnDefs = [
  { key: 'order-no', label: '生产单号' },
  { key: 'batch-no', label: '批次号' },
  { key: 'product-name', label: '产品名称' },
  { key: 'model', label: '型号' },
  { key: 'order-qty', label: '下单数量' },
  { key: 'received-qty', label: '已入库' },
  { key: 'in-transit', label: '在途' },
  { key: 'item-status', label: '明细状态' },
  { key: 'order-status', label: '订单状态' },
  { key: 'urgent', label: '加急' },
  { key: 'expected-delivery', label: '预计交期' },
]

export function useProductionOrderTables() {
  const order = useTableView('production-order-manage-order', orderColumnDefs)
  const item = useTableView('production-order-manage-item', itemColumnDefs)
  return {
    orderColumnDefs,
    itemColumnDefs,
    orderDensity: order.density,
    orderDensityClass: order.densityClass,
    orderVisibleKeys: order.visibleKeys,
    orderPanelRef: order.panelRef,
    orderIsFullscreen: order.isFullscreen,
    orderToggleFullscreen: order.toggleFullscreen,
    itemDensity: item.density,
    itemDensityClass: item.densityClass,
    itemVisibleKeys: item.visibleKeys,
    itemPanelRef: item.panelRef,
    itemIsFullscreen: item.isFullscreen,
    itemToggleFullscreen: item.toggleFullscreen,
  }
}
