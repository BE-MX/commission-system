import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getCustomerRequestPendingCount } from '@/api/domestic'
import { DOMESTIC_REVIEW_CHANGED } from '@/utils/domesticReviewEvents'

export function useDomesticReviewBadge() {
  const auth = useAuthStore()
  const count = ref(0)
  let version = 0
  let timer
  let disposed = false
  const identity = () => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions])
  const allowed = () => auth.user && auth.hasAnyPermission(['domestic:review', 'domestic:admin', 'domestic:recharge'])

  async function refresh() {
    const requestVersion = ++version
    if (!allowed()) { count.value = 0; return }
    if (document.hidden) return
    try {
      const result = await getCustomerRequestPendingCount()
      if (!disposed && requestVersion === version) count.value = Number(result.data?.count) || 0
    } catch (error) {
      if (!disposed && requestVersion === version) count.value = 0
      console.warn('Pending review count unavailable', error?.response?.status || 'network')
    }
  }

  watch(identity, () => { count.value = 0; refresh() }, { immediate: true })
  onMounted(() => {
    timer = window.setInterval(refresh, 30000)
    window.addEventListener(DOMESTIC_REVIEW_CHANGED, refresh)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
  })
  onUnmounted(() => {
    disposed = true
    version++
    window.clearInterval(timer)
    window.removeEventListener(DOMESTIC_REVIEW_CHANGED, refresh)
    window.removeEventListener('focus', refresh)
    document.removeEventListener('visibilitychange', refresh)
  })
  return count
}
