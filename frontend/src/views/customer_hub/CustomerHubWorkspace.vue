<template>
  <main class="hub-page customer-hub">
    <div class="hub-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>
    <header class="hub-header">
      <div>
        <span class="hub-kicker">CUSTOMER OPERATIONS</span>
        <h1>{{ config.title }}</h1>
        <p>{{ config.description }}</p>
      </div>
      <div class="header-context">
        <strong>{{ total }}</strong>
        <span>{{ config.countLabel }}</span>
      </div>
    </header>

    <section ref="panelRef" class="hub-table table-card lg-card is-static" :aria-busy="loading">
      <FilterBar v-if="hasFilterControls" aria-label="列表筛选" class="toolbar hub-toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="handleSearch" @reset="listPageState.handleReset"><el-input
          v-if="kind === 'customers'"
          v-model="searchForm.keyword"
          clearable
          placeholder="按客户编号或名称搜索"
          aria-label="搜索客户"
          class="filter-w-lg"

        />
<el-select v-else-if="kind === 'acquisition'" v-model="searchForm.status" clearable placeholder="全部任务状态" aria-label="筛选任务状态" class="filter-w-sm">
          <el-option v-for="status in ['pending', 'running', 'completed', 'failed']" :key="status" :label="statusLabel(status)" :value="status" />
        </el-select>
