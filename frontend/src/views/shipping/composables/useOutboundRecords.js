/**
 * OKKI 出库单列表 + 打印弹框逻辑（宪法 12/14：useListPage + 打印弹框模式）。
 */
import { reactive } from 'vue'
import { useRoute } from 'vue-router'
import { listOutboundRecords } from '@/api/shipping'
import { useListPage } from '@/composables/useListPage'

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

  // 打印弹框：内容渲染在 iframe 里的独立文档中，打印只出那份文档，
  // 弹框本身停在列表页上——关掉就回来，不用按浏览器后退
  const printDialog = reactive({ visible: false, recordId: null })

  function openPrint(row) {
    Object.assign(printDialog, { visible: true, recordId: row.outbound_record_id })
  }

  return {
    ...listApi,
    printDialog, openPrint,
  }
}
