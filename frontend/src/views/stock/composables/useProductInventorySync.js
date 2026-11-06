import { reactive } from 'vue'
import { syncProductInventory } from '@/api/stock'
import { errorMessage } from '@/utils/errors'
import { msgError, msgSuccessText, msgWarning } from '@/utils/feedback'

export function useProductInventorySync(listState) {
  const syncingProducts = reactive(new Set())

  async function syncInventory(row) {
    const productId = row.product_id
    if (syncingProducts.has(productId)) return
    syncingProducts.add(productId)
    try {
      await syncProductInventory(productId)
      const refreshed = await listState.fetchList({ adjustPage: true })
      if (refreshed) msgSuccessText('库存同步成功')
      else msgWarning('库存已同步，列表刷新未完成，请刷新列表查看')
    } catch (error) {
      msgError(errorMessage(error, '库存同步失败，请稍后重试'), error)
    } finally {
      syncingProducts.delete(productId)
    }
  }

  return { syncingProducts, syncInventory }
}
