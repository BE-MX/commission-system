<template>
  <div class="aftersales-list-page">
    <div class="page-heading">
      <div>
        <h1>{{ reviewMode ? '待我审核' : '售后单' }}</h1>
        <p>{{ reviewMode ? '集中处理当前需要你判断的售后方案' : '登记、跟踪并复盘客户售后问题' }}</p>
      </div>
      <GlassButton v-if="!reviewMode" v-permission="'aftersales:write'" variant="primary" left-icon="Plus" @click="createCase">
        新建售后单
      </GlassButton>
    </div>

    <div class="toolbar">
      <el-segmented v-if="!reviewMode" v-permission="'aftersales:read_all'" v-model="filters.scope" :options="[{ label: '我的售后', value: 'mine' }, { label: '全部售后', value: 'all' }]" @change="search" />
      <el-input v-model="filters.keyword" placeholder="搜索单号、客户或订单号" clearable class="keyword" @keyup.enter="search">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="filters.status" placeholder="全部状态" clearable @change="search">
        <el-option v-for="(label, value) in STATUS_LABELS" :key="value" :label="label" :value="value" />
      </el-select>
      <el-select v-model="filters.issue_type" placeholder="全部问题" clearable @change="search">
        <el-option v-for="item in issueTypes" :key="item.code" :label="item.label" :value="item.code" />
      </el-select>
      <el-select v-model="filters.has_compensation" placeholder="赔偿属性" clearable @change="search">
        <el-option label="涉及赔偿" :value="true" />
        <el-option label="不涉及赔偿" :value="false" />
      </el-select>
      <el-select v-model="filters.customer_grade" placeholder="客户等级" clearable @change="search"><el-option v-for="grade in ['A', 'B', 'C', 'D', 'E']" :key="grade" :label="`${grade} 级客户`" :value="grade" /></el-select>
      <el-select v-model="filters.responsibility_class" placeholder="责任分类" clearable @change="search"><el-option v-for="grade in ['A', 'B', 'C', 'D']" :key="grade" :label="`${grade} 类责任`" :value="grade" /></el-select>
      <el-select v-model="filters.creator_user_id" filterable clearable placeholder="业务员" @change="search"><el-option v-for="item in people" :key="item.user_id" :label="item.real_name" :value="item.user_id" /></el-select>
      <el-select v-model="filters.current_owner_user_id" filterable clearable placeholder="当前审批人" @change="search"><el-option v-for="item in people" :key="item.user_id" :label="item.real_name" :value="item.user_id" /></el-select>
      <el-date-picker v-model="filters.date_range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="反馈开始日期" end-placeholder="反馈结束日期" @change="search" />
      <GlassButton variant="secondary" left-icon="Refresh" @click="fetchList">刷新</GlassButton>
    </div>

    <div class="table-card">
      <el-table :data="cases" v-loading="loading" border class="list-table" style="width: 100%" @row-dblclick="openCase">
        <el-table-column prop="case_no" label="售后单号" min-width="150" max-width="210" show-overflow-tooltip>
          <template #default="{ row }"><button class="case-link" @click="openCase(row)">{{ row.case_no }}</button></template>
        </el-table-column>
        <el-table-column prop="customer_name_snapshot" label="客户" min-width="150" max-width="240" show-overflow-tooltip />
        <el-table-column prop="order_no_snapshot" label="订单号" min-width="120" max-width="180" show-overflow-tooltip />
        <el-table-column prop="primary_issue_type" label="问题类型" min-width="110" max-width="160" show-overflow-tooltip />
        <el-table-column prop="product_name_snapshot" label="产品" min-width="150" max-width="240" show-overflow-tooltip />
        <el-table-column label="证据" min-width="100" max-width="130">
          <template #default="{ row }"><span class="tabular">{{ row.evidence_score }}%</span></template>
        </el-table-column>
        <el-table-column label="责任判定" min-width="110" max-width="150">
          <template #default="{ row }"><el-tag v-if="row.responsibility_class" effect="plain">{{ row.responsibility_class }} 类</el-tag><span v-else>—</span></template>
        </el-table-column>
        <el-table-column label="赔偿成本" min-width="120" max-width="170">
          <template #default="{ row }"><span class="tabular">{{ row.has_compensation ? `USD ${row.estimated_compensation_usd}` : '无赔偿' }}</span></template>
        </el-table-column>
        <el-table-column label="处理措施" min-width="160" max-width="260" show-overflow-tooltip><template #default="{ row }">{{ actionSummary(row.selected_actions_json) }}</template></el-table-column>
        <el-table-column label="状态" min-width="120" max-width="170">
          <template #default="{ row }"><el-tag :type="statusType(row.current_status)" effect="plain">{{ STATUS_LABELS[row.current_status] || row.current_status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="creator_name_snapshot" label="业务员" min-width="100" max-width="150" show-overflow-tooltip />
        <el-table-column prop="current_owner_name" label="当前责任人" min-width="110" max-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.current_owner_name || '—' }}</template></el-table-column>
        <el-table-column label="等待时长" min-width="100" max-width="130"><template #default="{ row }"><span class="tabular">{{ row.waiting_hours }}h</span></template></el-table-column>
        <el-table-column label="操作" min-width="100" max-width="130" fixed="right">
          <template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="openCase(row)">查看</GlassButton></template>
        </el-table-column>
      </el-table>
    </div>

    <el-pagination
      v-model:current-page="page" v-model:page-size="pageSize" class="pager"
      :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
      @current-change="handlePageChange" @size-change="handleSizeChange"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAfterSalesCases, getAfterSalesOptions, searchAfterSalesPeople } from '@/api/aftersales'
