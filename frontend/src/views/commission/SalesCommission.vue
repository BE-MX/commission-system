<template>
  <div class="commission-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="commission-panel commission-filter-bar commission-lift cm-enter">
      <el-radio-group v-model="filters.status" @change="fetchList">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="confirming">确认中</el-radio-button>
        <el-radio-button value="confirmed">已确认</el-radio-button>
      </el-radio-group>

      <div class="commission-filter-bar__actions">
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

    <div class="selected-batch-bar commission-lift cm-enter-1">
      <span>当前批次</span>
      <strong>{{ selectedBatch?.batch_name || '暂无批次' }}</strong>
    </div>

    <CommissionMetricCards class="commission-lift cm-enter-2" :summary="selectedSummary" />

    <div class="table-card commission-panel commission-lift cm-enter-3">
      <el-table
        :data="tableData"
        v-loading="loading"
        border
        class="list-table cm-row-clickable"
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
            <el-tag :type="batchStatusType(row.status)" size="small" effect="plain">{{ batchStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="我的确认" min-width="100" max-width="150">
          <template #default="{ row }">
            <el-tag v-if="row.is_confirmed_by_me" type="success" size="small" effect="plain">已确认</el-tag>
            <el-tag v-else-if="row.status === 'confirming'" type="warning" size="small" effect="plain">待确认</el-tag>
            <el-tag v-else type="info" size="small" effect="plain">-</el-tag>
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
          <template #default="{ row }">{{ usd(row.total_payment_amount) }}</template>
        </el-table-column>
        <el-table-column label="回款单数量" prop="detail_count" min-width="110" max-width="150" align="right" />
        <el-table-column class-name="table-action-column" label="操作" min-width="300" max-width="420" fixed="right">
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
      class="commission-pagination commission-lift cm-enter-4"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next, sizes"
      :page-sizes="[20, 50, 100]"
      @current-change="fetchList"
      @size-change="fetchList"
    />

    <CommissionConfirmDialogs v-if="currentBatchId" ref="dialogsRef" :batch-id="currentBatchId" @confirmed="fetchList" />
  </div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  exportMyCommissionBatch,
  getMyCommissionBatches,
} from '@/api/commission'
import { downloadBlob } from '@/utils/download'
import { batchStatusLabel, batchStatusType, roleLabel, usd } from './commissionFormat'
import CommissionConfirmDialogs from './components/CommissionConfirmDialogs.vue'
import CommissionMetricCards from './components/CommissionMetricCards.vue'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const tableData = ref([])
const selectedBatch = ref(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const currentBatchId = ref(null)
const dialogsRef = ref(null)
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
  return row.id === selectedBatch.value?.id ? 'commission-selected-row' : ''
}

function goDetail(row) {
  router.push(`/commission/my/${row.id}/details`)
}

async function handleExport(row) {
  const res = await exportMyCommissionBatch(row.id)
  downloadBlob(res)
}

async function openFeedback(row) {
  if (!row?.id) return
  currentBatchId.value = row.id
  await nextTick()
  dialogsRef.value?.openFeedback()
}

async function openConfirm(row) {
  if (!row?.id) return
  currentBatchId.value = row.id
  await nextTick()
  dialogsRef.value?.openConfirm()
}

watch(currentUserKey, () => {
  page.value = 1
  fetchList()
}, { immediate: true })
</script>

<style scoped src="./commission.css"></style>

<style scoped>
.selected-batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}

.selected-batch-bar strong {
  color: var(--text-primary);
  font-size: 15px;
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

.list-table {
  width: 100%;
}
</style>
