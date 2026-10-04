<template>
  <div class="commission-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="selected-batch-bar commission-lift cm-enter">
      <span>当前批次</span>
      <strong>{{ selectedBatch?.batch_name || '暂无批次' }}</strong>
    </div>

    <CommissionMetricCards class="commission-lift cm-enter-1" :summary="selectedSummary" />

    <!-- 批次表格：筛选区 + 操作行 + 表格 + 分页同在卡片内（List Page Spec） -->
    <div ref="panelRef" class="table-card commission-panel commission-lift cm-enter-2">
      <FilterBar :loading="loading" :pending="listState.hasPendingSearch.value" @search="searchList" @reset="resetFilters">
        <el-radio-group v-model="filters.status">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="confirming">确认中</el-radio-button>
          <el-radio-button value="confirmed">已确认</el-radio-button>
        </el-radio-group>
        <el-select v-model="filters.role" placeholder="关联角色" clearable class="filter-w-sm">
          <el-option label="业务员" value="salesperson" />
          <el-option label="一级主管" value="supervisor" />
          <el-option label="二级主管" value="second_supervisor" />
        </el-select>
        <el-date-picker
          v-model="filters.month"
          type="month"
          value-format="YYYY-MM"
          placeholder="批次月份"
          class="filter-w-sm"
        />
        <el-input
          v-model="filters.keyword"
          placeholder="搜索批次名称"
          clearable
          class="filter-w-md"
        />


      </FilterBar>

      <!-- 操作行：TableTools 四图标（Action Bar Spec；本页主操作在行内，无新建类按钮） -->
      <div class="action-bar">
        <TableTools :loading="loading"
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listState.hasData.value && listState.errorMessage.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="fetchList" />
<el-table
        :data="tableData"
        v-loading="loading"
        border
        class="list-table cm-row-clickable"
        :class="densityClass"
        :max-height="isFullscreen ? undefined : 640"
        highlight-current-row
        :row-class-name="batchRowClassName"
        @row-click="selectBatch" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listState.errorMessage.value" :loading="loading" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('batch-name')" prop="batch_name" label="批次名称" min-width="160" max-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('period')" label="批次周期" min-width="180" max-width="280" show-overflow-tooltip>
          <template #default="{ row }">{{ row.period_start }} 至 {{ row.period_end }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="110" max-width="130">
          <template #default="{ row }">
            <StatusBadge :type="batchStatusType(row.status)" size="small" effect="plain">{{ batchStatusLabel(row.status) }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('my-confirmation')" label="我的确认" min-width="110" max-width="150">
          <template #default="{ row }">
            <StatusBadge v-if="row.is_confirmed_by_me" type="success" size="small" effect="plain">已确认</StatusBadge>
            <StatusBadge v-else-if="row.status === 'confirming'" type="warning" size="small" effect="plain">待确认</StatusBadge>
            <StatusBadge v-else type="info" size="small" effect="plain">-</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('related-roles')" label="关联角色" min-width="150" max-width="220">
          <template #default="{ row }">
            <el-space wrap>
              <StatusBadge v-for="role in row.related_roles" :key="role" size="small" effect="plain">
                {{ roleLabel(role) }}
              </StatusBadge>
            </el-space>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('total-payment')" label="回款总额" min-width="130" max-width="180" align="right">
          <template #default="{ row }">{{ usd(row.total_payment_amount) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('detail-count')" label="回款单数量" prop="detail_count" min-width="110" max-width="150" align="right" />
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

      <el-pagination
        class="pager"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        layout="total, sizes, prev, pager, next"
        :page-sizes="[20, 50, 100]"
        @current-change="listState.handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

    <CommissionConfirmDialogs v-if="currentBatchId" ref="dialogsRef" :batch-id="currentBatchId" @confirmed="fetchList" />
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'

import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  exportMyCommissionBatch,
  getMyCommissionBatches,
} from '@/api/commission'
import { downloadBlob } from '@/utils/download'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { batchStatusLabel, batchStatusType, roleLabel, usd } from './commissionFormat'
import CommissionConfirmDialogs from './components/CommissionConfirmDialogs.vue'
import CommissionMetricCards from './components/CommissionMetricCards.vue'

const router = useRouter()
const authStore = useAuthStore()
const selectedBatch = ref(null)
const currentBatchId = ref(null)
const dialogsRef = ref(null)


const listState = useListPage(async (params, { signal, isCurrent }) => {
  const previousId = selectedBatch.value?.id
  const response = await getMyCommissionBatches(params, { signal, suppressToast: true })
  if (isCurrent()) selectedBatch.value = response.data.items.find(item => item.id === previousId) || response.data.items[0] || null
  return response.data
}, { immediate: false, searchForm: { status: '', role: '', month: '', keyword: '' } })
const { loading, list: tableData, total, page, pageSize, searchForm: filters } = listState
const fetchList = () => listState.refreshUpdate()
const searchList = () => listState.handleSearch()
const resetFilters = () => listState.handleReset()
const handleSizeChange = size => listState.handleSizeChange(size)


const hasActiveFilters = computed(() => Object.values(listState.appliedSearchForm.value).some(Boolean))

// 列显隐元数据：TableTools 列设置面板的数据源（模板列保持静态，操作列不进配置）
const columnDefs = [
  { key: 'batch-name', label: '批次名称' },
  { key: 'period', label: '批次周期' },
  { key: 'status', label: '状态' },
  { key: 'my-confirmation', label: '我的确认' },
  { key: 'related-roles', label: '关联角色' },
  { key: 'total-payment', label: '回款总额' },
  { key: 'detail-count', label: '回款单数量' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('sales-commission', columnDefs)

const selectedSummary = computed(() => selectedBatch.value || {
  total_payment_amount: 0,
  total_salesperson_commission: 0,
  total_supervisor_commission: 0,
  total_second_supervisor_commission: 0,
  total_commission: 0,
})
const currentUserKey = computed(() => authStore.user?.id || authStore.user?.username || authStore.accessToken || '')

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
  listState.list.value = []; listState.total.value = 0; listState.hasLoaded.value = false; listState.error.value = null
  selectedBatch.value = null
  page.value = 1
  fetchList()
}, { immediate: true, flush: 'sync' })
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
</style>
