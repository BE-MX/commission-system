// Local synthetic QA fixture; no production API calls or account state changes.
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import '@/styles/tokens.css'
import '@/styles/app.css'
import '@/views/battle-report/battle-report.css'
import Fixture from './Fixture.vue'
import { battleReportApi } from '@/api/battleReport'
import { registerStickyScrollbarDirective } from '@/directives/stickyScrollbar'
import { registerSortableTables } from '@/components/SortableTableColumn'

const rows = Array.from({ length: 62 }, (_, index) => ({
  order_id: String(index + 1), order_no: `QA-2026-${index + 1}`, order_name: `模拟发制品订单 ${index + 1}`,
  company_name: index % 2 ? '模拟客户 Alice' : '模拟客户 Bella', company_id: index % 2 ? 'A' : 'B',
  account_date: `2026-10-${String(19 - index % 18).padStart(2, '0')}`, amount_usd: String((index + 1) * 10),
  member_id: 1, user_name: '模拟业务员', role: index % 3 ? 'repeat' : 'new_sign',
}))
battleReportApi.metricOrders = async (id, params) => {
  if (params.customer === '模拟失败') throw new Error('模拟读取失败，请重试')
  let filtered = rows.filter(row => (params.metric === 'combined' || row.role === params.metric)
    && (!params.customer || row.company_name.includes(params.customer))
    && (!params.order_name || row.order_name.includes(params.order_name))
    && (!params.start_date || row.account_date >= params.start_date)
    && (!params.end_date || row.account_date <= params.end_date))
  filtered.sort((a, b) => b.account_date.localeCompare(a.account_date) || Number(b.order_id) - Number(a.order_id))
  if (params.sort_field && params.sort_order) filtered.sort((a, b) => {
    const key = params.sort_field
    return (key === 'amount_usd' ? Number(a[key]) - Number(b[key]) : String(a[key]).localeCompare(String(b[key]))) * (params.sort_order === 'desc' ? -1 : 1)
  })
  return { items: filtered.slice((params.page - 1) * params.page_size, params.page * params.page_size),
    total: filtered.length, customer_count: new Set(filtered.map(row => row.company_id)).size,
    total_amount: String(filtered.reduce((sum, row) => sum + Number(row.amount_usd), 0)), data_complete: true }
}
const app = createApp(Fixture)
app.use(ElementPlus, { locale: zhCn })
registerStickyScrollbarDirective(app)
registerSortableTables(app)
app.mount('#app')
