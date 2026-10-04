<template>
  <div class="commission-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 页头：批次名 + 状态，返回列表 -->
    <div class="commission-page-header commission-lift cm-enter">
      <div>
        <div class="commission-page-header__title">
          <h2>{{ summary?.batch_name || '提成明细' }}</h2>
          <StatusBadge v-if="summary" :type="batchStatusType(summary.status)" size="small" effect="plain">
            {{ batchStatusLabel(summary.status) }}
          </StatusBadge>
        </div>
        <p v-if="summary">确认进度 {{ summary.confirmed_count || 0 }}/{{ summary.expected_confirm_count || 0 }} · 反馈 {{ summary.feedback_count || 0 }} 条</p>
      </div>
      <div class="commission-page-header__actions">
        <GlassButton variant="ghost" left-icon="ArrowLeft" @click="router.push('/commission/batch')">返回列表</GlassButton>
      </div>
    </div>

    <!-- 批次摘要指标卡 -->
    <ListPageStatus :error="summaryState.errorMessage.value" :loading="summaryLoading" :has-data="Boolean(summary)" @retry="fetchSummary" />
    <CommissionMetricCards v-if="summary" v-loading="summaryLoading" class="commission-lift cm-enter-1" :summary="summary || {}" />

    <!-- 明细表格：筛选区 + 操作行 + 表格 + 分页同在卡片内（List Page Spec） -->
    <div ref="panelRef" class="table-card commission-panel commission-lift cm-enter-2">
      <FilterBar :loading="loading" :pending="listState.hasPendingSearch.value" @search="handleSearch" @reset="resetFilters">
        <el-input
          v-model="keyword"
          placeholder="搜索客户/业务员/主管"
          clearable
          class="filter-w-lg"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>


      </FilterBar>

      <!-- 操作行：TableTools 四图标（Action Bar Spec；本页无新建类主操作） -->
      <div class="action-bar">
        <TableTools :loading="loading"
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchDetails"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listState.hasData.value && listState.errorMessage.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="fetchDetails" />
<el-table :data="tableData" v-loading="loading" class="list-table" :class="densityClass" border :max-height="isFullscreen ? undefined : 640" @sort-change="changeSort" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listState.errorMessage.value" :loading="loading" :has-data="false" @retry="fetchDetails">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('payment-id')" prop="payment_id" label="回款ID" min-width="160" max-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('order-id')" prop="order_id" label="订单ID" min-width="160" max-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('payment-amount')" prop="payment_amount" label="回款金额（美元）" min-width="130" max-width="190" align="right" sortable="custom">
          <template #default="{ row }">{{ usdOrDash(row.payment_amount) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('salesperson-name')" prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('salesperson-rate')" label="业务员比例" min-width="100" max-width="150" align="right">
          <template #default="{ row }">{{ commissionRate(row.salesperson_rate) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('salesperson-commission')" prop="salesperson_commission" label="业务员提成" min-width="110" max-width="160" align="right" sortable="custom">
          <template #default="{ row }">{{ usdOrDash(row.salesperson_commission) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('supervisor-name')" prop="supervisor_name" label="一级主管" min-width="90" max-width="140" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('supervisor-rate')" label="一级主管比例" min-width="110" max-width="160" align="right">
          <template #default="{ row }">{{ commissionRate(row.supervisor_rate) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('supervisor-commission')" label="一级主管提成" min-width="120" max-width="180" align="right">
          <template #default="{ row }">{{ usdOrDash(row.supervisor_commission) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('second-supervisor-name')" prop="second_supervisor_name" label="二级主管" min-width="90" max-width="140" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('second-supervisor-rate')" label="二级主管比例" min-width="110" max-width="160" align="right">
          <template #default="{ row }">{{ commissionRate(row.second_supervisor_rate) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('second-supervisor-commission')" label="二级主管提成" min-width="120" max-width="180" align="right">
          <template #default="{ row }">{{ usdOrDash(row.second_supervisor_commission) }}</template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('calc-rule-note')" prop="calc_rule_note" label="计算规则" min-width="130" max-width="200" show-overflow-tooltip />
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
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'
import { toRef, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'

import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { getBatchDetails, getBatchSummary } from '@/api/commission'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { batchStatusLabel, batchStatusType, commissionRate, usdOrDash } from './commissionFormat'
import CommissionMetricCards from './components/CommissionMetricCards.vue'

const orderSort = useTableSort()

const route = useRoute()
const router = useRouter()
const batchId = computed(() => route.params.batchId)

const summaryState = useAsyncResource(async (id, { signal }) => (await getBatchSummary(id, { signal, suppressToast: true })).data)
const { data: summary, loading: summaryLoading } = summaryState
const listState = useListPage(async (params, context) => {
  return (await getBatchDetails(batchId.value, params, { signal: context.signal, suppressToast: true })).data
}, { immediate: false, searchForm: { keyword: '' } })
const { page: page, pageSize: pageSize, total: total, list: tableData, loading: loading } = listState
const fetchDetails = () => listState.refreshUpdate()
const handleSearch = () => listState.handleSearch()
const resetFilters = () => listState.handleReset()
const handleSizeChange = size => listState.handleSizeChange(size)
function changeSort(event) { orderSort.onSortChange(event); return listState.handleSortChange(orderSort.sortParams.value) }



const keyword = toRef(listState.searchForm, 'keyword')

const hasActiveFilters = computed(() => Boolean(listState.appliedSearchForm.value.keyword))

// 列显隐元数据：TableTools 列设置面板的数据源（模板列保持静态，Action Bar Spec）
const columnDefs = [
  { key: 'payment-id', label: '回款ID' },
  { key: 'order-id', label: '订单ID' },
  { key: 'customer-name', label: '客户名称' },
  { key: 'payment-amount', label: '回款金额（美元）' },
  { key: 'salesperson-name', label: '业务员' },
  { key: 'salesperson-rate', label: '业务员比例' },
  { key: 'salesperson-commission', label: '业务员提成' },
  { key: 'supervisor-name', label: '一级主管' },
  { key: 'supervisor-rate', label: '一级主管比例' },
  { key: 'supervisor-commission', label: '一级主管提成' },
  { key: 'second-supervisor-name', label: '二级主管' },
  { key: 'second-supervisor-rate', label: '二级主管比例' },
  { key: 'second-supervisor-commission', label: '二级主管提成' },
  { key: 'calc-rule-note', label: '计算规则' },
]
// 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('commission-detail', columnDefs)

const fetchSummary = () => summaryState.load(batchId.value)

watch(batchId, () => {
  listState.list.value = []; listState.total.value = 0; listState.hasLoaded.value = false; listState.error.value = null; page.value = 1
  summaryState.load(batchId.value, { clear: true })
  fetchDetails()
}, { immediate: true, flush: 'sync' })
</script>

<style scoped src="./commission.css"></style>
