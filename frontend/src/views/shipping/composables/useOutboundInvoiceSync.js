import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { previewOutboundInvoiceSync, syncOutboundInvoice } from '@/api/shipping'

export function useOutboundInvoiceSync(refresh) {
  const syncingId = ref(null)
  const syncVisible = ref(false)
  const syncPreview = ref(null)
  const syncRow = ref(null)

  async function previewSync(row) {
    if (syncingId.value !== null || row.record_source !== 'okki' || !row.outbound_invoice_id) return
    syncingId.value = row.outbound_record_id
    syncPreview.value = null
    syncRow.value = row
    try {
      const response = await previewOutboundInvoiceSync(row.outbound_record_id)
      syncPreview.value = response.data
      syncVisible.value = true
    } finally { syncingId.value = null }
  }

  async function applySync() {
    if (syncingId.value !== null || !syncRow.value || !syncPreview.value) return
    syncingId.value = syncRow.value.outbound_record_id
    try {
      const response = await syncOutboundInvoice(syncRow.value.outbound_record_id, syncPreview.value.version || null,
        !!syncPreview.value.recover, !!syncPreview.value.requires_recheck)
      if (response.data.requires_preview) {
        syncPreview.value = (await previewOutboundInvoiceSync(syncRow.value.outbound_record_id)).data
        return
      }
      if (response.data.status !== 'sync_done') {
        syncPreview.value = { ...syncPreview.value, ...response.data }
        return
      }
      syncVisible.value = false
      ElMessage.success(response.data.message)
      await refresh()
    } catch (error) {
      if (error?.response?.status === 409) {
        syncPreview.value = (await previewOutboundInvoiceSync(syncRow.value.outbound_record_id)).data
      } else {
        // A network timeout does not prove failure. Reopen preview to recover without a second POST.
        syncPreview.value = { ...syncPreview.value, recover: true,
          message: '请求未完成，请重新核对结果。系统会检查上次操作，不会重复发送。' }
      }
    } finally { syncingId.value = null }
  }

  return { syncingId, syncVisible, syncPreview, syncRow, previewSync, applySync }
}
