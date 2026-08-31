<template>
  <main class="hub-page">
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

    <section class="hub-toolbar" aria-label="列表筛选">
      <el-input
        v-if="kind === 'customers'"
        v-model="searchForm.keyword"
        clearable
        placeholder="按客户编号或名称搜索"
        aria-label="搜索客户"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-select v-else-if="kind === 'acquisition'" v-model="searchForm.status" clearable placeholder="全部任务状态" @change="handleSearch">
        <el-option v-for="status in ['pending', 'running', 'completed', 'failed']" :key="status" :label="statusLabel(status)" :value="status" />
      </el-select>
      <div v-else class="toolbar-note">按最近更新时间排序 · 权限范围由方舟统一控制</div>
      <el-button type="primary" :loading="loading" @click="handleSearch">重新加载</el-button>
    </section>

    <el-alert v-if="errorGuidance" type="error" :title="errorGuidance" show-icon :closable="false" class="state-alert" />
    <el-alert v-if="staleGuidance" type="warning" :title="staleGuidance" show-icon :closable="false" class="state-alert" />

    <section class="hub-table" :aria-busy="loading">
      <el-table v-if="!empty || loading" v-loading="loading" :data="list" border class="list-table" :row-key="rowKey">
        <template v-if="kind === 'customers'">
          <el-table-column label="客户" min-width="220">
            <template #default="{ row }">
              <button class="customer-link" type="button" @click="openCustomer(row.customer_id)">
                <strong>{{ row.display_name || row.canonical_company_name || `临时客户 #${row.customer_id}` }}</strong>
                <span>{{ row.customer_code || `ID ${row.customer_id}` }}</span>
              </button>
            </template>
          </el-table-column>
          <el-table-column label="身份" min-width="116"><template #default="{ row }"><el-tag :type="row.identity_status === 'verified' ? 'success' : 'warning'" size="small">{{ row.identity_status || 'provisional' }}</el-tag></template></el-table-column>
          <el-table-column prop="primary_industry" label="行业" min-width="130"><template #default="{ row }">{{ row.primary_industry || '待补充' }}</template></el-table-column>
          <el-table-column prop="relationship_stage" label="关系阶段" min-width="120" />
          <el-table-column label="归属" min-width="118"><template #default="{ row }">{{ row.is_public_pool ? '公海' : '已分配' }}</template></el-table-column>
          <el-table-column label="完整度" min-width="105"><template #default="{ row }">{{ row.profile_completeness }}%</template></el-table-column>
        </template>

        <template v-else-if="kind === 'acquisition'">
          <el-table-column prop="name" label="任务" min-width="220" />
          <el-table-column label="状态" min-width="110"><template #default="{ row }"><el-tag :type="tagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="目标 / 结果" min-width="130"><template #default="{ row }">{{ row.target_count ?? 0 }} / {{ row.result_count ?? 0 }}</template></el-table-column>
          <el-table-column label="归档客户" min-width="110"><template #default="{ row }">{{ row.created_customer_count ?? 0 }}</template></el-table-column>
          <el-table-column prop="policy_version" label="策略版本" min-width="130" />
          <el-table-column label="反馈" min-width="190"><template #default="{ row }"><span :class="{ danger: row.error_message }">{{ row.error_message || `已去重 ${row.deduplicated_count ?? 0} 条` }}</span></template></el-table-column>
          <el-table-column label="操作" min-width="110" fixed="right"><template #default="{ row }"><el-button v-any-permission="['sales_automation:write', 'sales_automation:admin']" link type="primary" :loading="mutatingId === row.job_id" :disabled="!['failed', 'completed'].includes(row.status)" @click="retryJob(row)">重新入队</el-button></template></el-table-column>
        </template>

        <template v-else-if="kind === 'research'">
          <el-table-column label="客户" min-width="130"><template #default="{ row }"><button class="customer-link compact" type="button" @click="openCustomer(row.customer_id)">#{{ row.customer_id }}</button></template></el-table-column>
          <el-table-column prop="task_type" label="背调类型" min-width="150" />
          <el-table-column prop="tier" label="层级" min-width="90" />
          <el-table-column label="执行状态" min-width="110"><template #default="{ row }"><el-tag :type="tagType(row.task_status)" size="small">{{ statusLabel(row.task_status) }}</el-tag></template></el-table-column>
          <el-table-column prop="result_review_status" label="结果复核" min-width="120" />
          <el-table-column prop="data_classification" label="数据级别" min-width="150" />
          <el-table-column label="复核" min-width="160" fixed="right"><template #default="{ row }"><el-button v-permission="'sales_automation:admin'" link type="success" @click="$emit('review-task', row, 'accepted')">通过复核</el-button><el-button v-permission="'sales_automation:admin'" link type="warning" @click="$emit('review-task', row, 'revision_requested')">要求修订</el-button></template></el-table-column>
        </template>

        <template v-else-if="kind === 'opportunities'">
          <el-table-column prop="title" label="机会" min-width="240" />
          <el-table-column label="客户" min-width="120"><template #default="{ row }"><button class="customer-link compact" type="button" @click="openCustomer(row.customer_id)">#{{ row.customer_id }}</button></template></el-table-column>
          <el-table-column label="状态" min-width="110"><template #default="{ row }"><el-tag :type="tagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column prop="priority_level" label="优先级" min-width="100" />
          <el-table-column prop="owner_user_id" label="负责人" min-width="100" />
          <el-table-column prop="due_at" label="截止时间" min-width="170" />
        </template>

        <template v-else>
          <el-table-column prop="action_type" label="建议动作" min-width="200" />
          <el-table-column label="客户" min-width="120"><template #default="{ row }"><button class="customer-link compact" type="button" @click="openCustomer(row.customer_id)">#{{ row.customer_id }}</button></template></el-table-column>
          <el-table-column label="状态" min-width="105"><template #default="{ row }"><el-tag :type="tagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column prop="priority" label="优先级" min-width="100" />
          <el-table-column prop="due_at" label="建议完成时间" min-width="170" />
          <el-table-column label="操作" min-width="110" fixed="right"><template #default="{ row }"><el-button v-any-permission="['customer_radar:write', 'customer:admin']" link type="primary" :loading="mutatingId === row.action_id" :disabled="row.status === 'completed'" @click="complete(row)">已跟进</el-button></template></el-table-column>
        </template>

        <el-table-column prop="updated_at" label="最近更新" min-width="176" />
      </el-table>
      <el-empty v-else :description="config.emptyText" />
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </section>

    <CustomerDetailDrawer
      v-model="drawerVisible"
      :customer="detail"
      :loading="detailLoading"
      :timeline="timeline"
      :timeline-loading="timelineLoading"
      :detail-error="detailError"
      :timeline-error="timelineError"
      :load-timeline="loadTimeline"
      :retry-detail="() => loadDetail(currentCustomerId)"
    />
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { msgSuccess } from '@/utils/feedback'
import CustomerDetailDrawer from './CustomerDetailDrawer.vue'
import { useCustomerHub } from './composables/useCustomerHub'

