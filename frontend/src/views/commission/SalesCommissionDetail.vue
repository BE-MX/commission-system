<template>
  <div class="commission-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="commission-page-header commission-lift cm-enter">
      <div>
        <h2>{{ detail.batch?.batch_name || '我的提成明细' }}</h2>
        <p v-if="detail.batch">{{ detail.batch.period_start }} 至 {{ detail.batch.period_end }}</p>
      </div>
      <div class="commission-page-header__actions">
        <GlassButton variant="ghost" left-icon="ArrowLeft" @click="router.back()">返回</GlassButton>
        <GlassButton variant="secondary" left-icon="Download" @click="handleExport">导出</GlassButton>
        <template v-if="canSubmit">
          <GlassButton variant="secondary" left-icon="ChatDotRound" @click="dialogsRef?.openFeedback()">问题反馈</GlassButton>
          <GlassButton variant="primary" left-icon="CircleCheck" @click="dialogsRef?.openConfirm()">提交确认</GlassButton>
        </template>
      </div>
    </div>

    <div v-loading="loading" class="content-stack commission-lift cm-enter-1">
      <CommissionMetricCards :summary="activeSummary" :suffix="selectedMonth" />

      <div class="section-panel commission-panel monthly-panel">
        <div class="section-header">
          <div class="section-title">月度汇总</div>
          <GlassButton v-if="selectedMonth" variant="ghost" left-icon="RefreshLeft" @click="selectedMonth = ''">
            查看全部
          </GlassButton>
        </div>
        <el-table
          :data="detail.monthly_summary"
          border
          class="list-table month-table cm-row-clickable"
          empty-text="暂无月度数据"
          highlight-current-row
          :row-class-name="monthRowClassName"
          @row-click="selectMonth" v-sticky-scrollbar>
          <el-table-column prop="month" label="月份" min-width="100" max-width="140" show-overflow-tooltip />
          <el-table-column label="总提成（美元）" min-width="160" max-width="220" align="right">
            <template #default="{ row }">{{ usd(row.total_commission_usd) }}</template>
          </el-table-column>
          <el-table-column label="月平均汇率" min-width="140" max-width="190" align="right">
            <template #default="{ row }">{{ exchangeRate(row.average_exchange_rate) }}</template>
          </el-table-column>
          <el-table-column label="总提成（人民币）" min-width="170" max-width="240" align="right">
            <template #default="{ row }">{{ cny(row.total_commission_rmb) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="detail-window commission-panel">
        <el-tabs v-model="activeTab" class="detail-tabs cm-sticky-tabs">
          <el-tab-pane :label="`业务提成 (${visibleDetailCount(detail.salesperson_details, 'salesperson')})`" name="salesperson">
            <CommissionDetailTable :rows="detail.salesperson_details" role="salesperson" />
          </el-tab-pane>
          <el-tab-pane :label="`一级主管提成 (${visibleDetailCount(detail.supervisor_details, 'supervisor')})`" name="supervisor">
            <CommissionDetailTable :rows="detail.supervisor_details" role="supervisor" />
          </el-tab-pane>
          <el-tab-pane :label="`二级主管提成 (${visibleDetailCount(detail.second_supervisor_details, 'second_supervisor')})`" name="second_supervisor">
            <CommissionDetailTable :rows="detail.second_supervisor_details" role="second_supervisor" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>

    <CommissionConfirmDialogs v-if="batchId" ref="dialogsRef" :batch-id="batchId" @confirmed="fetchDetail" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  exportMyCommissionBatch,
  getMyCommissionBatchDetail,
} from '@/api/commission'
import { downloadBlob } from '@/utils/download'
import { cny, exchangeRate, usd } from './commissionFormat'
import { buildMonthSummary, visibleDetailCount } from './commissionGrouping'
import CommissionConfirmDialogs from './components/CommissionConfirmDialogs.vue'
import CommissionDetailTable from './components/CommissionDetailTable.vue'
import CommissionMetricCards from './components/CommissionMetricCards.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const activeTab = ref('salesperson')
const selectedMonth = ref('')
const dialogsRef = ref(null)
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
  return buildMonthSummary(detail.value, selectedMonth.value)
})

function selectMonth(row) {
  selectedMonth.value = row.month
}

function monthRowClassName({ row }) {
  return row.month === selectedMonth.value ? 'commission-selected-row' : ''
}

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

watch([batchId, currentUserKey], fetchDetail, { immediate: true })
</script>

<style scoped src="./commission.css"></style>

<style scoped>
.content-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.monthly-panel {
  padding: 14px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-title {
  color: var(--text-primary);
  font-weight: 700;
}

.detail-window {
  max-height: 680px;
  padding: 0 14px 14px;
}

.detail-tabs {
  min-width: 0;
}

.detail-tabs :deep(.el-tabs__content) {
  padding-top: 12px;
}

.list-table {
  width: 100%;
}
</style>