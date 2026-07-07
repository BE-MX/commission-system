<template>
  <div class="sales-commission-detail">
    <div class="page-header">
      <div>
        <h2>{{ detail.batch?.batch_name || '我的提成明细' }}</h2>
        <p v-if="detail.batch">{{ detail.batch.period_start }} 至 {{ detail.batch.period_end }}</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="ghost" left-icon="ArrowLeft" @click="router.back()">返回</GlassButton>
        <GlassButton variant="secondary" left-icon="Download" @click="handleExport">导出</GlassButton>
        <template v-if="canSubmit">
          <GlassButton variant="secondary" left-icon="ChatDotRound" @click="openFeedback">问题反馈</GlassButton>
          <GlassButton variant="primary" left-icon="CircleCheck" @click="openConfirm">提交确认</GlassButton>
        </template>
      </div>
    </div>

    <div v-loading="loading" class="content-stack">
      <div class="summary-grid">
        <div class="metric-item payment">
          <div class="metric-icon"><el-icon><Money /></el-icon></div>
          <span>{{ metricTitle('回款总额') }}</span>
          <strong>{{ usd(activeSummary.total_payment_amount) }}</strong>
        </div>
        <div class="metric-item sales">
          <div class="metric-icon"><el-icon><User /></el-icon></div>
          <span>{{ metricTitle('业务员提成') }}</span>
          <strong>{{ usd(activeSummary.total_salesperson_commission) }}</strong>
        </div>
        <div class="metric-item supervisor">
          <div class="metric-icon"><el-icon><UserFilled /></el-icon></div>
          <span>{{ metricTitle('一级主管提成') }}</span>
          <strong>{{ usd(activeSummary.total_supervisor_commission) }}</strong>
        </div>
        <div class="metric-item second-supervisor">
          <div class="metric-icon"><el-icon><Connection /></el-icon></div>
          <span>{{ metricTitle('二级主管提成') }}</span>
          <strong>{{ usd(activeSummary.total_second_supervisor_commission) }}</strong>
        </div>
        <div class="metric-item total">
          <div class="metric-icon"><el-icon><TrendCharts /></el-icon></div>
          <span>{{ metricTitle('总提成') }}</span>
          <strong>{{ usd(activeSummary.total_commission) }}</strong>
        </div>
      </div>

      <div class="section-panel monthly-panel">
        <div class="section-header">
          <div class="section-title">月度汇总</div>
          <GlassButton v-if="selectedMonth" variant="ghost" left-icon="RefreshLeft" @click="selectedMonth = ''">
            查看全部
          </GlassButton>
        </div>
        <el-table
          :data="detail.monthly_summary"
          border
          class="list-table month-table"
          empty-text="暂无月度数据"
          highlight-current-row
          :row-class-name="monthRowClassName"
          @row-click="selectMonth"
        >
          <el-table-column prop="month" label="月份" min-width="100" max-width="140" show-overflow-tooltip />
          <el-table-column label="总提成（美元）" min-width="160" max-width="220" align="right">
            <template #default="{ row }">{{ usd(row.total_commission_usd) }}</template>
          </el-table-column>
          <el-table-column label="月平均汇率" min-width="140" max-width="190" align="right">
            <template #default="{ row }">{{ rate(row.average_exchange_rate) }}</template>
          </el-table-column>
          <el-table-column label="总提成（人民币）" min-width="170" max-width="240" align="right">
            <template #default="{ row }">{{ cny(row.total_commission_rmb) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="detail-window">
        <el-tabs v-model="activeTab" class="detail-tabs">
          <el-tab-pane :label="`业务提成 (${visibleDetailCount(detail.salesperson_details, 'salesperson')})`" name="salesperson">
            <detail-table :rows="detail.salesperson_details" role="salesperson" />
          </el-tab-pane>
          <el-tab-pane :label="`一级主管提成 (${visibleDetailCount(detail.supervisor_details, 'supervisor')})`" name="supervisor">
            <detail-table :rows="detail.supervisor_details" role="supervisor" />
          </el-tab-pane>
          <el-tab-pane :label="`二级主管提成 (${visibleDetailCount(detail.second_supervisor_details, 'second_supervisor')})`" name="second_supervisor">
            <detail-table :rows="detail.second_supervisor_details" role="second_supervisor" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>

    <el-dialog v-model="feedbackVisible" title="问题反馈" width="520px">
      <el-input
        v-model="feedbackContent"
        type="textarea"
        :rows="5"
        maxlength="2000"
        show-word-limit
        placeholder="描述本批次提成数据中的问题"
      />
      <template #footer>
        <GlassButton variant="ghost" @click="feedbackVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="submitting" @click="submitFeedback">提交</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="confirmVisible" title="提交确认" width="520px">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="一旦提交确认后将不能修改，如确认无误，则在下方输入框中输入‘我已确认’后点击提交。"
      />
      <el-input v-model="confirmText" class="confirm-input" placeholder="请输入：我已确认" />
      <template #footer>
        <GlassButton variant="ghost" @click="confirmVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="submitting" @click="submitConfirm">提交</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElTable, ElTableColumn } from 'element-plus'