<el-select v-else-if="kind === 'research'" v-model="searchForm.review_status" clearable placeholder="全部研究任务" aria-label="筛选研究质量" class="filter-w-md"><el-option label="已完成 · 待质量复核" value="pending" /><el-option label="质量已通过" value="accepted" /><el-option label="待修订" value="revision_requested" /><el-option label="已驳回" value="rejected" /></el-select>
<div v-else class="toolbar-note">按最近更新时间排序 · 权限范围由方舟统一控制</div></FilterBar>
      <div v-else class="toolbar toolbar-note">按最近更新时间排序 · 权限范围由方舟统一控制</div>
      <!-- 操作行：页面主操作经 actions 插槽注入，右侧 TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <slot name="actions" />
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
<el-table v-loading="loading" :data="list" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" :row-key="rowKey" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : config.emptyText">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="handleReset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <template v-if="kind === 'customers'">
          <el-table-column v-if="visibleKeys.includes('customer')" label="客户" min-width="220" max-width="360">
            <template #default="{ row }">
              <button class="customer-link" :title="row.display_name || row.canonical_company_name" type="button" @click="openCustomer(row.customer_id)">
                <strong>{{ row.display_name || row.canonical_company_name || `临时客户 #${row.customer_id}` }}</strong>
                <span>{{ row.customer_code || `ID ${row.customer_id}` }}</span>
              </button>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleKeys.includes('identity')" label="身份" min-width="140"><template #default="{ row }"><StatusBadge :type="row.identity_status === 'verified' ? 'success' : 'warning'" size="small">{{ identityLabel(row.identity_status) }}</StatusBadge></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('industry')" prop="primary_industry" label="行业" min-width="130" max-width="220" show-overflow-tooltip><template #default="{ row }">{{ row.primary_industry || '待补充' }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('relationship-stage')" prop="relationship_stage" label="关系阶段" min-width="120" max-width="180" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('ownership')" label="归属" min-width="118"><template #default="{ row }">{{ row.is_public_pool ? '公海' : '已分配' }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('completeness')" label="完整度" min-width="105"><template #default="{ row }">{{ row.profile_completeness }}%</template></el-table-column>
          <el-table-column label="操作" min-width="120" max-width="150" class-name="table-action-column" fixed="right">
            <template #default="{ row }">
              <GlassButton variant="link" left-icon="FolderOpened" @click="$router.push(`/customer-hub/workspace/${row.customer_id}`)">工作区</GlassButton>
            </template>
          </el-table-column>
        </template>

        <template v-else-if="kind === 'acquisition'">
          <el-table-column v-if="visibleKeys.includes('task')" prop="name" label="任务" min-width="220" max-width="360" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="140"><template #default="{ row }"><StatusBadge :type="tagType(row.status)" size="small">{{ statusLabel(row.status) }}</StatusBadge></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('target-result')" label="目标 / 结果" min-width="130"><template #default="{ row }">{{ row.target_count ?? 0 }} / {{ row.result_count ?? 0 }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('archived-customers')" label="归档客户" min-width="110"><template #default="{ row }">{{ row.created_customer_count ?? 0 }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('policy-version')" prop="policy_version" label="策略版本" min-width="130" max-width="180" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('feedback')" label="反馈" min-width="190" max-width="320" show-overflow-tooltip><template #default="{ row }"><span :class="{ danger: getSearchJobFeedback(row).tone === 'danger' }">{{ getSearchJobFeedback(row).text }}</span></template></el-table-column>
          <el-table-column label="操作" min-width="224" max-width="264" class-name="table-action-column" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="$emit('view-results', row)">查看结果</GlassButton><GlassButton v-if="canRequeueJob(row)" v-any-permission="['sales_automation:write', 'sales_automation:admin']" variant="link" left-icon="RefreshRight" :loading="mutatingId === row.job_id" @click="retryJob(row)">重新入队</GlassButton></template></el-table-column>
        </template>

        <template v-else-if="kind === 'research'">
          <el-table-column v-if="visibleKeys.includes('customer')" label="客户" min-width="130"><template #default="{ row }"><button v-if="canOpenDetail" class="customer-link compact" :title="row.customer_name" type="button" @click="openCustomer(row.customer_id)">{{ row.customer_name || `临时客户 #${row.customer_id}` }}</button><span v-else>{{ row.customer_name || `临时客户 #${row.customer_id}` }}</span></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('research-type')" label="背调类型" min-width="150" max-width="240" show-overflow-tooltip><template #default="{ row }">{{ researchTypeLabels[row.task_type] || '客户研究' }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('tier')" prop="tier" label="层级" min-width="90" />
          <el-table-column v-if="visibleKeys.includes('exec-status')" label="执行状态" min-width="140"><template #default="{ row }"><StatusBadge :type="tagType(row.task_status)" size="small">{{ statusLabel(row.task_status) }}</StatusBadge></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('quality')" label="研究质量" min-width="120"><template #default="{ row }">{{ operationStatusLabel(row.result_review_status) }}</template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('data-classification')" label="数据级别" min-width="150" max-width="220" show-overflow-tooltip><template #default="{ row }">{{ classificationLabels[row.data_classification] || '待确认' }}</template></el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="128" max-width="160" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="$emit('inspect-task', row)">查看详情</GlassButton></template></el-table-column>
        </template>

        <template v-else-if="kind === 'opportunities'">
          <el-table-column v-if="visibleKeys.includes('opportunity')" prop="title" label="机会" min-width="240" max-width="380" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('customer')" label="客户" min-width="120"><template #default="{ row }"><button v-if="canOpenDetail" class="customer-link compact" :title="row.customer_name" type="button" @click="openCustomer(row.customer_id)">{{ row.customer_name || `临时客户 #${row.customer_id}` }}</button><span v-else>{{ row.customer_name || `临时客户 #${row.customer_id}` }}</span></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="140"><template #default="{ row }"><StatusBadge :type="tagType(row.status)" size="small">{{ statusLabel(row.status) }}</StatusBadge></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('priority')" prop="priority_level" label="优先级" min-width="100" />
          <el-table-column v-if="visibleKeys.includes('owner')" prop="owner_name" label="负责人" min-width="100" />
          <el-table-column v-if="visibleKeys.includes('due-at')" label="截止时间" min-width="170"><template #default="{ row }">{{ formatDate(row.due_at) }}</template></el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="100" max-width="140" fixed="right"><template #default="{ row }"><GlassButton v-any-permission="['customer_opportunity:write', 'customer:admin']" variant="link" left-icon="Edit" :disabled="!row.can_operate || getOpportunityTransitionOptions(row.status).length === 0" @click="$emit('edit-opportunity', row)">更新</GlassButton></template></el-table-column>
        </template>

        <template v-else>
          <el-table-column v-if="visibleKeys.includes('action')" prop="action_type" label="建议动作" min-width="200" max-width="360" show-overflow-tooltip />
          <el-table-column v-if="visibleKeys.includes('customer')" label="客户" min-width="120"><template #default="{ row }"><button v-if="canOpenDetail" class="customer-link compact" :title="row.customer_name" type="button" @click="openCustomer(row.customer_id)">{{ row.customer_name || `临时客户 #${row.customer_id}` }}</button><span v-else>{{ row.customer_name || `临时客户 #${row.customer_id}` }}</span></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="140"><template #default="{ row }"><StatusBadge :type="tagType(row.status)" size="small">{{ statusLabel(row.status) }}</StatusBadge></template></el-table-column>
          <el-table-column v-if="visibleKeys.includes('priority')" prop="priority" label="优先级" min-width="100" />
          <el-table-column v-if="visibleKeys.includes('due-at')" label="建议完成时间" min-width="170"><template #default="{ row }">{{ formatDate(row.due_at) }}</template></el-table-column>
          <el-table-column class-name="table-action-column" label="操作" min-width="128" max-width="160" fixed="right"><template #default="{ row }"><GlassButton v-any-permission="['customer_radar:write', 'customer:admin']" variant="link" left-icon="Operation" :disabled="getRadarOperationOptions(row.status).length === 0" @click="$emit('operate-action', row)">处理</GlassButton></template></el-table-column>
        </template>

        <el-table-column label="最近更新" min-width="176"><template #default="{ row }">{{ formatDate(row.updated_at) }}</template></el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :pager-count="5"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </section>

    <CustomerDetailDrawer
      v-model="drawerVisible"
      :customer="detail"
      :loading="detailLoading"
      :timeline="timeline"
      :timeline-total="timelineTotal"
      :timeline-loading="timelineLoading"
      :detail-error="detailError"
      :timeline-error="timelineError"
      :load-timeline="loadTimeline"
      :retry-detail="() => loadDetail(currentCustomerId)"
    />
  </main>
