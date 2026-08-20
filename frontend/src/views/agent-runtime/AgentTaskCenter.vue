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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getAgentProfiles, getAgentRuntimeConfig, getAgentTasks } from '@/api/agentRuntime'
import { useListPage } from '@/composables/useListPage'
import { PROFILE_LABELS, STATUS_META, formatTime, statusMeta } from './agentRuntimeView'

const router = useRouter()
const config = ref(null)
const profiles = ref(new Map())
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
})

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
</script>

<style scoped>
.task-page { position: relative; }
.task-aurora { inset: -24px -28px; }
.page-header, .toolbar, .task-panel { position: relative; z-index: 1; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; }
.page-header h1 { margin: 0; font-size: 24px; }
.page-header p { margin: 6px 0 0; color: var(--text-secondary); }
.runtime-state, .toolbar-actions { display: flex; justify-content: flex-end; gap: 8px; }
.toolbar { margin-bottom: 14px; row-gap: 10px; }
.task-panel { border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight); }
.task-panel :deep(.el-table) { --el-table-bg-color: transparent; --el-table-tr-bg-color: transparent; --el-table-header-bg-color: rgba(255, 255, 255, 0.5); background: transparent; }
.task-title { color: var(--text-primary); font-weight: 700; }
.task-sub { margin-top: 4px; color: var(--text-secondary); font-size: 12px; }
.pager { padding: 14px; justify-content: flex-end; }
@media (max-width: 720px) { .page-header { flex-direction: column; } .runtime-state { justify-content: flex-start; } }
</style>
