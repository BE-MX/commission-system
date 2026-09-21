/**
 * OKKI 出库单列表 + 直接打印逻辑（宪法 12/14：useListPage；打印不走预览弹框）。
 */
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getOutboundPrintData, listOutboundRecords, deleteOutboundRecord, recoverOutboundDeletion } from '@/api/shipping'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import { useListPage } from '@/composables/useListPage'
import { buildOutboundDoc, printDocHtml } from '../print/printDocs'
import { downloadOutboundWord } from '@/api/shipping'
import { downloadBlob } from '@/utils/download'

export function useOutboundRecords() {
  const route = useRoute()

  const listApi = useListPage(
    async ({ page, page_size, ...form }) => {
      const params = { page, page_size }
      if (form.keyword) params.keyword = form.keyword
      if (form.dateRange?.length === 2) {
        params.date_from = form.dateRange[0]
        params.date_to = form.dateRange[1]
      }
      const res = await listOutboundRecords(params)
      return res.data || {}
    },
    {
      searchForm: {
        keyword: route.query.keyword || '',
        dateRange: [],
      },
    },
  )

  // 点击「打印出库单」直接调起浏览器打印：取数 → 构建文档 → 隐藏 iframe print()
  // printingId 给按钮上 loading，同时挡住重复点击
  const printingId = ref(null)
  const downloadingId = ref(null)
  const deletingId = ref(null)

  async function deleteRecord(row) {
    if (row.record_source !== 'okki' || !row.outbound_invoice_id || deletingId.value !== null) return
    deletingId.value = row.outbound_record_id
    try {
      try {
        await confirmDanger('删除出库单', row.outbound_no,
          '将同时删除小满中的整张待出库单。订单发票和已上传的验货资料保留。')
      } catch {
        return
      }
      await deleteOutboundRecord(row.outbound_record_id)
      msgSuccess('删除出库单并同步小满')
      if (listApi.list.value.length === 1 && listApi.page.value > 1) listApi.page.value--
      await listApi.fetchList()
    } finally {
      deletingId.value = null
    }
  }

  async function recoverDeletion(row) {
    if (deletingId.value !== null) return
    let reason
    try { reason = (await ElMessageBox.prompt('仅处理超时待核对的删除。确认保留小满原单并终止原请求，自动重建仍暂停。请填写至少10字核对依据。', '恢复删除任务', { inputValidator: v => v?.trim().length >= 10 || '请填写至少10字依据' })).value.trim() }
    catch { return }
    deletingId.value = row.outbound_record_id
    try {
      const result = await recoverOutboundDeletion(row.outbound_record_id, { reason, confirmed: true })
      ElMessage.success(result.data?.message || (result.data?.deleted ? '已核实小满出库单删除' : '已保存处理结果'))
      await listApi.fetchList()
    } finally { deletingId.value = null }
  }

  async function downloadWord(row) {
    if (!row.can_print) return
    if (downloadingId.value !== null) return
    downloadingId.value = row.outbound_record_id
    try {
      downloadBlob(await downloadOutboundWord(row.outbound_record_id))
    } finally {
      downloadingId.value = null
    }
  }

  async function openPrint(row) {
    if (!row.can_print) return
    if (printingId.value) return
    printingId.value = row.outbound_record_id
    try {
      const res = await getOutboundPrintData(row.outbound_record_id)
      const data = res.data || {}
      printDocHtml(buildOutboundDoc({
        record: data.record || {},
        items: data.items || [],
        qr_code_base64: data.qr_code_base64 || '',
      }))
    } catch {
      ElMessage.error('出库单打印数据加载失败，请稍后重试')
    } finally {
      printingId.value = null
    }
  }

  return {
    ...listApi,
    printingId, openPrint, downloadingId, downloadWord, deletingId, deleteRecord, recoverDeletion,
  }
}
