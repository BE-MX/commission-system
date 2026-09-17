/**
 * 验货单列表 + 详情抽屉 + 打印弹框逻辑（宪法 12/14：useListPage + DetailDrawer）。
 */
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadBlob } from '@/utils/download'
import { getInspectionRecord, listInspectionRecords, recallInspectionRecord, downloadInspectionPdf } from '@/api/shipping'
import { useListPage } from '@/composables/useListPage'
import { confirmDanger, msgSuccess } from '@/utils/feedback'

export function useInspectionRecords() {
  const route = useRoute()
  const router = useRouter()
  const downloading = ref(false), pdfError = ref('')
  const noticePdf = computed(() => {
    const id = String(route.query.pdf || ''), version = String(route.query.version ?? '')
    return /^[1-9]\d*$/.test(id) && /^\d+$/.test(version) ? { id, version } : null
  })
  async function downloadPdf(row) {
    if (downloading.value) return
    downloading.value = true
    pdfError.value = ''
    try { downloadBlob(await downloadInspectionPdf(row.id, row.edit_version ?? row.version)) }
    catch (error) {
      if (error.response?.status === 401) {
        await router.push({ name: 'Login', query: { redirect: route.fullPath } })
        return
      }
      let detail = error.response?.data
      if (detail instanceof Blob) {
        try { detail = JSON.parse(await detail.text()) } catch { detail = null }
      }
      pdfError.value = detail?.detail || 'PDF 下载失败，请稍后重试'
    } finally { downloading.value = false }
  }


  const listApi = useListPage(
    async ({ page, page_size, ...form }) => {
      const params = { page, page_size }
      if (form.keyword) params.keyword = form.keyword
      if (form.submittedByName?.trim()) params.submitted_by_name = form.submittedByName.trim()
      if (form.salespersonName?.trim()) params.salesperson_name = form.salespersonName.trim()
      if (form.dateFrom) params.date_from = form.dateFrom
      if (form.dateTo) params.date_to = form.dateTo
      const res = await listInspectionRecords(params)
      return res.data || {}
    },
    {
      searchForm: {
        keyword: route.query.keyword || '',
        submittedByName: '', salespersonName: '', dateFrom: '', dateTo: '',
      },
    },
  )

  // ── 详情抽屉 ──
  const detailVisible = ref(false)
  const detailLoading = ref(false)
  const detail = ref(null)

  async function openDetail(row) {
    detailVisible.value = true
    detail.value = null
    detailLoading.value = true
    try {
      const res = await getInspectionRecord(row.id)
      detail.value = res.data
    } finally {
      detailLoading.value = false
    }
  }

  // 打印弹框：内容渲染在 iframe 里的独立文档中，打印只出那份文档
  const printDialog = reactive({ visible: false, recordId: null })
  const recallingId = ref(null)

  async function recallForEdit(row) {
    if (recallingId.value !== null) return
    recallingId.value = row.id
    try {
      try {
        await confirmDanger('撤回编辑', row.outbound_no, '已上传照片和视频会保留，小程序重新扫码后可继续上传和提交。')
      } catch { return }
      await recallInspectionRecord(row.id, row.edit_version)
      detailVisible.value = false
      printDialog.visible = false
      msgSuccess('撤回')
      await listApi.handleSearch()
    } finally {
      recallingId.value = null
    }
  }

  function openPrint(row) {
    Object.assign(printDialog, { visible: true, recordId: row.id })
  }

  return {
    ...listApi, noticePdf, downloading, pdfError, downloadPdf,
    detailVisible, detailLoading, detail, openDetail,
    printDialog, openPrint, recallingId, recallForEdit,
  }
}
