<template>
  <div class="task-page">
    <div class="task-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="page-header">
      <div>
        <h1>AI Agent 任务中心</h1>
        <p>统一查看 DSH 等受控运行时的任务、过程、成本、证据与人工决策。</p>
      </div>
      <div class="runtime-state">
        <el-tag :type="config?.enabled ? 'success' : 'info'" effect="plain">
          控制面 {{ config?.enabled ? '已启用' : '未启用' }}
        </el-tag>
        <el-tag :type="config?.dsh_enabled ? 'success' : 'info'" effect="plain">
          DSH {{ config?.dsh_enabled ? '已启用' : '未启用' }}
        </el-tag>
      </div>
    </header>

    <section v-if="canAdmin" class="evaluation-panel">
      <div class="evaluation-head">
        <div>
          <h2>业务灰度验收</h2>
          <p>30 个标准问题、200 张复购卡和 50 组同输入 Shadow 对照全部达标后，才进入人工晋级评审。</p>
        </div>
        <div class="evaluation-actions">
          <el-tag v-if="caseCatalog" type="info" effect="plain">
            Profile v{{ caseCatalog.profile_version }} · {{ caseCatalog.model || '模型未配置' }} · {{ caseCatalog.cohort_id?.split(':').at(-1) }}
          </el-tag>
          <el-tag :type="readiness?.business_validation_complete ? 'success' : 'warning'" effect="plain">
            {{ readiness?.business_validation_complete ? '已满足晋级门槛' : '保持 Shadow' }}
          </el-tag>
          <GlassButton
            v-permission="'agent_runtime:admin'" variant="secondary" left-icon="DataAnalysis"
            :loading="evaluationLoading" @click="openEvaluation"
          >执行标准评测</GlassButton>
        </div>
      </div>
      <el-alert v-if="evaluationError" :title="evaluationError" type="warning" show-icon :closable="false" />
      <div v-else class="evaluation-grid">
        <div class="evaluation-metric">
          <div><span>副驾驶标准题</span><strong>{{ caseCatalog?.completed_cases || 0 }}/{{ caseCatalog?.total_cases || 30 }}</strong></div>
          <el-progress :percentage="evaluationProgress(caseCatalog?.completed_cases, caseCatalog?.total_cases || 30)" :show-text="false" />
          <small>可直接使用率 {{ percent(readiness?.copilot?.direct_use_rate) }} · 证据绑定率 {{ percent(readiness?.copilot?.evidence_binding_rate) }}</small>
        </div>
        <div class="evaluation-metric">
          <div><span>复购行动卡</span><strong>{{ readiness?.repurchase?.cards || 0 }}/200</strong></div>
          <el-progress :percentage="evaluationProgress(readiness?.repurchase?.cards, 200)" :show-text="false" />
          <small>证据有效率 {{ percent(readiness?.repurchase?.evidence_valid_rate) }}</small>
        </div>
        <div class="evaluation-metric">
          <div><span>同输入 Shadow 对照</span><strong>{{ readiness?.sales_shadow?.same_input_completed_pairs || 0 }}/50</strong></div>
          <el-progress :percentage="evaluationProgress(readiness?.sales_shadow?.same_input_completed_pairs, 50)" :show-text="false" />
          <small>按不同 SearchJob 计数，不因重复 Run 虚增</small>
        </div>
      </div>
    </section>

    <el-row :gutter="12" class="toolbar">
      <el-col :xs="24" :sm="7" :md="5">
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 100%" @change="search">
          <el-option v-for="(meta, key) in STATUS_META" :key="key" :label="meta.label" :value="key" />
        </el-select>
      </el-col>
      <el-col :xs="24" :sm="7" :md="5">
        <el-select v-model="filters.runtime" placeholder="全部运行时" clearable style="width: 100%" @change="search">
          <el-option label="DSH" value="dsh" />
          <el-option label="OpenClaw" value="openclaw" />
          <el-option label="方舟原生" value="native" />
        </el-select>
      </el-col>
      <el-col :xs="24" :sm="10" :md="14" class="toolbar-actions">
        <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="fetchTasks">刷新</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card task-panel">
      <el-table :data="tasks" v-loading="loading" border class="list-table" style="width: 100%" empty-text="暂无 Agent 任务">
        <el-table-column label="任务" min-width="250" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="task-title">{{ taskTitle(row) }}</div>
            <div class="task-sub">#{{ row.id }} · {{ profileName(row.profile_id) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" effect="plain" size="small">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="运行时" min-width="95">
          <template #default="{ row }">{{ runtimeLabel(row.source_runtime) }}</template>
        </el-table-column>
        <el-table-column label="业务对象" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ businessRef(row) }}</template>
        </el-table-column>
        <el-table-column label="消耗" min-width="135">
          <template #default="{ row }">{{ row.steps_used }} 步 · {{ tokenTotal(row) }} Token</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="100" max-width="140" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openRun(row.id)">详情</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="evaluationDialog" title="客户与订单副驾驶 · 标准评测" width="min(980px, calc(100vw - 32px))">
      <el-alert
        title="这是正式灰度样本。每题应选择具备相应数据的真实内部客户；完成后必须在任务详情提交有帮助、无帮助或已修正反馈。"
        type="info" show-icon :closable="false" class="evaluation-notice"
      />
      <div class="evaluation-toolbar">
        <el-select
          v-model="selectedCustomerId" filterable remote clearable placeholder="搜索并选择评测客户"
          :remote-method="searchCustomers" :loading="customerLoading" style="min-width: 320px"
        >
          <el-option
            v-for="customer in evaluationCustomers" :key="customer.id" :value="customer.id"
            :label="customerLabel(customer)"
          />
        </el-select>
        <el-select v-model="evaluationCategory" clearable placeholder="全部题型" style="width: 160px">
          <el-option v-for="category in evaluationCategories" :key="category" :label="category" :value="category" />
        </el-select>
      </div>
      <el-table :data="filteredEvaluationCases" border max-height="520" class="list-table" empty-text="暂无标准评测题">
        <el-table-column label="题目" min-width="300">
          <template #default="{ row }">
            <div class="case-title"><el-tag size="small" effect="plain">{{ row.case_id }}</el-tag><strong>{{ row.title }}</strong></div>
            <div class="case-question">{{ row.question }}</div>
          </template>
        </el-table-column>
        <el-table-column label="数据要求" min-width="190">
          <template #default="{ row }"><span class="case-requires">{{ row.requires.join(' · ') }}</span></template>
        </el-table-column>
        <el-table-column label="状态" min-width="105">
          <template #default="{ row }"><el-tag :type="evaluationCaseMeta(row).type" effect="plain" size="small">{{ evaluationCaseMeta(row).label }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" min-width="105" max-width="130" fixed="right">
          <template #default="{ row }">
            <GlassButton
              v-if="row.completed_run_id || (row.latest_run_id && !['failed', 'cancelled', 'ambiguous'].includes(row.latest_status))"
              variant="link" left-icon="View" @click="openRun(row.completed_run_id || row.latest_run_id)"
            >查看</GlassButton>
            <GlassButton
              v-else v-permission="'agent_runtime:admin'" variant="link" left-icon="CaretRight"
              :loading="startingCaseId === row.case_id" @click="startEvaluation(row)"
            >运行</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  getAgentEvaluationReadiness, getAgentProfiles, getAgentRuntimeConfig, getAgentTasks,
  getCopilotEvaluationCases, searchCopilotEvaluationCustomers, startCopilotEvaluationCase,
} from '@/api/agentRuntime'
import { useListPage } from '@/composables/useListPage'
import { useAuthStore } from '@/stores/auth'
import {
  PROFILE_LABELS, STATUS_META, evaluationCaseMeta, evaluationProgress, formatTime, statusMeta,
} from './agentRuntimeView'

