import { createApp, h, ref } from 'vue'
import ElementPlus, { ElTable, ElTableColumn, ElButton } from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/table-actions.css'
import StatusBadge from '../../../src/components/StatusBadge.vue'
import { CASE_STATUS } from '../../../src/views/aftersales/aftersalesRules.js'
import { SALARY_STATUS } from '../../../src/views/salary/salaryStatus.js'
import { JOB_STATUS } from '../../../src/views/mail_outreach/presentation.js'
import { TRACKING_STATUS } from '../../../src/views/tracking/trackingStatus.js'
import afterSalesSource from '../../../src/views/aftersales/AfterSalesList.vue?raw'
import salarySource from '../../../src/views/salary/SalaryPeriods.vue?raw'
import mailSource from '../../../src/views/mail_outreach/MailOutreachQueue.vue?raw'
import trackingSource from '../../../src/views/tracking/TrackingList.vue?raw'
import priceSource from '../../../src/views/invoice/InvoicePriceConfig.vue?raw'
import riskSource from '../../../src/views/order_intelligence/OrderIntelligence.vue?raw'
import credibilitySource from '../../../src/views/insight/IntelligenceLibrary.vue?raw'
import { COLOR_TYPE_TEXT } from '../../../src/views/invoice/invoicePricePresentation.js'
import { statusBadgeColumns, statusFunctionDictionary } from '../../helpers/statusBadgeColumns.mjs'

const labels = ['已同步', '取消处理中', '同步结果待核对', '未知状态（future_long_status_code）']
const rows = labels.map((label, id) => ({ id, label }))
const badge = row => h(StatusBadge, { size: 'small', type: 'success' }, () => row.label)
const closed = ref(false)
const slotLabel = ref('First')
const dictionaryCases = [
  ['售后', CASE_STATUS, afterSalesSource, 'status'],
  ['工资', SALARY_STATUS, salarySource, 'status'],
  ['邮件任务', JOB_STATUS, mailSource, 'status'],
  ['物流', TRACKING_STATUS, trackingSource, 'current-status'],
  ['产品色型', COLOR_TYPE_TEXT, priceSource, 'color-type'],
  ['订单风险', statusFunctionDictionary(riskSource, 'riskLabel'), riskSource, 'risk'],
  ['情报可信度', statusFunctionDictionary(credibilitySource, 'credibilityLabel'), credibilitySource, 'credibility'],
].map(([name, dictionary, source, key]) => ({
  name, dictionary, width: statusBadgeColumns(source).find(row => row.attributes['v-if']?.includes("'" + key + "'")).width,
}))
createApp({
  render: () => h('main', { style: 'padding:24px;max-width:960px;margin:auto' }, [
    h('h1', '状态标签窄列回归'),
    h('p', '窄列保持单行；发票状态列完整显示已登记状态。'),
    h(ElTable, { data: rows, border: true, class: 'list-table' }, () => [
      h(ElTableColumn, { label: '窄列', width: 84, className: 'narrow-status' }, { default: ({ row }) => badge(row) }),
      h(ElTableColumn, { label: '状态', width: 160, showOverflowTooltip: true, className: 'invoice-status' }, { default: ({ row }) => badge(row) }),
      h(ElTableColumn, { label: '同步', width: 110, className: 'invoice-sync' }, { default: () => badge({ label: '已同步' }) }),
      h(ElTableColumn, { label: '类型', width: 110, className: 'invoice-type' }, { default: () => badge({ label: '生产单' }) }),
      h(ElTableColumn, { prop: 'label', label: '完整标签', minWidth: 300 }),
    ]),
    h('div', { style: 'display:flex;width:84px;margin-top:24px', class: 'flex-status' }, [badge({ label: '取消处理中' })]),
    h('div', { style: 'width:70px;margin-top:16px', class: 'closable-status' }, [
      closed.value ? h('span', { class: 'close-result' }, '已关闭') :
        h(StatusBadge, { size: 'small', closable: true, onClose: () => { closed.value = true } }, () => '同步结果待核对'),
    ]),
    h('div', { class: 'slot-status', style: 'margin-top:16px' }, [
      h(StatusBadge, {}, () => h('strong', slotLabel.value)),
      h('button', { onClick: () => { slotLabel.value = 'Second' } }, '更新槽内容'),
    ]),
    h('div', { class: 'zero-status' }, [h(StatusBadge, { value: 0 })]),
    h('div', { class: 'explicit-title-status' }, [h(StatusBadge, { title: '指定说明' }, () => '原始文字')]),
    h('div', { class: 'empty-title-status' }, [h(StatusBadge, { title: '' }, () => '原始文字')]),
    h(ElTable, { data: [{}], border: true, class: 'list-table grouped-badges', style: 'margin-top:24px' }, () => [
      h(ElTableColumn, { label: '多标签', width: 120, className: 'multiple-status' }, { default: () => [badge({ label: '启用' }), badge({ label: '主推' })] }),
      h(ElTableColumn, { label: '操作', width: 200, className: 'table-action-column' }, { default: () => h('div', { class: 'table-actions' }, [
        h(ElButton, { link: true }, () => '查看'),
        h(ElButton, { link: true }, () => '编辑'),
      ]) }),
      h(ElTableColumn, { label: '其他文字', minWidth: 200 }, { default: () => '多标签完整展示，操作列保持原布局' }),
    ]),
    ...dictionaryCases.flatMap(({ name, dictionary, width }) => [
      h('h2', name + ' · 实际字典与最小列宽'),
      h(ElTable, { data: Object.entries(dictionary).map(([value, meta]) => ({ value, ...(typeof meta === 'string' ? { label: meta } : meta) })), border: true, class: 'list-table dictionary-status' }, () => [
        h(ElTableColumn, { label: '状态', width, className: 'registered-status' }, { default: ({ row }) => h(StatusBadge, { value: row.value, dictionary, size: 'small' }) }),
        h(ElTableColumn, { prop: 'label', label: '完整文字', minWidth: 300 }),
      ]),
    ]),
  ]),
}).use(ElementPlus).mount('#app')
