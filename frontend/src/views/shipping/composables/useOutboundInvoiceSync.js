import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { previewOutboundInvoiceSync, syncOutboundInvoice } from '@/api/shipping'

export function useOutboundInvoiceSync(refresh) {
  const syncingId = ref(null)
  const syncVisible = ref(false)
  const syncPreview = ref(null)
  const syncRow = ref(null)

  async function finishSync(data) {
    if (data.requires_preview) {
      syncPreview.value = (await previewOutboundInvoiceSync(syncRow.value.outbound_record_id)).data
    } else if (data.status === 'sync_done') {
      syncVisible.value = false
      ElMessage.success(data.message)
      await refresh()
    } else {
      syncPreview.value = { ...syncPreview.value, ...data }
    }
  }

  async function resumeSync() {
    const id = syncRow.value.outbound_record_id
    // Every request sends at most one missing row and verifies it before the next.
    for (let attempt = 0; attempt < 72; attempt += 1) {
      const data = (await syncOutboundInvoice(id, null, false, false, true)).data
      if (data.status === 'sync_pending' || data.status === 'sync_sending') {
        syncPreview.value = { ...syncPreview.value, ...data }
        await new Promise(resolve => setTimeout(resolve, 5000))
        continue
      }
      if (data.status === 'sync_uncertain' && data.repairable) {
        syncPreview.value = { ...syncPreview.value, ...data }
        continue
      }
      await finishSync(data)
      return
    }
    syncPreview.value = { ...syncPreview.value, recover: true,
      message: '核对仍在进行中，请稍后再点击同步订单继续检查。' }
  }

  async function previewSync(row) {
    if (syncingId.value !== null || row.record_source !== 'okki' || !row.outbound_invoice_id) return
    syncingId.value = row.outbound_record_id
    syncPreview.value = null
    syncRow.value = row
    try {
      const response = await previewOutboundInvoiceSync(row.outbound_record_id)
      syncPreview.value = response.data
      syncVisible.value = true
      if (response.data.recover) await resumeSync()
    } catch (error) {
      if (!syncVisible.value) throw error
      if (error?.response?.status === 409) {
        syncPreview.value = (await previewOutboundInvoiceSync(row.outbound_record_id)).data
      } else {
        syncPreview.value = { ...syncPreview.value, recover: true,
          message: '核对暂未完成，请再次点击同步订单继续检查。' }
      }
    } finally { syncingId.value = null }
  }

  async function applySync() {
    if (syncingId.value !== null || !syncRow.value || !syncPreview.value) return
    syncingId.value = syncRow.value.outbound_record_id
    try {
      if (syncPreview.value.recover) {
        await resumeSync()
      } else {
        const data = (await syncOutboundInvoice(syncRow.value.outbound_record_id, syncPreview.value.version || null,
          false, !!syncPreview.value.requires_recheck)).data
        if (data.status === 'sync_uncertain' || data.status === 'sync_pending' || data.status === 'sync_sending') {
          syncPreview.value = { ...syncPreview.value, ...data, recover: true }
          await resumeSync()
        } else {
          await finishSync(data)
        }
      }
    } catch (error) {
      if (error?.response?.status === 409) {
        syncPreview.value = (await previewOutboundInvoiceSync(syncRow.value.outbound_record_id)).data
      } else {
        // A timeout does not prove failure; the next click starts with readback.
        syncPreview.value = { ...syncPreview.value, recover: true,
          message: '请求未完成，请再次点击同步订单继续核对和补齐。' }
      }
    } finally { syncingId.value = null }
  }

  return { syncingId, syncVisible, syncPreview, syncRow, previewSync, applySync }
}
