import { onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getInvoiceRelatedDetail } from '@/api/invoice'
import { createDetailSession } from './invoiceDetailState'

export function useInvoiceDetail() {
  const visible = ref(false), order = ref(null), activeTab = ref('order'), fullscreen = ref(false)
  const header = ref({ state: 'idle' }), receipts = ref({ state: 'idle' }), outbounds = ref({ state: 'idle' })
  const session = createDetailSession()
  const loading = ref(false)
  let identity, trigger
  const auth = useAuthStore()
  async function load(force = false) {
    if (!identity) return
    const ticket = session.begin(), id = identity
    loading.value = true
    header.value = { state: 'loading' }
    receipts.value = { ...receipts.value, state: 'loading', summary: null, freight: null, batch_balance: null }
    outbounds.value = { ...outbounds.value, state: 'loading', summary: null }
    await Promise.all([['', header], ['receipts', receipts], ['outbounds', outbounds]].map(async ([source, target]) => {
      try {
        const data = await getInvoiceRelatedDetail(id, source, { signal: ticket.signal, params: source === 'receipts' ? { refresh: force } : undefined })
        if (!session.current(ticket.version)) return
        if (!source) { order.value = data.order; header.value = { state: 'ready', checked_at: data.checked_at } }
        else target.value = data
      } catch (error) {
        if (!session.current(ticket.version)) return
        const status = error?.response?.status
        target.value = { state: [403, 404].includes(status) ? 'restricted' : 'unverified', message: [403, 404].includes(status) ? '单据不在当前查看范围内' : '加载失败，请刷新重试', items: [] }
        if (!source) order.value = null
      }
    }))
    if (session.current(ticket.version)) {
      loading.value = false
      window.dispatchEvent(new Event('ark-document-anomalies-changed'))
    }
  }
  function open(row) {
    trigger = document.activeElement
    identity = row.id; order.value = null; activeTab.value = 'order'; fullscreen.value = false; visible.value = true
    receipts.value = {state:'idle'}; outbounds.value = {state:'idle'}
    return load()
  }
  function close() { session.cancel(); loading.value = false; identity = null; order.value = null; receipts.value = {state:'idle'}; outbounds.value = {state:'idle'}; trigger?.isConnected && trigger.focus(); trigger = null }
  watch(() => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions]), () => { visible.value = false; close() })
  onUnmounted(() => session.cancel())
  return { visible, order, activeTab, fullscreen, header, receipts, outbounds, loading, open, close, refresh: () => load(true) }
}
