import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getDocumentAnomalies } from '@/api/invoice'
import { mergeAnomalyOverview } from '@/views/invoice/composables/invoiceDetailState'

export function useDocumentAnomalyBadge() {
  const auth = useAuthStore(), route = useRoute(), overview = ref({})
  let version = 0, timer, disposed = false, controller
  const permissions = ['invoice:read', 'invoice:write', 'invoice:sync', 'receipt:read', 'receipt:write', 'receipt:admin', 'shipping_inspection:read', 'shipping_inspection:write', 'shipping_inspection:admin']
  async function refresh() {
    if (document.hidden || disposed) return
    const current = ++version
    controller?.abort(); controller = new AbortController()
    if (!auth.user || !auth.hasAnyPermission(permissions)) { overview.value = {}; return }
    try {
      const data = await getDocumentAnomalies({ signal: controller.signal })
      if (current === version && !disposed) overview.value = mergeAnomalyOverview(overview.value, data.domains)
    } catch {
      if (current === version && !disposed) overview.value = mergeAnomalyOverview(overview.value, {})
    }
  }
  watch(() => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions]), () => { version++; controller?.abort(); overview.value = {}; refresh() }, { immediate: true })
  watch(() => route.path, refresh)
  onMounted(() => {
    timer = window.setInterval(refresh, 30000)
    window.addEventListener('focus', refresh)
    window.addEventListener('ark-document-anomalies-changed', refresh)
    document.addEventListener('visibilitychange', refresh)
  })
  onUnmounted(() => {
    disposed = true; version++; controller?.abort(); window.clearInterval(timer)
    window.removeEventListener('focus', refresh)
    window.removeEventListener('ark-document-anomalies-changed', refresh)
    document.removeEventListener('visibilitychange', refresh)
  })
  return overview
}
