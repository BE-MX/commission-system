<template>
  <div class="sales-page">
    <header class="page-heading">
      <div>
        <h1>搜索任务</h1>
        <p>提交目标后等待已配置的 Codex/OpenClaw Agent 领取。Agent 真正开始工作后才显示“执行中”。</p>
      </div>
      <GlassButton
        v-any-permission="['sales_automation:write', 'sales_automation:admin']"
        variant="primary"
        left-icon="Plus"
        @click="dialogVisible = true"
      >新建搜索任务</GlassButton>
    </header>

    <div class="toolbar">
      <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 160px" @change="search">
        <el-option v-for="item in STATUS_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="fetchJobs">刷新</GlassButton>
      <span class="toolbar-spacer" />
      <span v-if="activeCount" class="muted">{{ activeCount }} 个任务等待或执行中，页面每 10 秒自动刷新</span>
    </div>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="jobs" border class="list-table">
        <el-table-column prop="name" label="任务" min-width="190" show-overflow-tooltip />
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }"><el-tag :type="statusMeta(row.status).type" effect="light">{{ statusMeta(row.status).label }}</el-tag></template>
        </el-table-column>
        <el-table-column label="目标 / 已发现" min-width="130">
          <template #default="{ row }">{{ row.target_count }} / {{ row.result_count }}</template>
        </el-table-column>
        <el-table-column prop="created_count" label="新客户" min-width="90" />
        <el-table-column prop="deduplicated_count" label="已去重" min-width="90" />
        <el-table-column prop="attempt_count" label="执行次数" min-width="90" />
        <el-table-column label="创建时间" min-width="155">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="结果" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.error_message" class="error-text">{{ row.error_message }}</span>
            <span v-else class="muted">{{ resultText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <GlassButton
              v-if="row.status === 'failed'"
              v-any-permission="['sales_automation:write', 'sales_automation:admin']"
              variant="link"
              left-icon="Refresh"
              :loading="startingId === row.id"
              @click="requeue(row)"
            >重新排队</GlassButton>
            <span v-else class="muted">{{ row.status === 'pending' ? '等待领取' : (row.status === 'running' ? 'Agent 执行中' : '已结束') }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </section>

    <el-dialog v-model="dialogVisible" title="新建搜索任务" width="min(560px, calc(100vw - 32px))" destroy-on-close @closed="resetDraft">
      <el-form label-position="top">
        <el-form-item label="任务名称" required>
          <el-input v-model="draft.name" maxlength="255" placeholder="例如：美国假发零售商 8 月第一批" />
        </el-form-item>
        <el-form-item label="目标公司数量">
          <el-input-number v-model="draft.target_count" :min="1" :max="500" controls-position="right" />
        </el-form-item>
        <el-form-item label="补充关键词（可选）">
          <el-select v-model="draft.keywords" multiple filterable allow-create default-first-option style="width: 100%" placeholder="不填时直接使用获客模型">
            <el-option v-for="item in draft.keywords" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <p class="dialog-hint">国家、行业和排除条件自动取自获客模型。创建后立即开放给 Agent，不需要保持页面打开。</p>
      </el-form>
      <template #footer>
        <GlassButton variant="secondary" @click="closeCreate">取消</GlassButton>
        <GlassButton variant="primary" left-icon="Plus" :loading="creating" @click="createJob">创建任务</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { createSearchJob, getSearchJobs, requeueSearchJob } from '@/api/salesAutomation'
import { useListPage } from '@/composables/useListPage'
import { msgError, msgSuccess } from '@/utils/feedback'

const STATUS_OPTIONS = [
  { value: 'pending', label: '等待 Agent', type: 'info' },
  { value: 'running', label: '执行中', type: 'warning' },
  { value: 'completed', label: '已完成', type: 'success' },
  { value: 'failed', label: '失败', type: 'danger' },
]
const statusMeta = value => STATUS_OPTIONS.find(item => item.value === value) || { label: value || '-', type: 'info' }
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
const resultText = row => row.status === 'completed' ? `新增 ${row.created_count}，去重 ${row.deduplicated_count}` : '等待结果'

const {
  loading, list: jobs, total, page, pageSize, searchForm: filters,
  fetchList: fetchJobs, handleSearch: search, handlePageChange, handleSizeChange,
} = useListPage(async params => {
  const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== ''))
  const res = await getSearchJobs(clean)
  return res.data || {}
}, { searchForm: { status: '' } })

const activeCount = computed(() => jobs.value.filter(item => ['pending', 'running'].includes(item.status)).length)
let pollTimer = null
let disposed = false
function schedulePoll() {
  if (disposed) return
  pollTimer = setTimeout(async () => {
    try { await fetchJobs() } finally { schedulePoll() }
  }, 10000)
}
onMounted(schedulePoll)
onBeforeUnmount(() => {
  disposed = true
  if (pollTimer) clearTimeout(pollTimer)
})

const dialogVisible = ref(false)
const creating = ref(false)
const startingId = ref(null)
const draftRequestKey = ref('')
const freshDraft = () => ({ name: '', target_count: 20, keywords: [] })
const draft = reactive(freshDraft())

async function requeue(row) {
  startingId.value = row.id
  try {
    await requeueSearchJob(row.id)
    msgSuccess('任务已重新排队，等待 Agent 领取')
    fetchJobs()
  } finally {
    startingId.value = null
  }
}

function closeCreate() {
  dialogVisible.value = false
}

function resetDraft() {
  draftRequestKey.value = ''
  Object.assign(draft, freshDraft())
}

async function createJob() {
  if (!draft.name.trim()) {
    msgError('请填写任务名称')
    return
  }
  creating.value = true
  try {
    if (!draftRequestKey.value) {
      draftRequestKey.value = globalThis.crypto?.randomUUID?.() || `job-${Date.now()}`
    }
    await createSearchJob({
      ...draft,
      idempotency_key: draftRequestKey.value,
    })
    Object.assign(draft, freshDraft())
    draftRequestKey.value = ''
    dialogVisible.value = false
    msgSuccess('任务已创建，等待 Agent 领取')
    fetchJobs()
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
@import './salesAutomation.css';
.error-text { color: var(--color-danger-text); font-size: 12px; }
.dialog-hint { margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.6; }
</style>
