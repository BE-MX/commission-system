<template>
  <div class="sales-commission-page">
    <div class="filter-bar">
      <el-radio-group v-model="filters.status" @change="fetchList">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="confirming">确认中</el-radio-button>
        <el-radio-button value="confirmed">已确认</el-radio-button>
      </el-radio-group>

      <div class="filter-actions">
        <el-select v-model="filters.role" placeholder="关联角色" clearable class="role-select" @change="fetchList">
          <el-option label="业务员" value="salesperson" />
          <el-option label="一级主管" value="supervisor" />
          <el-option label="二级主管" value="second_supervisor" />
        </el-select>
        <el-date-picker
          v-model="filters.month"
          type="month"
          value-format="YYYY-MM"
          placeholder="批次月份"
          class="month-picker"
          @change="fetchList"
        />
        <el-input
          v-model="filters.keyword"
          placeholder="搜索批次名称"
          clearable
          class="keyword-input"
          @keyup.enter="fetchList"
          @clear="fetchList"
        />
        <GlassButton variant="primary" left-icon="Search" @click="fetchList">查询</GlassButton>
      </div>
    </div>

    <div class="selected-batch-bar">
      <span>当前批次</span>
      <strong>{{ selectedBatch?.batch_name || '暂无批次' }}</strong>
    </div>

    <div class="summary-grid">
      <div class="metric-item payment">
        <div class="metric-icon"><el-icon><Money /></el-icon></div>
        <span>回款总额</span>
        <strong>{{ money(selectedSummary.total_payment_amount) }}</strong>
      </div>
      <div class="metric-item sales">
        <div class="metric-icon"><el-icon><User /></el-icon></div>
        <span>业务员提成</span>
        <strong>{{ money(selectedSummary.total_salesperson_commission) }}</strong>
      </div>
      <div class="metric-item supervisor">
        <div class="metric-icon"><el-icon><UserFilled /></el-icon></div>
        <span>一级主管提成</span>
        <strong>{{ money(selectedSummary.total_supervisor_commission) }}</strong>
      </div>
      <div class="metric-item second-supervisor">
        <div class="metric-icon"><el-icon><Connection /></el-icon></div>
        <span>二级主管提成</span>
        <strong>{{ money(selectedSummary.total_second_supervisor_commission) }}</strong>
      </div>
      <div class="metric-item total">
        <div class="metric-icon"><el-icon><TrendCharts /></el-icon></div>
        <span>总提成</span>
        <strong>{{ money(selectedSummary.total_commission) }}</strong>
      </div>
    </div>

    <div class="table-card">
      <el-table
        :data="tableData"
        v-loading="loading"
        border
        class="list-table"
        highlight-current-row
        :row-class-name="batchRowClassName"
        @row-click="selectBatch"
      >
        <el-table-column prop="batch_name" label="批次名称" min-width="160" max-width="240" show-overflow-tooltip />
        <el-table-column label="批次周期" min-width="180" max-width="280" show-overflow-tooltip>
          <template #default="{ row }">{{ row.period_start }} 至 {{ row.period_end }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="90" max-width="130">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="我的确认" min-width="100" max-width="150">
          <template #default="{ row }">
            <el-tag v-if="row.is_confirmed_by_me" type="success" effect="plain">已确认</el-tag>
            <el-tag v-else-if="row.status === 'confirming'" type="warning" effect="plain">待确认</el-tag>
            <el-tag v-else type="info" effect="plain">-</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关联角色" min-width="150" max-width="220">
          <template #default="{ row }">
            <el-space wrap>
              <el-tag v-for="role in row.related_roles" :key="role" size="small" effect="plain">
                {{ roleLabel(role) }}
              </el-tag>
            </el-space>
          </template>
        </el-table-column>
        <el-table-column label="回款总额" min-width="130" max-width="180" align="right">
          <template #default="{ row }">{{ money(row.total_payment_amount) }}</template>
        </el-table-column>
        <el-table-column label="回款单数量" prop="detail_count" min-width="110" max-width="150" align="right" />
        <el-table-column label="操作" min-width="300" max-width="420" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="goDetail(row)">明细</GlassButton>
            <GlassButton variant="link" left-icon="Download" @click="handleExport(row)">导出</GlassButton>
            <template v-if="row.status === 'confirming' && !row.is_confirmed_by_me">
              <GlassButton variant="link" left-icon="ChatDotRound" @click="openFeedback(row)">问题反馈</GlassButton>
              <GlassButton variant="link" link-tone="success" left-icon="CircleCheck" @click="openConfirm(row)">提交确认</GlassButton>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-pagination
      class="pagination"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next, sizes"
      :page-sizes="[20, 50, 100]"
      @current-change="fetchList"
      @size-change="fetchList"
    />

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
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  confirmMyCommissionBatch,
  exportMyCommissionBatch,
  getMyCommissionBatches,
  submitMyCommissionFeedback,
} from '@/api/commission'
import { downloadBlob } from '@/utils/download'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const tableData = ref([])
const selectedBatch = ref(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const currentRow = ref(null)
const feedbackVisible = ref(false)
const feedbackContent = ref('')
const confirmVisible = ref(false)
const confirmText = ref('')
let listRequestSeq = 0

const filters = reactive({
  status: '',
  role: '',
  month: '',
  keyword: '',
})

const selectedSummary = computed(() => selectedBatch.value || {
  total_payment_amount: 0,
  total_salesperson_commission: 0,
  total_supervisor_commission: 0,
  total_second_supervisor_commission: 0,
  total_commission: 0,
})
const currentUserKey = computed(() => authStore.user?.id || authStore.user?.username || authStore.accessToken || '')

function money(value) {
  return `$${Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function statusType(status) {
  return { confirming: 'warning', confirmed: 'success' }[status] || 'info'
}

function statusLabel(status) {
  return { confirming: '确认中', confirmed: '已确认' }[status] || status
}

function roleLabel(role) {
  return {
    salesperson: '业务员',
    supervisor: '一级主管',
    second_supervisor: '二级主管',
  }[role] || role
}

async function fetchList() {
  const requestSeq = ++listRequestSeq
  const requestUserKey = currentUserKey.value
  const previousId = selectedBatch.value?.id
  tableData.value = []
  selectedBatch.value = null
  total.value = 0
  loading.value = true
  try {
    const res = await getMyCommissionBatches({
      status: filters.status,
      role: filters.role,
      month: filters.month,
      keyword: filters.keyword,
      page: page.value,
      page_size: pageSize.value,
    })
    if (requestSeq !== listRequestSeq || requestUserKey !== currentUserKey.value) {
      return
    }
    tableData.value = res.data.items
    total.value = res.data.total
    selectedBatch.value = tableData.value.find(item => item.id === previousId) || tableData.value[0] || null
  } finally {
    if (requestSeq === listRequestSeq) {
      loading.value = false
    }
  }
}

function selectBatch(row) {
  selectedBatch.value = row
}

function batchRowClassName({ row }) {
  return row.id === selectedBatch.value?.id ? 'selected-batch-row' : ''
}

function goDetail(row) {
  router.push(`/commission/my/${row.id}/details`)
}

async function handleExport(row) {
  const res = await exportMyCommissionBatch(row.id)
  downloadBlob(res)
}

function openFeedback(row) {
  currentRow.value = row
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
    await submitMyCommissionFeedback(currentRow.value.id, { content: feedbackContent.value.trim() })
    ElMessage.success('反馈已提交')
    feedbackVisible.value = false
  } finally {
    submitting.value = false
  }
}

function openConfirm(row) {
  currentRow.value = row
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
    await confirmMyCommissionBatch(currentRow.value.id, { confirmation_text: confirmText.value })
    ElMessage.success('确认成功')
    confirmVisible.value = false
    await fetchList()
  } finally {
    submitting.value = false
  }
}

watch(currentUserKey, () => {
  page.value = 1
  fetchList()
}, { immediate: true })
</script>

<style scoped>
.sales-commission-page {
  --commission-ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 14px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
  animation: surface-in 220ms var(--commission-ease-out) both;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.role-select {
  width: 140px;
}

.month-picker {
  width: 140px;
}

.keyword-input {
  width: 220px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(150px, 1fr));
  gap: 12px;
  animation: surface-in 240ms var(--commission-ease-out) 40ms both;
}

.selected-batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #606266;
  font-size: 13px;
  animation: surface-in 220ms var(--commission-ease-out) 20ms both;
}

.selected-batch-bar strong {
  color: #111827;
  font-size: 15px;
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

.table-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  overflow: hidden;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
  animation: surface-in 260ms var(--commission-ease-out) 80ms both;
}

.list-table {
  width: 100%;
}

:deep(.selected-batch-row td) {
  background: #f0f9ff !important;
  box-shadow: inset 0 1px 0 #bae6fd, inset 0 -1px 0 #bae6fd;
}

:deep(.selected-batch-row td:first-child) {
  box-shadow: inset 3px 0 0 #0ea5e9, inset 0 1px 0 #bae6fd, inset 0 -1px 0 #bae6fd;
}

:deep(.list-table .el-table__body td.el-table__cell) {
  transition: background-color 160ms ease;
}

:deep(.el-table__row) {
  cursor: pointer;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  animation: surface-in 220ms var(--commission-ease-out) 120ms both;
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

@media (max-width: 960px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-bar {
    align-items: stretch;
  }

  .filter-actions,
  .keyword-input,
  .role-select,
  .month-picker {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .filter-bar,
  .selected-batch-bar,
  .summary-grid,
  .table-card,
  .pagination {
    animation: none;
  }

  :deep(.list-table .el-table__body td.el-table__cell) {
    transition-duration: 0.01ms;
  }
}
</style>