const router = useRouter()
const auth = useAuthStore()
const config = ref(null)
const profiles = ref(new Map())
const readiness = ref(null)
const caseCatalog = ref(null)
const evaluationLoading = ref(false)
const evaluationError = ref('')
const evaluationDialog = ref(false)
const evaluationCategory = ref('')
const evaluationCustomers = ref([])
const selectedCustomerId = ref(null)
const customerLoading = ref(false)
const startingCaseId = ref(null)
const evaluationRequestKeys = new Map()
const canAdmin = computed(() => auth.hasPermission('agent_runtime:admin'))
const evaluationCategories = computed(() => [
  ...new Set((caseCatalog.value?.cases || []).map(item => item.category)),
])
const filteredEvaluationCases = computed(() => (
  (caseCatalog.value?.cases || []).filter(item => (
    !evaluationCategory.value || item.category === evaluationCategory.value
  ))
))
const {
  loading, list: tasks, total, page, pageSize, searchForm: filters,
  fetchList: fetchTasks, handleSearch: search, handlePageChange, handleSizeChange,
} = useListPage(async params => {
  const cleaned = Object.fromEntries(Object.entries(params).filter(([, value]) => value))
  const response = await getAgentTasks(cleaned)
  return response.data || {}
}, { searchForm: { status: '', runtime: '' } })

onMounted(async () => {
  const [configResponse, profileResponse] = await Promise.all([
    getAgentRuntimeConfig(), getAgentProfiles(),
  ])
  config.value = configResponse.data
  profiles.value = new Map((profileResponse.data || []).map(item => [item.id, item]))
  if (canAdmin.value) await loadEvaluation()
})

async function loadEvaluation() {
  evaluationLoading.value = true
  evaluationError.value = ''
  try {
    const [readinessResponse, casesResponse] = await Promise.all([
      getAgentEvaluationReadiness(), getCopilotEvaluationCases(),
    ])
    readiness.value = readinessResponse.data
    caseCatalog.value = casesResponse.data
  } catch {
    evaluationError.value = '暂时无法读取业务验收进度，任务列表不受影响。'
  } finally { evaluationLoading.value = false }
}

async function openEvaluation() {
  if (!caseCatalog.value) await loadEvaluation()
  evaluationDialog.value = true
  if (!evaluationCustomers.value.length) await searchCustomers('')
}