const props = defineProps({ kind: { type: String, required: true } })
defineEmits(['review-task'])
const CONFIG = {
  customers: { title: '客户档案', description: '方舟唯一客户主档：先识别主体，再组织证据与经营动作。', countLabel: '可见客户', emptyText: '暂无可见客户；无主负责人客户会进入公海。' },
  acquisition: { title: '获客任务', description: '追踪搜索任务、策略版本与进入方舟主档的结果。', countLabel: '搜索任务', emptyText: '暂无搜索任务。' },
  research: { title: '背调中心', description: '查看客户证据采集进度与人工复核状态。', countLabel: '背调任务', emptyText: '暂无待处理背调任务。' },
  opportunities: { title: '客户机会', description: '以 customer_id 串联机会、负责人和截止时间。', countLabel: '经营机会', emptyText: '当前没有可见客户机会。' },
  radar: { title: '经营雷达', description: '把高优先级信号转成清晰、可反馈的下一步行动。', countLabel: '建议动作', emptyText: '当前没有待处理经营动作。' },
}
const config = CONFIG[props.kind]
const drawerVisible = ref(false)
const {
  loading, list, total, page, pageSize, searchForm, empty, errorGuidance, staleGuidance,
  handleSearch, handlePageChange, handleSizeChange,
  detail, detailLoading, detailError, timeline, timelineLoading, timelineError, currentCustomerId, loadDetail, loadTimeline,
  mutatingId, requeueJob, completeAction,
} = useCustomerHub(props.kind)

const rowKey = row => row.job_id || row.research_task_id || row.opportunity_id || row.action_id || row.customer_id
const statusLabel = status => ({ pending: '待处理', running: '执行中', completed: '已完成', failed: '失败', open: '进行中', dismissed: '已忽略', snoozed: '已延后' }[status] || status || '未知')
const tagType = status => ({ completed: 'success', failed: 'danger', running: 'warning', open: 'warning', dismissed: 'info' }[status] || 'info')

async function openCustomer(customerId) {
  drawerVisible.value = true
  await loadDetail(customerId)
}

async function complete(row) {
  await completeAction(row.action_id)
  msgSuccess('更新经营动作')
}

async function retryJob(row) {
  await requeueJob(row.job_id)
  msgSuccess('重新入队')
}
</script>

<style scoped>
.hub-page { display: grid; gap: 14px; color: var(--text-primary); }
.hub-header { display: flex; justify-content: space-between; align-items: end; gap: 24px; padding: 18px 20px; border-left: 4px solid var(--color-primary); background: var(--card-bg); box-shadow: var(--card-shadow); }
.hub-kicker { color: var(--color-primary); font-size: 11px; font-weight: 700; letter-spacing: .14em; }
h1 { margin: 4px 0 5px; font-size: 24px; letter-spacing: -.02em; }
.hub-header p { margin: 0; color: var(--text-secondary); }
.header-context { min-width: 100px; text-align: right; }
.header-context strong { display: block; font-size: 28px; } .header-context span { color: var(--text-muted); font-size: 12px; }
.hub-toolbar { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--toolbar-bg); }
.hub-toolbar :deep(.el-input), .hub-toolbar :deep(.el-select) { max-width: 360px; }
.toolbar-note { flex: 1; color: var(--text-secondary); font-size: 13px; }
.hub-toolbar > :first-child { flex: 1; }
.state-alert { margin: 0; }
.hub-table { padding: 12px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); box-shadow: var(--card-shadow); }
.hub-table :deep(.el-table__header th) { background: var(--toolbar-bg); color: var(--text-secondary); }
.customer-link { display: grid; gap: 3px; padding: 0; border: 0; background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; }
.customer-link:hover strong, .customer-link:focus-visible strong { color: var(--color-primary); text-decoration: underline; }
.customer-link:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.customer-link span { color: var(--text-muted); font-size: 12px; }
.customer-link.compact { display: inline; color: var(--color-primary); }
.danger { color: var(--color-danger-text); }
.el-pagination { justify-content: flex-end; margin-top: 14px; }
@media (max-width: 760px) { .hub-header { align-items: start; } .header-context { display: none; } .hub-toolbar { align-items: stretch; flex-direction: column; } .hub-toolbar :deep(.el-input), .hub-toolbar :deep(.el-select) { max-width: none; width: 100%; } }
</style>
