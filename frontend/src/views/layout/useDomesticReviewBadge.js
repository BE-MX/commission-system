import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getCustomerRequestPendingCount } from '@/api/domestic'
import { DOMESTIC_REVIEW_CHANGED } from '@/utils/domesticReviewEvents'

export function useDomesticReviewBadge() {
  const auth = useAuthStore()
  // null means no count has been confirmed for the current identity yet.
  const count = ref(null)
  let version = 0
  let timer
  let resumeTimer
  let controller
  let refreshAfterPending = false
  let disposed = false
  const identity = () => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions])
  const allowed = () => auth.user && auth.hasAnyPermission(['domestic:review', 'domestic:admin', 'domestic:recharge'])

  async function refresh({ queueIfPending = false } = {}) {
    if (disposed || document.hidden || !allowed()) return
    if (controller) {
      if (queueIfPending) refreshAfterPending = true
      return
    }
    window.clearTimeout(resumeTimer)
    const requestVersion = ++version
    controller = new AbortController()
    try {
      const result = await getCustomerRequestPendingCount({ signal: controller.signal })
      if (disposed || requestVersion !== version) return
      const nextCount = result.data?.count
      if (!Number.isSafeInteger(nextCount) || nextCount < 0) throw new Error('Invalid pending review count')
      count.value = nextCount
    } catch (error) {
      if (!disposed && requestVersion === version && error?.code !== 'ERR_CANCELED') {
        console.warn('Pending review count unavailable', error?.response?.status || error?.message || 'network')
      }
    } finally {
      if (!disposed && requestVersion === version) {
        controller = null
        if (refreshAfterPending) {
          refreshAfterPending = false
          refresh()
        }
      }
    }
  }

  function resume() {
    window.clearTimeout(resumeTimer)
    if (!disposed && !document.hidden) resumeTimer = window.setTimeout(refresh, 100)
  }
  function reviewChanged() { refresh({ queueIfPending: true }) }
  watch(identity, () => {
    version++
    controller?.abort()
    controller = null
    refreshAfterPending = false
    window.clearTimeout(resumeTimer)
    count.value = null
    refresh()
  }, { immediate: true })
  onMounted(() => {
    timer = window.setInterval(refresh, 60000)
    window.addEventListener(DOMESTIC_REVIEW_CHANGED, reviewChanged)
    window.addEventListener('focus', resume)
    document.addEventListener('visibilitychange', resume)
  })
  onUnmounted(() => {
    disposed = true
    version++
    controller?.abort()
    window.clearInterval(timer)
    window.clearTimeout(resumeTimer)
    window.removeEventListener(DOMESTIC_REVIEW_CHANGED, reviewChanged)
    window.removeEventListener('focus', resume)
    document.removeEventListener('visibilitychange', resume)
  })
  return count
}