async function searchCustomers(keyword) {
  customerLoading.value = true
  try {
    const response = await searchCopilotEvaluationCustomers({ keyword: keyword || undefined, limit: 30 })
    evaluationCustomers.value = response.data || []
  } finally { customerLoading.value = false }
}

async function startEvaluation(item) {
  if (!selectedCustomerId.value) return ElMessage.warning('请先选择具备本题所需数据的客户')
  const customer = evaluationCustomers.value.find(row => row.id === selectedCustomerId.value)
  try {
    await ElMessageBox.confirm(
      `确认用“${customerLabel(customer)}”执行 ${item.case_id}「${item.title}」？该结果会进入正式 30 题验收统计。`,
      '启动标准评测',
      { type: 'warning', confirmButtonText: '启动评测', cancelButtonText: '取消' },
    )
  } catch { return }
  startingCaseId.value = item.case_id
  try {
    const requestKey = `${item.case_id}:${selectedCustomerId.value}`
    if (!evaluationRequestKeys.has(requestKey)) {
      evaluationRequestKeys.set(
        requestKey,
        globalThis.crypto?.randomUUID?.()
          || `evaluation-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      )
    }
    const response = await startCopilotEvaluationCase(item.case_id, {
      customer_profile_id: selectedCustomerId.value,
      idempotency_key: evaluationRequestKeys.get(requestKey),
    })
    evaluationRequestKeys.delete(requestKey)
    ElMessage.success('标准评测任务已创建')
    await loadEvaluation()
    openRun(response.data.id)
  } finally { startingCaseId.value = null }
}

function taskTitle(row) {
  return row.input?.question || `${PROFILE_LABELS[profiles.value.get(row.profile_id)?.profile_key] || 'Agent 任务'}`
}

function profileName(profileId) {
  const profile = profiles.value.get(profileId)
  return profile?.name || `Profile #${profileId}`
}

function businessRef(row) {
  return row.business_ref_type && row.business_ref_id
    ? `${row.business_ref_type} · ${row.business_ref_id}` : '-'
}

function runtimeLabel(runtime) {
  return { dsh: 'DSH', openclaw: 'OpenClaw', native: '方舟原生' }[runtime] || runtime || '-'
}

function tokenTotal(row) {
  return Number(row.prompt_tokens || 0) + Number(row.completion_tokens || 0)
}

function openRun(runId) {
  router.push({ name: 'AgentRunDetail', params: { runId } })
}

function customerLabel(customer) {
  if (!customer) return '未选择客户'
  const name = customer.customer_company || customer.customer_name || `客户 #${customer.id}`
  return customer.customer_region ? `${name} · ${customer.customer_region}` : name
}

const percent = value => `${Math.round(Number(value || 0) * 100)}%`
</script>

<style scoped>
.task-page { position: relative; }
.task-aurora { inset: -24px -28px; }
.page-header, .toolbar, .task-panel { position: relative; z-index: 1; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; }
.page-header h1 { margin: 0; font-size: 24px; }
.page-header p { margin: 6px 0 0; color: var(--text-secondary); }
.runtime-state, .toolbar-actions { display: flex; justify-content: flex-end; gap: 8px; }
.evaluation-panel { position: relative; z-index: 1; margin-bottom: 14px; padding: 16px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-highlight); }
.evaluation-head, .evaluation-actions, .evaluation-metric > div, .evaluation-toolbar, .case-title { display: flex; align-items: center; gap: 10px; }
.evaluation-head { justify-content: space-between; align-items: flex-start; }
.evaluation-head h2 { margin: 0; font-size: 18px; }
.evaluation-head p { margin: 5px 0 0; color: var(--text-secondary); }
.evaluation-actions { justify-content: flex-end; }
.evaluation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.evaluation-metric { padding: 13px; border-radius: 10px; background: var(--surface-subtle); }
.evaluation-metric > div { justify-content: space-between; margin-bottom: 9px; }
.evaluation-metric strong { font-size: 18px; }
.evaluation-metric small { display: block; margin-top: 8px; color: var(--text-secondary); }
.evaluation-notice { margin-bottom: 12px; }
.evaluation-toolbar { margin-bottom: 12px; flex-wrap: wrap; }
.case-title { align-items: flex-start; }
.case-question { margin-top: 6px; color: var(--text-secondary); line-height: 1.45; }
.case-requires { color: var(--text-secondary); font-size: 12px; }
.toolbar { margin-bottom: 14px; row-gap: 10px; }
.task-panel { border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.task-panel :deep(.el-table) { --el-table-bg-color: transparent; --el-table-tr-bg-color: transparent; --el-table-header-bg-color: rgba(255, 255, 255, 0.5); background: transparent; }
.task-title { color: var(--text-primary); font-weight: 700; }
.task-sub { margin-top: 4px; color: var(--text-secondary); font-size: 12px; }
.pager { padding: 14px; justify-content: flex-end; }
@media (max-width: 720px) { .page-header, .evaluation-head { flex-direction: column; } .runtime-state, .evaluation-actions { justify-content: flex-start; } .evaluation-grid { grid-template-columns: 1fr; } .evaluation-toolbar :deep(.el-select) { min-width: 100% !important; width: 100% !important; } }
</style>
