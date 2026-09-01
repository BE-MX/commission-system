/**
 * 验货单列表 + 详情抽屉 + 打印弹框逻辑（宪法 12/14：useListPage + DetailDrawer）。
 */
import { reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getInspectionRecord, listInspectionRecords } from '@/api/shipping'
import { useListPage } from '@/composables/useListPage'

export function useInspectionRecords() {
  const route = useRoute()

  const listApi = useListPage(
    async ({ page, page_size, ...form }) => {
      const params = { page, page_size }
      if (form.keyword) params.keyword = form.keyword
      if (form.dateRange?.length === 2) {
        params.date_from = form.dateRange[0]
        params.date_to = form.dateRange[1]
      }
      const res = await listInspectionRecords(params)
      return res.data || {}
    },
    {
      searchForm: {
        keyword: route.query.keyword || '',
        dateRange: [],
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

  function openPrint(row) {
    Object.assign(printDialog, { visible: true, recordId: row.id })
  }

  return {
    ...listApi,
    detailVisible, detailLoading, detail, openDetail,
    printDialog, openPrint,
  }
}
