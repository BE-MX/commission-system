<template>
  <div class="aftersales-list-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="aftersales-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-heading">
      <div>
        <h1>{{ reviewMode ? '待我审核' : '售后单' }}</h1>
        <p>{{ reviewMode ? '集中处理当前需要你判断的售后方案' : '登记、跟踪并复盘客户售后问题' }}</p>
      </div>
    </div>

    <div ref="panelRef" class="table-card aftersales-panel">
      <FilterBar  class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="search" @reset="reset"><el-segmented v-if="!reviewMode" v-permission="'aftersales:read_all'" v-model="filters.scope" :options="[{ label: '我的售后', value: 'mine' }, { label: '全部售后', value: 'all' }]"  />
<el-input v-model="filters.keyword" placeholder="搜索单号、客户或订单号" clearable class="filter-w-lg" >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
<el-select v-model="filters.status" placeholder="全部状态" clearable class="filter-w-sm" >
          <el-option v-for="(label, value) in STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
<el-select v-model="filters.issue_type" placeholder="全部问题" clearable class="filter-w-sm" >
          <el-option v-for="item in issueTypes" :key="item.code" :label="item.label" :value="item.code" />
        </el-select>
<template #advanced><el-select v-model="filters.has_compensation" placeholder="赔偿属性" clearable class="filter-w-sm" >
          <el-option label="涉及赔偿" :value="true" />
          <el-option label="不涉及赔偿" :value="false" />
        </el-select>
<el-select v-model="filters.customer_grade" placeholder="客户等级" clearable class="filter-w-sm" ><el-option v-for="grade in ['A', 'B', 'C', 'D', 'E']" :key="grade" :label="`${grade} 级客户`" :value="grade" /></el-select>
<el-select v-model="filters.responsibility_class" placeholder="责任分类" clearable class="filter-w-sm" ><el-option v-for="grade in ['A', 'B', 'C', 'D']" :key="grade" :label="`${grade} 类责任`" :value="grade" /></el-select>
<el-select v-model="filters.creator_user_id" filterable clearable placeholder="业务员" class="filter-w-sm" ><el-option v-for="item in people" :key="item.user_id" :label="item.real_name" :value="item.user_id" /></el-select>
<el-select v-model="filters.current_owner_user_id" filterable clearable placeholder="当前审批人" class="filter-w-sm" ><el-option v-for="item in people" :key="item.user_id" :label="item.real_name" :value="item.user_id" /></el-select>
<el-date-picker v-model="filters.date_range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="反馈开始日期" end-placeholder="反馈结束日期" class="filter-w-lg"  />
</template></FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-if="!reviewMode" v-permission="'aftersales:write'" variant="primary" left-icon="Plus" @click="createCase">
          新建售后单
        </GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="fetchList" />
<el-table :data="cases" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @row-dblclick="openCase">
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('case-no')" prop="case_no" label="售后单号" min-width="150" max-width="210" show-overflow-tooltip>
          <template #default="{ row }"><button class="case-link" @click="openCase(row)">{{ row.case_no }}</button></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('customer')" prop="customer_name_snapshot" label="客户" min-width="150" max-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('order-no')" prop="order_no_snapshot" label="订单号" min-width="120" max-width="180" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('issue-type')" prop="primary_issue_type" label="问题类型" min-width="110" max-width="160" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('product')" prop="product_name_snapshot" label="产品" min-width="150" max-width="240" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('evidence')" label="证据" min-width="100" max-width="130">
          <template #default="{ row }"><span class="tabular">{{ row.evidence_score }}%</span></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('responsibility')" label="责任判定" min-width="110" max-width="150">
          <template #default="{ row }"><StatusBadge v-if="row.responsibility_class" effect="plain">{{ row.responsibility_class }} 类</StatusBadge><span v-else>—</span></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('compensation')" label="赔偿成本" min-width="120" max-width="170">
          <template #default="{ row }"><span class="tabular">{{ row.has_compensation ? formatMoney(row.estimated_compensation_usd, { currency: 'USD', missing: '—' }) : '无赔偿' }}</span></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('actions')" label="处理措施" min-width="160" max-width="260" show-overflow-tooltip><template #default="{ row }">{{ actionSummary(row.selected_actions_json) }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="200" max-width="230">
          <template #default="{ row }"><StatusBadge :value="row.current_status" :dictionary="CASE_STATUS" effect="plain" /></template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('creator')" prop="creator_name_snapshot" label="业务员" min-width="100" max-width="150" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('owner')" prop="current_owner_name" label="当前责任人" min-width="110" max-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.current_owner_name || '—' }}</template></el-table-column>
        <el-table-column v-if="visibleKeys.includes('waiting')" label="等待时长" min-width="100" max-width="130"><template #default="{ row }"><span class="tabular">{{ row.waiting_hours }}h</span></template></el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="100" max-width="130" fixed="right">
          <template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="openCase(row)">查看</GlassButton></template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" class="pager"
        :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { formatMoney } from '../../utils/money.js'

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAfterSalesCases, getAfterSalesOptions, searchAfterSalesPeople } from '@/api/aftersales'
import { watchListResourceScope } from '@/composables/useListResourceScope'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { CASE_STATUS, STATUS_LABELS } from './aftersalesRules'