import { Connection, Money, TrendCharts, User, UserFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  confirmMyCommissionBatch,
  exportMyCommissionBatch,
  getMyCommissionBatchDetail,
  submitMyCommissionFeedback,
} from '@/api/commission'
import { downloadBlob } from '@/utils/download'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const activeTab = ref('salesperson')
const selectedMonth = ref('')
const feedbackVisible = ref(false)
const feedbackContent = ref('')
const confirmVisible = ref(false)
const confirmText = ref('')
let detailRequestSeq = 0

function createEmptyDetail() {
  return {
    batch: null,
    summary: {},
    monthly_summary: [],
    salesperson_details: [],
    supervisor_details: [],
    second_supervisor_details: [],
  }
}

const detail = ref(createEmptyDetail())

const batchId = computed(() => route.params.batchId)
const currentUserKey = computed(() => authStore.user?.id || authStore.user?.username || authStore.accessToken || '')
const canSubmit = computed(() => detail.value.batch?.status === 'confirming' && !detail.value.batch?.is_confirmed_by_me)

const activeSummary = computed(() => {
  if (!selectedMonth.value) {
    return detail.value.summary || {}
  }
  return buildMonthSummary(selectedMonth.value)
})

function usd(value) {
  return `$${Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function cny(value) {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function rate(value) {
  return Number(value || 0).toFixed(6)
}

function monthOf(value) {
  return value ? String(value).slice(0, 7) : '未设置日期'
}

function metricTitle(label) {
  return selectedMonth.value ? `${label} · ${selectedMonth.value}` : label
}

function roleValue(row, role, suffix) {
  const key = {
    salesperson: `salesperson_${suffix}`,
    supervisor: `supervisor_${suffix}`,
    second_supervisor: `second_supervisor_${suffix}`,
  }[role]
  return row[key]
}

function visibleDetailCount(rows, role) {
  return rows.filter(row => Number(roleValue(row, role, 'commission') || 0) !== 0).length
}

function buildMonthSummary(month) {
  const rowsById = new Map()
  const summary = {
    total_payment_amount: 0,
    total_salesperson_commission: 0,
    total_supervisor_commission: 0,
    total_second_supervisor_commission: 0,
    total_commission: 0,
  }

  detail.value.salesperson_details.filter(row => monthOf(row.collection_date) === month).forEach(row => {
    rowsById.set(row.id, row)
    summary.total_salesperson_commission += Number(row.salesperson_commission || 0)
  })
  detail.value.supervisor_details.filter(row => monthOf(row.collection_date) === month).forEach(row => {
    rowsById.set(row.id, row)
    summary.total_supervisor_commission += Number(row.supervisor_commission || 0)
  })
  detail.value.second_supervisor_details.filter(row => monthOf(row.collection_date) === month).forEach(row => {
    rowsById.set(row.id, row)
    summary.total_second_supervisor_commission += Number(row.second_supervisor_commission || 0)
  })

  rowsById.forEach(row => {
    summary.total_payment_amount += Number(row.payment_amount || 0)
  })
  summary.total_commission = summary.total_salesperson_commission
    + summary.total_supervisor_commission
    + summary.total_second_supervisor_commission
  return summary
}

function selectMonth(row) {
  selectedMonth.value = row.month
}

function monthRowClassName({ row }) {
  return row.month === selectedMonth.value ? 'selected-month-row' : ''
}

function groupedRows(rows, role) {
  const groups = new Map()
  rows.filter(row => Number(roleValue(row, role, 'commission') || 0) !== 0).forEach(row => {
    const month = monthOf(row.collection_date)
    if (!groups.has(month)) {
      groups.set(month, {
        id: `month-${month}`,
        isMonthGroup: true,
        month,
        total_payment_amount: 0,
        total_service_fee: 0,
        total_commission: 0,
        children: [],
      })
    }
    const group = groups.get(month)
    group.children.push(row)
    group.total_payment_amount += Number(row.payment_amount || 0)
    group.total_service_fee += Number(row.service_fee || 0)
    group.total_commission += Number(roleValue(row, role, 'commission') || 0)
  })

  return Array.from(groups.values())
    .sort((a, b) => String(a.month).localeCompare(String(b.month)))
    .map(group => ({
      ...group,
      children: group.children.sort((a, b) => {
        const dateCompare = String(a.collection_date || '').localeCompare(String(b.collection_date || ''))
        return dateCompare || Number(a.id || 0) - Number(b.id || 0)
      }),
    }))
}

const DetailTable = defineComponent({
  props: {
    rows: { type: Array, required: true },
    role: { type: String, required: true },
  },
  setup(props) {
    const tableRows = computed(() => groupedRows(props.rows, props.role))
    const cellClassName = ({ row }) => (row.isMonthGroup ? 'month-group-cell' : '')
    const rowClassName = ({ row, rowIndex }) => {
      if (!row.isMonthGroup) return ''
      return rowIndex % 2 === 0 ? 'month-group-row month-group-row-a' : 'month-group-row month-group-row-b'
    }

    return () => h(ElTable, {
      data: tableRows.value,
      border: true,
      class: 'list-table detail-table',
      emptyText: '暂无明细',
      rowKey: 'id',
      defaultExpandAll: true,
      cellClassName,
      rowClassName,
      treeProps: { children: 'children' },
      maxHeight: 560,
    }, () => [
      h(ElTableColumn, { prop: 'collection_date', label: '回款日期', minWidth: 104, maxWidth: 140, showOverflowTooltip: true }, {
        default: ({ row }) => row.isMonthGroup ? `${row.month}（${row.children.length} 笔）` : row.collection_date,
      }),
      h(ElTableColumn, { prop: 'salesperson_name', label: '业务员', minWidth: 92, maxWidth: 130, showOverflowTooltip: true }, {
        default: ({ row }) => row.isMonthGroup ? '月度汇总' : (row.salesperson_name || row.salesperson_id || ''),
      }),
      h(ElTableColumn, { label: '订单名称', minWidth: 122, maxWidth: 240, showOverflowTooltip: true }, {
        default: ({ row }) => row.isMonthGroup ? '' : (row.order_name || row.order_no || row.order_id),
      }),
      h(ElTableColumn, { prop: 'customer_name', label: '客户', minWidth: 140, maxWidth: 240, showOverflowTooltip: true }),
      h(ElTableColumn, { prop: 'customer_country', label: '国家', minWidth: 76, maxWidth: 120, showOverflowTooltip: true }),
      h(ElTableColumn, { label: '回款金额（美元）', minWidth: 112, maxWidth: 160, align: 'right' }, {
        default: ({ row }) => row.isMonthGroup ? usd(row.total_payment_amount) : usd(row.payment_amount),
      }),
      h(ElTableColumn, { label: '服务费（美元）', minWidth: 104, maxWidth: 150, align: 'right' }, {
        default: ({ row }) => row.isMonthGroup ? usd(row.total_service_fee) : usd(row.service_fee),
      }),
      h(ElTableColumn, { label: '提成比例', minWidth: 82, maxWidth: 120, align: 'right' }, {
        default: ({ row }) => row.isMonthGroup ? '' : `${(Number(roleValue(row, props.role, 'rate') || 0) * 100).toFixed(2)}%`,
      }),
      h(ElTableColumn, { label: '提成金额（美元）', minWidth: 112, maxWidth: 160, align: 'right' }, {
        default: ({ row }) => row.isMonthGroup ? usd(row.total_commission) : usd(roleValue(row, props.role, 'commission')),
      }),
      h(ElTableColumn, { prop: 'type', label: '付款方式', minWidth: 92, maxWidth: 140, showOverflowTooltip: true }),
      h(ElTableColumn, { prop: 'order_source', label: '订单来源', minWidth: 96, maxWidth: 150, showOverflowTooltip: true }),
      h(ElTableColumn, { prop: 'calc_rule_note', label: '计算说明', minWidth: 150, maxWidth: 260, showOverflowTooltip: true }),
    ])
  },
})

async function fetchDetail() {
  const requestSeq = ++detailRequestSeq
  const requestBatchId = batchId.value
  const requestUserKey = currentUserKey.value
  detail.value = createEmptyDetail()
  selectedMonth.value = ''
  activeTab.value = 'salesperson'
  if (!requestBatchId) return
  loading.value = true
  try {
    const res = await getMyCommissionBatchDetail(requestBatchId)
    if (
      requestSeq !== detailRequestSeq
      || requestBatchId !== batchId.value
      || requestUserKey !== currentUserKey.value
    ) {
      return
    }
    detail.value = res.data
    if (detail.value.salesperson_details.length) activeTab.value = 'salesperson'
    else if (detail.value.supervisor_details.length) activeTab.value = 'supervisor'
    else activeTab.value = 'second_supervisor'
  } finally {
    if (requestSeq === detailRequestSeq) {
      loading.value = false
    }
  }
}

async function handleExport() {
  const res = await exportMyCommissionBatch(batchId.value)
  downloadBlob(res)
}

function openFeedback() {
  feedbackContent.value = ''
  feedbackVisible.value = true
}

async function submitFeedback() {
  if (!feedbackContent.value.trim()) {
    ElMessage.warning('请输入反馈内容')
    return
  }
  submitting.value = true
  try {
    await submitMyCommissionFeedback(batchId.value, { content: feedbackContent.value.trim() })
    ElMessage.success('反馈已提交')
    feedbackVisible.value = false
  } finally {
    submitting.value = false
  }
}

function openConfirm() {
  confirmText.value = ''
  confirmVisible.value = true
}

async function submitConfirm() {
  if (confirmText.value !== '我已确认') {
    ElMessage.warning('请输入“我已确认”后再提交')
    return
  }
  submitting.value = true
  try {
    await confirmMyCommissionBatch(batchId.value, { confirmation_text: confirmText.value })
    ElMessage.success('确认成功')
    confirmVisible.value = false
    await fetchDetail()
  } finally {
    submitting.value = false
  }
}

watch([batchId, currentUserKey], fetchDetail, { immediate: true })
</script>

<style scoped>
.sales-commission-detail {
  --commission-ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  animation: surface-in 220ms var(--commission-ease-out) both;
}

.page-header h2 {
  margin: 0;
  color: #111827;
  font-size: 22px;
  line-height: 1.3;
}

.page-header p {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 13px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.content-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(150px, 1fr));
  gap: 12px;
  animation: surface-in 240ms var(--commission-ease-out) 40ms both;
}

.metric-item {
  position: relative;
  min-height: 82px;
  padding: 14px 16px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #fff;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
}

.metric-icon {
  position: absolute;
  right: 14px;
  bottom: 8px;
  width: 64px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 60px;
  background: transparent;
  box-shadow: none;
  opacity: 0.14;
  pointer-events: none;
}

.metric-icon :deep(.el-icon) {
  width: 1em;
  height: 1em;
  font-size: 60px;
}

.metric-item.payment {
  background: linear-gradient(135deg, #eef6ff 0%, #ffffff 72%);
  border-color: #cfe4ff;
}

.metric-item.payment .metric-icon {
  color: #2563eb;
}

.metric-item.payment span {
  color: #3b82f6;
}

.metric-item.payment strong {
  color: #1d4ed8;
}

.metric-item.sales {
  background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 72%);
  border-color: #bbf7d0;
}

.metric-item.sales .metric-icon {
  color: #16a34a;
}

.metric-item.sales span {
  color: #22c55e;
}

.metric-item.sales strong {
  color: #15803d;
}

.metric-item.supervisor {
  background: linear-gradient(135deg, #fff7ed 0%, #ffffff 72%);
  border-color: #fed7aa;
}

.metric-item.supervisor .metric-icon {
  color: #ea580c;
}

.metric-item.supervisor span {
  color: #f97316;
}

.metric-item.supervisor strong {
  color: #c2410c;
}

.metric-item.second-supervisor {
  background: linear-gradient(135deg, #f5f3ff 0%, #ffffff 72%);
  border-color: #ddd6fe;
}

.metric-item.second-supervisor .metric-icon {
  color: #7c3aed;
}

.metric-item.second-supervisor span {
  color: #8b5cf6;
}

.metric-item.second-supervisor strong {
  color: #6d28d9;
}

.metric-item.total {
  background: linear-gradient(135deg, #ecfeff 0%, #ffffff 72%);
  border-color: #a5f3fc;
}

.metric-item.total .metric-icon {
  color: #0891b2;
}

.metric-item.total span {
  color: #06b6d4;
}

.metric-item.total strong {
  color: #0e7490;
}

.metric-item span {
  position: relative;
  z-index: 1;
  font-size: 13px;
}

.metric-item strong {
  position: relative;
  z-index: 1;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.section-panel,
.detail-window {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
}

.monthly-panel {
  padding: 14px;
  animation: surface-in 250ms var(--commission-ease-out) 80ms both;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-title {
  color: #111827;
  font-weight: 700;
}

.month-table {
  cursor: pointer;
}

:deep(.selected-month-row td) {
  background: #f0f9ff !important;
  box-shadow: inset 0 1px 0 #bae6fd, inset 0 -1px 0 #bae6fd;
}

:deep(.selected-month-row td:first-child) {
  box-shadow: inset 3px 0 0 #0ea5e9, inset 0 1px 0 #bae6fd, inset 0 -1px 0 #bae6fd;
}

.detail-window {
  max-height: 680px;
  padding: 0 14px 14px;
  animation: surface-in 260ms var(--commission-ease-out) 120ms both;
}

.detail-tabs {
  min-width: 0;
}

:deep(.detail-tabs > .el-tabs__header) {
  position: sticky;
  top: 0;
  z-index: 6;
  margin: 0;
  padding-top: 14px;
  background: #fff;
}

:deep(.detail-tabs .el-tabs__content) {
  padding-top: 12px;
}

.list-table,
.detail-table {
  width: 100%;
}

:deep(.detail-table .el-table__header th.el-table__cell) {
  padding: 8px 6px;
  white-space: normal !important;
}

:deep(.detail-table .el-table__header th.el-table__cell .cell) {
  white-space: normal !important;
  word-break: keep-all !important;
  line-height: 1.25;
  padding: 0 4px;
}

:deep(.detail-table .el-table__body td.el-table__cell) {
  padding: 8px 6px;
  white-space: nowrap !important;
  transition: background-color 160ms ease;
}

:deep(.month-table .el-table__body td.el-table__cell) {
  transition: background-color 160ms ease;
}

:deep(.detail-table .el-table__body td.el-table__cell .cell) {
  white-space: nowrap !important;
  word-break: keep-all !important;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 4px;
}

:deep(.detail-table .month-group-cell) {
  color: #1f2937;
  font-weight: 700;
}

:deep(.detail-table .month-group-row-a > td.month-group-cell) {
  background: #eef6ff !important;
}

:deep(.detail-table .month-group-row-b > td.month-group-cell) {
  background: #f0fdf4 !important;
}

:deep(.detail-table .month-group-row > td.month-group-cell .cell) {
  font-weight: 700;
}

:deep(.detail-table .month-group-row:hover > td.month-group-cell) {
  background: #fff7ed !important;
}

.confirm-input {
  margin-top: 18px;
}

@keyframes surface-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 1100px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .page-header,
  .summary-grid,
  .monthly-panel,
  .detail-window {
    animation: none;
  }

  :deep(.month-table .el-table__body td.el-table__cell),
  :deep(.detail-table .el-table__body td.el-table__cell) {
    transition-duration: 0.01ms;
  }
}
</style>
