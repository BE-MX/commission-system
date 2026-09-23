import { onMounted, ref } from 'vue'
import { getShipmentCapabilities } from '@/api/shipment'

export const orderTypeLabel = type => ({ stock: '库存单', production: '生产单', presale: '预售单' })[type] || type

export function useInvoiceShipments() {
  const shipmentInvoice = ref(null)
  const shipmentCapabilities = ref({ enabled: false, reason: '正在核验预售出库能力' })
  onMounted(async () => {
    try { shipmentCapabilities.value = await getShipmentCapabilities() }
    catch { shipmentCapabilities.value = { enabled: false, reason: '预售出库能力核验失败，请刷新页面重试' } }
  })
  return { shipmentInvoice, shipmentCapabilities }
}
