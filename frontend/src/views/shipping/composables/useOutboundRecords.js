/**
 * OKKI 出库单列表 + 直接打印逻辑（宪法 12/14：useListPage；打印不走预览弹框）。
 */
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getOutboundPrintData, listOutboundRecords } from '@/api/shipping'
import { useListPage } from '@/composables/useListPage'
import { buildOutboundDoc, printDocHtml } from '../print/printDocs'

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

  async function openPrint(row) {
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
    printingId, openPrint,
  }
}
