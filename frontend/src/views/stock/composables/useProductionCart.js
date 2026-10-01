import { msgError, msgSuccessText, msgWarning } from '@/utils/feedback'
import { ref, computed, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'

import {
  getProductionCart,
  addToProductionCart,
  updateProductionCartItem,
  deleteProductionCartItem,
  deleteProductionCartItems,
  createProductionOrder,
} from '@/api/stock'

export function useProductionCart() {
  const cartResource = useAsyncResource(async (_, { signal }) => {
    const response = await getProductionCart({ signal, suppressToast: true })
    return response.data ?? response
  })
  const cartItems = computed(() => cartResource.data.value?.items || [])
  const cartCount = computed(() => cartResource.data.value?.count || 0)
  const cartLoading = cartResource.loading
  const cartErrorMessage = cartResource.errorMessage
  const selectedCartIds = ref([])
  const drawerVisible = ref(false)

  const isCartEmpty = computed(() => cartItems.value.length === 0)
  const selectedItems = computed(() =>
    cartItems.value.filter(item => selectedCartIds.value.includes(item.id))
  )

  const loadCart = () => cartResource.load()
  watch(cartResource.data, payload => {
    if (payload) selectedCartIds.value = selectedCartIds.value.filter(id => (payload.items || []).some(item => item.id === id))
  })

  async function addToCart(payload) {
    try {
      const res = await addToProductionCart(payload)
      msgSuccessText(res.message || '已添加到购物车')
      await loadCart()
      return true
    } catch (e) {
      msgError(e?.response?.data?.message || '添加失败', e)
      return false
    }
  }

  async function updateCartItem(cartId, { order_qty, remark }) {
    try {
      await updateProductionCartItem(cartId, { order_qty, remark })
      msgSuccessText('已更新')
      await loadCart()
      return true
    } catch (e) {
      msgError(e?.response?.data?.message || '更新失败', e)
      return false
    }
  }

  async function removeCartItem(cartId) {
    try {
      await deleteProductionCartItem(cartId)
      selectedCartIds.value = selectedCartIds.value.filter(id => id !== cartId)
      await loadCart()
      return true
    } catch (e) {
      msgError(e?.response?.data?.message || '删除失败', e)
      return false
    }
  }

  async function batchRemoveCartItems(ids) {
    try {
      await deleteProductionCartItems(ids)
      selectedCartIds.value = selectedCartIds.value.filter(id => !ids.includes(id))
      await loadCart()
      return true
    } catch (e) {
      msgError(e?.response?.data?.message || '删除失败', e)
      return false
    }
  }

  async function generateOrder({ batch_no, remark, is_urgent, expected_delivery_date }) {
    if (selectedCartIds.value.length === 0) {
      msgWarning('请先选择产品')
      return false
    }
    try {
      const res = await createProductionOrder({
        cart_ids: selectedCartIds.value,
        batch_no,
        remark,
        is_urgent,
        expected_delivery_date,
      })
      msgSuccessText(res.message || '生产订单创建成功')
      selectedCartIds.value = []
      await loadCart()
      return true
    } catch (e) {
      msgError(e?.response?.data?.message || '创建失败', e)
      return false
    }
  }

  function toggleSelection(selection) {
    selectedCartIds.value = selection.map(item => item.id)
  }

  return {
    cartItems,
    cartCount,
    cartLoading,
    cartErrorMessage,
    selectedCartIds,
    drawerVisible,
    isCartEmpty,
    selectedItems,
    loadCart,
    addToCart,
    updateCartItem,
    removeCartItem,
    batchRemoveCartItems,
    generateOrder,
    toggleSelection,
  }
}