</template>

<script setup>
import './customerHub.css'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useAuthStore } from '@/stores/auth'
import { canRequeueJob, createSearchJobPollingController, getOpportunityTransitionOptions, getRadarOperationOptions, getSearchJobFeedback, shouldPollSearchJobs } from './customerHubController'
import CustomerDetailDrawer from './CustomerDetailDrawer.vue'
import { classificationLabels, identityLabel, researchTypeLabels, statusLabel as operationStatusLabel } from './operationsPresentation'
import { useCustomerHub } from './composables/useCustomerHub'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'

const props = defineProps({ kind: { type: String, required: true } })
defineEmits(['inspect-task', 'edit-opportunity', 'operate-action', 'view-results'])
const auth = useAuthStore()
const canOpenDetail = computed(() => props.kind === 'customers' || auth.hasPermission('customer:read'))
const formatDate = value => value ? formatBeijingDateTime(value) : '—'
const CONFIG = {
  customers: { title: '客户档案', description: '方舟唯一客户主档：先识别主体，再组织证据与经营动作。', countLabel: '可见客户', emptyText: '暂无可见客户；无主负责人客户会进入公海。' },
  acquisition: { title: '获客任务', description: '追踪搜索任务、策略版本与进入方舟主档的结果。', countLabel: '搜索任务', emptyText: '暂无搜索任务。' },
  research: { title: '背调中心', description: '查看客户证据采集进度与人工复核状态。', countLabel: '背调任务', emptyText: '暂无待处理背调任务。' },
  opportunities: { title: '客户机会', description: '跟进客户机会，结合沟通证据更新进展。', countLabel: '经营机会', emptyText: '当前没有可见客户机会。' },
  radar: { title: '经营雷达', description: '把高优先级信号转成清晰、可反馈的下一步行动。', countLabel: '建议动作', emptyText: '当前没有待处理经营动作。' },
}
const config = CONFIG[props.kind]

// 表格视图状态：列显隐/密度/全屏（Action Bar Spec）。各工作区列集不同，按 kind 取列定义
const COLUMN_DEFS = {
  customers: [
    { key: 'customer', label: '客户' },
    { key: 'identity', label: '身份' },
    { key: 'industry', label: '行业' },
    { key: 'relationship-stage', label: '关系阶段' },
    { key: 'ownership', label: '归属' },
    { key: 'completeness', label: '完整度' },
  ],
  acquisition: [
    { key: 'task', label: '任务' },
    { key: 'status', label: '状态' },
    { key: 'target-result', label: '目标 / 结果' },
    { key: 'archived-customers', label: '归档客户' },
    { key: 'policy-version', label: '策略版本' },
    { key: 'feedback', label: '反馈' },
  ],
  research: [
    { key: 'customer', label: '客户' },
    { key: 'research-type', label: '背调类型' },
    { key: 'tier', label: '层级' },
    { key: 'exec-status', label: '执行状态' },
    { key: 'quality', label: '研究质量' },
    { key: 'data-classification', label: '数据级别' },
  ],
  opportunities: [
    { key: 'opportunity', label: '机会' },
    { key: 'customer', label: '客户' },
    { key: 'status', label: '状态' },
    { key: 'priority', label: '优先级' },
    { key: 'owner', label: '负责人' },
    { key: 'due-at', label: '截止时间' },
  ],
  radar: [
    { key: 'action', label: '建议动作' },
    { key: 'customer', label: '客户' },
    { key: 'status', label: '状态' },
    { key: 'priority', label: '优先级' },
    { key: 'due-at', label: '建议完成时间' },
  ],
}
const columnDefs = COLUMN_DEFS[props.kind] || []
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView(`customer-hub-${props.kind}`, columnDefs)
const drawerVisible = ref(false)
const listPageState = useCustomerHub(props.kind)
const {
  loading, list, total, page, pageSize, searchForm, empty, errorGuidance, staleGuidance,
  fetchList, handleSearch, handlePageChange, handleSizeChange,
  detail, detailLoading, detailError, timeline, timelineTotal, timelineLoading, timelineError, currentCustomerId, loadDetail, loadTimeline,
  mutatingId, requeueJob,
} = listPageState
const hasFilterControls = computed(() => ['customers', 'acquisition', 'research'].includes(props.kind))
const hasActiveFilters = computed(() => Object.values(searchForm).some(value => String(value ?? '').trim()))
function handleReset() {
  for (const key of Object.keys(searchForm)) searchForm[key] = ''
  handleSearch()
}