const route = useRoute()
const router = useRouter()
const reviewMode = computed(() => route.name === 'AfterSalesReviews')
const issueTypes = ref([])
const actionOptions = ref([])
const people = ref([])

// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'case-no', label: '售后单号' },
  { key: 'customer', label: '客户' },
  { key: 'order-no', label: '订单号' },
  { key: 'issue-type', label: '问题类型' },
  { key: 'product', label: '产品' },
  { key: 'evidence', label: '证据' },
  { key: 'responsibility', label: '责任判定' },
  { key: 'compensation', label: '赔偿成本' },
  { key: 'actions', label: '处理措施' },
  { key: 'status', label: '状态' },
  { key: 'creator', label: '业务员' },
  { key: 'owner', label: '当前责任人' },
  { key: 'waiting', label: '等待时长' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('aftersales-list', columnDefs)

const listPageState = useListPage(async (params, { signal, isCurrent }) => {
  const cleaned = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '' && value !== null))
  if (cleaned.date_range?.length === 2) {
    cleaned.date_from = cleaned.date_range[0]; cleaned.date_to = cleaned.date_range[1]
  }
  delete cleaned.date_range
  if (!cleaned.assigned_to_me) delete cleaned.assigned_to_me
  const response = await getAfterSalesCases(cleaned, { signal, suppressToast: true })
  return response.data || {}
}, { immediate: false, searchForm: { assigned_to_me: reviewMode.value, scope: 'mine', keyword: '', status: '', issue_type: '', has_compensation: null, customer_grade: '', responsibility_class: '', creator_user_id: null, current_owner_user_id: null, date_range: null } })
const {
  loading, list: cases, total, page, pageSize, searchForm: filters,
  fetchList, handleSearch: search, handleReset, handlePageChange, handleSizeChange,
} = listPageState

function reset() { Object.assign(filters, { keyword: '', status: '', issue_type: '', has_compensation: null, customer_grade: '', responsibility_class: '', creator_user_id: null, current_owner_user_id: null, date_range: null }); filters.assigned_to_me = reviewMode.value; return search() }

// scope（我的/全部）是视角切换而非筛选条件，不计入空态的「有筛选」判断
const hasActiveFilters = computed(() => Boolean(
  filters.keyword || filters.status || filters.issue_type || filters.has_compensation !== null
  || filters.customer_grade || filters.responsibility_class || filters.creator_user_id
  || filters.current_owner_user_id || filters.date_range?.length,
))



function openCase(row) { router.push(`/aftersales/cases/${row.id}`) }
function createCase() { router.push('/aftersales/cases/new') }
function actionSummary(actions) { return (actions || []).map(action => actionOptions.value.find(item => item.code === action.code)?.label || action.code).join('、') || '—' }

watchListResourceScope(listPageState, ['scope', 'assigned_to_me'])
watch(() => route.name, () => { filters.assigned_to_me = reviewMode.value; search() })
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
.aftersales-list-page { min-width: 0; position: relative; }
/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.aftersales-aurora { inset: -24px -28px; }
/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-drawer/el-dialog 的 .el-overlay position: fixed */
.aftersales-list-page .page-heading,
.aftersales-list-page .aftersales-panel { position: relative; z-index: 1; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 20px; }
.page-heading h1 { margin: 0 0 4px; font: 700 20px/1.3 var(--font-display); color: var(--text-primary); }
.page-heading p { margin: 0; color: var(--text-secondary); font-size: 13px; }
/* 筛选控件三档宽度、操作行、分页均为全局规范类（app.css），本页只保留玻璃皮肤覆写 */
.toolbar { border-bottom: 1px solid var(--border-color); background: rgba(255, 255, 255, 0.4); }
.action-bar { background: rgba(255, 255, 255, 0.28); }
/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.aftersales-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}
/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.aftersales-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}
/* 右侧固定操作列：sticky 单元格 + background: inherit，行透明时会透底重影，
   改成磨砂不透明的暖白，表头/hover 态同步（同 invoice-manage.css） */
.aftersales-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.aftersales-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.aftersales-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }
.case-link { border: 0; padding: 0; background: transparent; color: var(--color-primary-text); font: 600 13px/1.4 var(--font-body); cursor: pointer; }
.tabular { font-variant-numeric: tabular-nums; }
</style>
