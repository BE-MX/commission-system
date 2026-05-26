import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getProductionCart,
  addToProductionCart,
  updateProductionCartItem,
  deleteProductionCartItem,
  deleteProductionCartItems,
  createProductionOrder,
} from '@/api/stock'

export function useProductionCart() {
  const cartItems = ref([])
  const cartCount = ref(0)
  const cartLoading = ref(false)
  const selectedCartIds = ref([])
  const drawerVisible = ref(false)

  const isCartEmpty = computed(() => cartItems.value.length === 0)
  const selectedItems = computed(() =>
    cartItems.value.filter(item => selectedCartIds.value.includes(item.id))
  )

  async function loadCart() {
    cartLoading.value = true
    try {
      const res = await getProductionCart()
      // 响应拦截器返回 { code, message, data }，取内层 data
      const payload = res.data ?? res
      cartItems.value = payload.items || []
      cartCount.value = payload.count || 0
    } catch (e) {
      console.warn('加载购物车失败:', e)
      ElMessage.error('加载购物车失败: ' + (e?.response?.data?.message || e.message || '未知错误'))
    } finally {
      cartLoading.value = false
    }
  }

  async function addToCart(payload) {
    try {
      const res = await addToProductionCart(payload)
      ElMessage.success(res.message || '已添加到购物车')
      await loadCart()
      return true
    } catch (e) {
      ElMessage.error(e?.response?.data?.message || '添加失败')
      return false
    }
  }

  async function updateCartItem(cartId, { order_qty, remark }) {
    try {
      await updateProductionCartItem(cartId, { order_qty, remark })
      ElMessage.success('已更新')
      await loadCart()
      return true
    } catch (e) {
      ElMessage.error(e?.response?.data?.message || '更新失败')
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
      ElMessage.error(e?.response?.data?.message || '删除失败')
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
      ElMessage.error(e?.response?.data?.message || '删除失败')
      return false
    }
  }

  async function generateOrder({ batch_no, remark, is_urgent, expected_delivery_date }) {
    if (selectedCartIds.value.length === 0) {
      ElMessage.warning('请先选择产品')
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
      ElMessage.success(res.message || '生产订单创建成功')
      selectedCartIds.value = []
      await loadCart()
      return true
    } catch (e) {
      ElMessage.error(e?.response?.data?.message || '创建失败')
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
