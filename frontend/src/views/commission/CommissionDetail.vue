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
          <el-tag v-if="summary" :type="batchStatusType(summary.status)" size="small" effect="plain">
            {{ batchStatusLabel(summary.status) }}
          </el-tag>
        </div>
        <p v-if="summary">确认进度 {{ summary.confirmed_count || 0 }}/{{ summary.expected_confirm_count || 0 }} · 反馈 {{ summary.feedback_count || 0 }} 条</p>
      </div>
      <div class="commission-page-header__actions">
        <GlassButton variant="ghost" left-icon="ArrowLeft" @click="router.push('/commission/batch')">返回列表</GlassButton>
      </div>
    </div>

    <!-- 批次摘要指标卡 -->
    <CommissionMetricCards v-loading="summaryLoading" class="commission-lift cm-enter-1" :summary="summary || {}" />

    <!-- 筛选栏 -->
    <div class="commission-panel commission-filter-bar commission-lift cm-enter-2">
      <el-input
        v-model="keyword"
        placeholder="搜索客户/业务员/主管"
        clearable
        class="keyword-input"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <div class="commission-filter-bar__actions">
        <GlassButton variant="primary" left-icon="Search" @click="handleSearch">查询</GlassButton>
      </div>
    </div>

    <!-- 明细表格 -->
    <div class="table-card commission-panel commission-lift cm-enter-3">
      <el-table ref="tableRef" :data="tableData" v-loading="loading" class="list-table" border :max-height="maxHeight" @sort-change="orderSort.onSortChange">
        <el-table-column prop="payment_id" label="回款ID" min-width="160" max-width="240" show-overflow-tooltip />
        <el-table-column prop="order_id" label="订单ID" min-width="160" max-width="240" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户名称" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="payment_amount" label="回款金额（美元）" min-width="130" max-width="190" align="right" sortable="custom">
          <template #default="{ row }">{{ usdOrDash(row.payment_amount) }}</template>
        </el-table-column>
        <el-table-column prop="salesperson_name" label="业务员" min-width="90" max-width="140" show-overflow-tooltip sortable="custom" />
        <el-table-column label="业务员比例" min-width="100" max-width="150" align="right">
          <template #default="{ row }">{{ commissionRate(row.salesperson_rate) }}</template>
        </el-table-column>
        <el-table-column prop="salesperson_commission" label="业务员提成" min-width="110" max-width="160" align="right" sortable="custom">
          <template #default="{ row }">{{ usdOrDash(row.salesperson_commission) }}</template>
        </el-table-column>
        <el-table-column prop="supervisor_name" label="一级主管" min-width="90" max-width="140" show-overflow-tooltip />
        <el-table-column label="一级主管比例" min-width="110" max-width="160" align="right">
          <template #default="{ row }">{{ commissionRate(row.supervisor_rate) }}</template>
        </el-table-column>
        <el-table-column label="一级主管提成" min-width="120" max-width="180" align="right">
          <template #default="{ row }">{{ usdOrDash(row.supervisor_commission) }}</template>
        </el-table-column>
        <el-table-column prop="second_supervisor_name" label="二级主管" min-width="90" max-width="140" show-overflow-tooltip />
        <el-table-column label="二级主管比例" min-width="110" max-width="160" align="right">
          <template #default="{ row }">{{ commissionRate(row.second_supervisor_rate) }}</template>
        </el-table-column>
        <el-table-column label="二级主管提成" min-width="120" max-width="180" align="right">
          <template #default="{ row }">{{ usdOrDash(row.second_supervisor_commission) }}</template>
        </el-table-column>
        <el-table-column prop="calc_rule_note" label="计算规则" min-width="130" max-width="200" show-overflow-tooltip />
      </el-table>
    </div>

    <el-pagination
      class="commission-pagination commission-lift cm-enter-4"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next, sizes"
      :page-sizes="[20, 50, 100]"
      @current-change="fetchDetails"
      @size-change="fetchDetails"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getBatchDetails, getBatchSummary } from '@/api/commission'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useTableSort } from '@/composables/useTableSort'
import { batchStatusLabel, batchStatusType, commissionRate, usdOrDash } from './commissionFormat'
import CommissionMetricCards from './components/CommissionMetricCards.vue'

const { tableRef, maxHeight } = useTableMaxHeight()
const orderSort = useTableSort()

const route = useRoute()
const router = useRouter()
const batchId = route.params.batchId

const summary = ref(null)
const summaryLoading = ref(false)
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

async function fetchSummary() {
  summaryLoading.value = true
  try {
    const res = await getBatchSummary(batchId)
    summary.value = res.data
  } catch { /* 拦截器已提示，明细表不受影响 */ }
  finally {
    summaryLoading.value = false
  }
}

function handleSearch() {
  page.value = 1
  fetchDetails()
}

async function fetchDetails() {
  loading.value = true
  try {
    const res = await getBatchDetails(batchId, {
      keyword: keyword.value,
      page: page.value,
      page_size: pageSize.value,
      ...orderSort.sortParams.value
    })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchSummary()
  fetchDetails()
})
</script>

<style scoped src="./commission.css"></style>

<style scoped>
.keyword-input {
  width: 280px;
  max-width: 100%;
}

.list-table {
  width: 100%;
}
</style>