const jobPolling = createSearchJobPollingController({
  shouldPoll: () => props.kind === 'acquisition' && shouldPollSearchJobs(list.value),
  refresh: fetchList,
})
watch(list, jobPolling.sync, { immediate: true })
onBeforeUnmount(jobPolling.dispose)

const rowKey = row => row.job_id || row.research_task_id || row.opportunity_id || row.action_id || row.customer_id
const statusLabel = status => ({ running: '执行中', failed: '失败', open: '进行中' }[status] || operationStatusLabel(status))
const tagType = status => ({ completed: 'success', failed: 'danger', running: 'warning', open: 'warning', dismissed: 'info' }[status] || 'info')

async function openCustomer(customerId) {
  drawerVisible.value = true
  await loadDetail(customerId)
}

async function retryJob(row) {
  await requeueJob(row.job_id)
  msgSuccess('重新入队')
}
defineExpose({ refresh: listPageState.refreshUpdate, refreshCreate: listPageState.refreshCreate })
</script>

<style scoped>
.hub-page { min-width: 0; isolation: isolate; position: relative; display: grid; align-content: start; gap: 16px; min-height: calc(100vh - 148px); color: var(--text-primary); }
.hub-aurora { inset: 0 -28px -24px; }
.hub-header,.state-alert,.hub-table { position: relative; z-index: 1; }
.hub-header { display: flex; justify-content: space-between; align-items: end; gap: 24px; padding: 8px 4px 0; }
.hub-kicker { color: var(--color-primary-text); font-size: 11px; font-weight: 700; letter-spacing: .14em; }
h1 { margin: 4px 0; font-size: 17px; }
.hub-header p { margin: 0; color: var(--text-secondary); }
.header-context { min-width: 100px; text-align: right; }
.header-context strong { display: block; font-size: 28px; } .header-context span { color: var(--text-muted); font-size: 12px; }
.hub-toolbar { display: flex; align-items: center; gap: 8px; padding: 12px; border-bottom: 1px solid var(--border-color); background: var(--toolbar-bg); }
.hub-toolbar :deep(.el-input), .hub-toolbar :deep(.el-select) { max-width: 360px; }
.toolbar-note { flex: 1; color: var(--text-secondary); font-size: 13px; }
.hub-toolbar > :first-child { flex: 1; }
.state-alert { margin: 0; }
.hub-table { overflow: hidden; padding: 0; }
.customer-link { font: inherit; max-width: 100%; overflow: hidden; display: grid; gap: 4px; min-height: 44px; padding: 4px 0; border: 0; background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; }
.customer-link:hover strong, .customer-link:focus-visible strong { color: var(--color-primary-text); text-decoration: underline; }
.customer-link:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.customer-link strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.customer-link span { color: var(--text-muted); font-size: 12px; }
.customer-link.compact { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-primary-text); }
.danger { color: var(--color-danger-text); }
.el-pagination { justify-content: flex-end; padding: 12px 16px; }
@media (max-width: 768px) { .hub-header { align-items: start; } .header-context { display: none; } .hub-toolbar { align-items: stretch; flex-direction: column; } .hub-toolbar :deep(.el-input), .hub-toolbar :deep(.el-select) { max-width: none; width: 100%; } .el-pagination { justify-content: flex-start; overflow-x: auto; } }
</style>
