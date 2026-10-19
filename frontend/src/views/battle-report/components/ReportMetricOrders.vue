<template>
  <section class="table-card battle-panel metric-orders">
    <p class="metric-note">{{ metricNote }} 下单日期沿用战报核算日期，金额统一为 USD。</p>
    <p v-if="report.award_kind === 'new_sign_pk'" class="metric-note">本明细按原新签客户归属核对；PK 总览的“新签金额”按订单负责人统计，客户转交后两者金额可能不同。</p>
    <FilterBar :loading="loading" :pending="state.hasPendingSearch.value" @search="state.handleSearch" @reset="state.handleReset">
      <el-input v-model="searchForm.customer" clearable placeholder="客户名称" aria-label="客户名称" class="filter-w-md" />
      <el-input v-model="searchForm.order_name" clearable placeholder="订单名称" aria-label="订单名称" class="filter-w-md" />
      <el-date-picker v-model="searchForm.dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="下单开始日期" end-placeholder="下单结束日期" aria-label="下单日期范围" class="filter-w-lg" />
      <el-select v-model="searchForm.member_id" clearable placeholder="全部可查看业务员" aria-label="业务员范围" class="filter-w-md">
        <el-option v-for="member in detailMembers" :key="member.id" :label="member.user_name" :value="member.id" />
      </el-select>
    </FilterBar>
    <div v-if="meta && !error" class="battle-order-summary" role="status">
      <b>{{ meta.data_complete ? '合计金额' : '已识别金额（待核对）' }}：USD {{ formatMoney(meta.total_amount) }}</b>
      <span>合计 {{ meta.total }} 笔订单 / {{ meta.customer_count }} 位客户 · 全部筛选结果</span>
    </div>
    <el-alert v-if="meta?.warning && !error" :title="meta.warning" type="warning" :closable="false" show-icon />
    <ListPageStatus v-if="state.hasData.value" :error="state.errorMessage.value" :loading="loading" :has-data="true" :data-page="state.dataPage.value" @retry="state.fetchList" />
    <el-table ref="tableRef" v-loading="loading" :data="list" :max-height="maxHeight" border class="list-table" v-sticky-scrollbar @sort-change="event => state.handleSortChange(tableSortParams(event))">
      <template #empty><ListPageStatus :error="state.errorMessage.value" :loading="loading" :has-data="false" @retry="state.fetchList">当前可查看范围及筛选条件下暂无订单</ListPageStatus></template>
      <el-table-column sortable="custom" prop="company_name" label="客户名称" min-width="180" max-width="280" show-overflow-tooltip />
      <el-table-column sortable="custom" prop="order_name" label="订单名称" min-width="200" max-width="320" show-overflow-tooltip />
      <el-table-column sortable="custom" prop="order_no" label="订单号" min-width="170" max-width="230" show-overflow-tooltip />
      <el-table-column sortable="custom" prop="account_date" label="下单日期" min-width="130" max-width="160" />
      <el-table-column sortable="custom" prop="amount_usd" label="下单金额 / USD" min-width="165" max-width="200" align="right"><template #default="{ row }">{{ formatMoney(row.amount_usd) }}</template></el-table-column>
      <el-table-column sortable="custom" prop="user_name" label="统计归属业务员" min-width="150" max-width="200" show-overflow-tooltip />
    </el-table>
    <el-pagination class="pager" :current-page="page" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="state.handlePageChange" @size-change="state.handleSizeChange" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import FilterBar from '@/components/FilterBar.vue'
import ListPageStatus from '@/components/ListPageStatus.vue'
import { useListPage } from '@/composables/useListPage'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { battleReportApi } from '@/api/battleReport'
import { formatMoney } from '@/utils/money'
import { tableSortParams } from '@/utils/tableSort'

const props = defineProps({ report: { type: Object, required: true }, metric: { type: String, required: true }, team: { type: String, default: '' } })
const meta = ref(null)
const { tableRef, maxHeight } = useTableMaxHeight(84)
const detailMembers = computed(() => props.report.members.filter(member => props.report.detail_member_ids.includes(member.id) && (!props.team || member.team === props.team)))
const metricNote = computed(() => ({
  new_sign: '展示周期内新签客户的新签订单，客户数去重；同一客户可有多笔订单。',
  repeat: '展示周期内新签客户在首次新签后的复购订单，归原新签业务员。',
  combined: '展示周期内新签客户的新签及后续复购订单，含尚未复购客户。',
})[props.metric])
const state = useListPage(async ({ dates, member_id, ...params }, { signal, isCurrent }) => {
  if (!detailMembers.value.length) {
    if (isCurrent()) meta.value = null
    return { items: [], total: 0 }
  }
  const result = await battleReportApi.metricOrders(props.report.id, {
    ...params, metric: props.metric, team: props.team || undefined, member_id: member_id || undefined,
    start_date: dates?.[0], end_date: dates?.[1],
  }, { signal, suppressToast: true })
  if (isCurrent()) meta.value = result
  return result
}, { searchForm: { customer: '', order_name: '', dates: [], member_id: '' } })
const { list, loading, error, page, pageSize, total, searchForm } = state
</script>

<style scoped>
.metric-note { margin: 0 0 12px; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.metric-orders { min-width: 0; }
.metric-orders .pager { overflow-x: auto; }
</style>