import { useListPage } from '@/composables/useListPage'
import { STATUS_LABELS } from './aftersalesRules'

const route = useRoute()
const router = useRouter()
const reviewMode = computed(() => route.name === 'AfterSalesReviews')
const issueTypes = ref([])
const actionOptions = ref([])
const people = ref([])

const {
  loading, list: cases, total, page, pageSize, searchForm: filters,
  fetchList, handleSearch: search, handlePageChange, handleSizeChange,
} = useListPage(async params => {
  const cleaned = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value !== null))
  if (cleaned.date_range?.length === 2) {
    cleaned.date_from = cleaned.date_range[0]; cleaned.date_to = cleaned.date_range[1]
  }
  delete cleaned.date_range
  if (reviewMode.value) cleaned.assigned_to_me = true
  const response = await getAfterSalesCases(cleaned)
  return response.data || {}
}, { immediate: false, searchForm: { scope: 'mine', keyword: '', status: '', issue_type: '', has_compensation: null, customer_grade: '', responsibility_class: '', creator_user_id: null, current_owner_user_id: null, date_range: null } })

function statusType(status) {
  if (['approved', 'closed'].includes(status)) return 'success'
  if (['rejected', 'ai_failed'].includes(status)) return 'danger'
  if (['returned', 'awaiting_evidence_waiver', 'awaiting_supervisor', 'awaiting_director'].includes(status)) return 'warning'
  return 'info'
}

function openCase(row) { router.push(`/aftersales/cases/${row.id}`) }
function createCase() { router.push('/aftersales/cases/new') }
function actionSummary(actions) { return (actions || []).map(action => actionOptions.value.find(item => item.code === action.code)?.label || action.code).join('、') || '—' }

watch(() => route.name, fetchList)
onMounted(async () => {
  try {
    const response = await getAfterSalesOptions()
    issueTypes.value = response.data?.issue_types || []
    actionOptions.value = response.data?.actions || []
    people.value = (await searchAfterSalesPeople({ keyword: '' })).data?.items || []
  } catch {
    // 下拉选项/人员加载失败时降级为空，绝不阻断主列表加载
  }
  fetchList()
})
</script>

<style scoped>
.aftersales-list-page { min-width: 0; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 20px; }
.page-heading h1 { margin: 0 0 4px; font: 700 20px/1.3 var(--font-display); color: var(--text-primary); }
.page-heading p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
.toolbar .keyword { width: 280px; }
.toolbar :deep(.el-select) { width: 150px; }
.case-link { border: 0; padding: 0; background: transparent; color: var(--color-primary); font: 600 13px/1.4 var(--font-body); cursor: pointer; }
.tabular { font-variant-numeric: tabular-nums; }
.pager { margin-top: 16px; justify-content: flex-end; }
</style>
