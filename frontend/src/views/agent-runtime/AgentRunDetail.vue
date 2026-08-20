<template>
  <div class="run-page" v-loading="loading">
    <div class="run-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
    </div>

    <header class="run-header">
      <div class="title-row">
        <GlassButton variant="link" left-icon="ArrowLeft" @click="router.push('/agent-runtime/tasks')">返回任务中心</GlassButton>
        <el-tag v-if="run" :type="statusMeta(run.status).type" effect="plain">{{ statusMeta(run.status).label }}</el-tag>
      </div>
      <div v-if="run" class="run-heading">
        <div>
          <h1>{{ run.input?.question || `Agent 任务 #${run.id}` }}</h1>
          <p>#{{ run.id }} · {{ runtimeLabel(run.source_runtime) }} · 创建于 {{ formatTime(run.created_at) }}</p>
        </div>
        <GlassButton
          v-if="!isTerminal" v-permission="'agent_runtime:write'" variant="secondary"
          left-icon="Close" :loading="cancelling" @click="cancelRun"
        >取消任务</GlassButton>
      </div>
    </header>

    <el-alert v-if="run?.error_message" :title="run.error_code || '执行失败'" :description="run.error_message" type="error" show-icon :closable="false" />
    <el-alert v-if="run?.status === 'ambiguous'" title="任务结果状态不确定，请人工核查后再决定是否重试。" type="warning" show-icon :closable="false" />

    <section v-if="run" class="summary-grid">
      <div class="metric-card"><span>执行步数</span><strong>{{ run.steps_used }}</strong></div>
      <div class="metric-card"><span>输入 Token</span><strong>{{ number(run.prompt_tokens) }}</strong></div>
      <div class="metric-card"><span>输出 Token</span><strong>{{ number(run.completion_tokens) }}</strong></div>
      <div class="metric-card"><span>估算成本</span><strong>${{ run.cost_usd }}</strong></div>
    </section>

    <section v-if="artifacts.length" class="content-card">
      <div class="section-head"><div><h2>结构化成果</h2><p>校验通过后仍需人工接受，才会投影到正式业务数据。</p></div></div>
      <article v-for="artifact in artifacts" :key="artifact.id" class="artifact-card">
        <div class="artifact-head">
          <div><h3>{{ artifact.title || artifact.artifact_type }}</h3><span>成果 #{{ artifact.id }}</span></div>
          <div class="artifact-tags">
            <el-tag :type="artifact.validation_status === 'valid' ? 'success' : 'danger'" effect="plain" size="small">{{ artifact.validation_status }}</el-tag>
            <el-tag :type="decisionType(artifact.decision_status)" effect="plain" size="small">{{ decisionLabel(artifact.decision_status) }}</el-tag>
          </div>
        </div>
        <div v-for="(value, key) in artifact.content" :key="key" class="artifact-field">
          <div class="field-label">{{ artifactFieldLabel(key) }}</div>
          <ul v-if="Array.isArray(value)" class="field-list">
            <li v-for="(item, index) in value" :key="index"><pre>{{ formatPayload(item) }}</pre></li>
          </ul>
          <pre v-else class="field-value">{{ formatPayload(value) }}</pre>
        </div>
        <el-collapse v-if="artifact.evidence?.length" class="evidence-collapse">
          <el-collapse-item :title="`查看 ${artifact.evidence.length} 条证据`">
            <pre>{{ formatPayload(artifact.evidence) }}</pre>
          </el-collapse-item>
        </el-collapse>
        <div v-if="artifact.feedback_note" class="decision-note">决策说明：{{ artifact.feedback_note }}</div>
        <div v-if="artifact.decision_status === 'draft' && artifact.validation_status === 'valid'" class="artifact-actions">
          <GlassButton v-permission="'agent_runtime:write'" variant="primary" left-icon="Check" @click="decideArtifact(artifact, 'accept')">接受成果</GlassButton>
          <GlassButton v-permission="'agent_runtime:write'" variant="secondary" left-icon="Close" @click="decideArtifact(artifact, 'reject')">拒绝成果</GlassButton>
        </div>
      </article>
    </section>

    <section class="content-card">
      <div class="section-head">
        <div><h2>运行时间线</h2><p>仅展示可见的脱敏事件；原始提示词、工具参数与凭证不会进入页面。</p></div>
        <GlassButton variant="secondary" left-icon="Refresh" :loading="eventsLoading" @click="refreshAll">刷新</GlassButton>
      </div>
      <el-timeline v-if="events.length" class="event-timeline">
        <el-timeline-item v-for="event in events" :key="event.id" :timestamp="formatTime(event.created_at)" placement="top">
          <div class="event-card">
            <div class="event-title"><strong>#{{ event.sequence_no }} {{ event.event_type }}</strong><el-tag size="small" effect="plain">{{ event.actor_type }}</el-tag></div>
            <pre v-if="Object.keys(event.payload || {}).length">{{ formatPayload(event.payload) }}</pre>
          </div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else-if="!eventsLoading" description="暂无运行事件" />
    </section>

    <section v-if="run && isTerminal" class="content-card feedback-card">
      <div><h2>效果反馈</h2><p>反馈用于离线评测与 Profile 迭代，不会直接训练或自动改写业务事实。</p></div>
      <div class="feedback-actions">
        <GlassButton v-permission="'agent_runtime:write'" variant="secondary" @click="feedback('useful')">有帮助</GlassButton>
        <GlassButton v-permission="'agent_runtime:write'" variant="secondary" @click="feedback('not_useful')">无帮助</GlassButton>
        <GlassButton v-permission="'agent_runtime:write'" variant="secondary" @click="feedback('corrected')">已人工修正</GlassButton>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  acceptAgentArtifact, cancelAgentRun, getAgentEvents, getAgentRun,
  rejectAgentArtifact, submitAgentFeedback,
} from '@/api/agentRuntime'
import {
  TERMINAL_STATUSES, artifactFieldLabel, formatPayload, formatTime, statusMeta,
} from './agentRuntimeView'

const route = useRoute()
const router = useRouter()
const runId = Number(route.params.runId)
const loading = ref(true)
const eventsLoading = ref(false)
const cancelling = ref(false)
const run = ref(null)
const artifacts = ref([])
const events = ref([])
let pollTimer = null
const isTerminal = computed(() => TERMINAL_STATUSES.has(run.value?.status))

async function loadRun() {
  const response = await getAgentRun(runId)
  run.value = response.data?.run
  artifacts.value = response.data?.artifacts || []
}

async function loadEvents() {
  eventsLoading.value = true
  try {
    const response = await getAgentEvents(runId, { after_sequence: 0, limit: 500 })
    events.value = response.data || []
  } finally { eventsLoading.value = false }
}

async function refreshAll() {
  await Promise.all([loadRun(), loadEvents()])
  armPolling()
}

function armPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  if (!run.value || isTerminal.value) return
  pollTimer = setInterval(async () => {
    try { await Promise.all([loadRun(), loadEvents()]) } catch { /* 下一轮继续 */ }
    if (isTerminal.value && pollTimer) { clearInterval(pollTimer); pollTimer = null }
  }, 3000)
}

async function cancelRun() {
  try { await ElMessageBox.confirm('确认取消这个 Agent 任务？正在执行的任务会在安全检查点停止。', '取消任务', { type: 'warning' }) } catch { return }
  cancelling.value = true
  try { await cancelAgentRun(runId); ElMessage.success('取消请求已记录'); await refreshAll() } finally { cancelling.value = false }
}

async function decideArtifact(artifact, decision) {
  let note = null
  try {
    const result = await ElMessageBox.prompt('可填写判断依据，方便后续评测与复盘。', decision === 'accept' ? '接受成果' : '拒绝成果', {
      inputType: 'textarea', inputPlaceholder: '选填，最多 1000 字', inputValidator: value => !value || value.length <= 1000 || '最多 1000 字',
    })
    note = result.value || null
  } catch { return }
  if (decision === 'accept') await acceptAgentArtifact(artifact.id, note)
  else await rejectAgentArtifact(artifact.id, note)
  ElMessage.success(decision === 'accept' ? '成果已接受' : '成果已拒绝')
  await refreshAll()
}

async function feedback(rating) {
  let note = null
  try {
    const result = await ElMessageBox.prompt('这条反馈会进入 Agent 离线评测。', '提交效果反馈', {
      inputType: 'textarea', inputPlaceholder: '选填：哪里有帮助，或哪里需要改进？', inputValidator: value => !value || value.length <= 1000 || '最多 1000 字',
    })
    note = result.value || null
  } catch { return }
  await submitAgentFeedback(runId, { rating, note })
  ElMessage.success('反馈已记录')
  await loadRun()
}

const number = value => Number(value || 0).toLocaleString('zh-CN')
const runtimeLabel = value => ({ dsh: 'DSH', openclaw: 'OpenClaw', native: '方舟原生' }[value] || value || '-')
const decisionLabel = value => ({ draft: '待决策', accepted: '已接受', rejected: '已拒绝' }[value] || value)
const decisionType = value => ({ accepted: 'success', rejected: 'danger', draft: 'warning' }[value] || 'info')

onMounted(async () => {
  try { await refreshAll() } finally { loading.value = false }
})
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.run-page { position: relative; display: flex; flex-direction: column; gap: 14px; }
.run-aurora { inset: -24px -28px; }
.run-header, .run-page > section, .run-page > .el-alert { position: relative; z-index: 1; }
.title-row, .run-heading, .section-head, .artifact-head, .artifact-tags, .artifact-actions, .feedback-card, .feedback-actions { display: flex; align-items: center; gap: 10px; }
.run-header { display: flex; flex-direction: column; gap: 8px; }
.run-heading, .section-head, .artifact-head, .feedback-card { justify-content: space-between; }
.run-heading h1 { margin: 0; font-size: 24px; }
.run-heading p, .section-head p, .feedback-card p { margin: 5px 0 0; color: var(--text-secondary); }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-card, .content-card, .artifact-card, .event-card { border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-highlight); }
.metric-card { padding: 16px; display: flex; flex-direction: column; gap: 7px; }
.metric-card span, .artifact-head span { color: var(--text-secondary); font-size: 12px; }
.metric-card strong { font-size: 20px; }
.content-card { padding: 18px; }
.section-head { margin-bottom: 14px; }
.section-head h2, .feedback-card h2 { margin: 0; font-size: 18px; }
.artifact-card { padding: 16px; margin-top: 12px; background: var(--card-bg); }
.artifact-head { align-items: flex-start; }
.artifact-head h3 { margin: 0 0 4px; font-size: 16px; }
.artifact-field { margin-top: 14px; }
.field-label { margin-bottom: 6px; font-size: 13px; font-weight: 700; }
pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: inherit; line-height: 1.55; }
.field-value, .field-list, .event-card pre { padding: 10px; border-radius: 8px; background: var(--surface-subtle); }
.field-list { margin: 0; padding-left: 30px; }
.field-list li + li { margin-top: 6px; }
.evidence-collapse { margin-top: 12px; }
.decision-note { margin-top: 12px; color: var(--text-secondary); font-size: 13px; }
.artifact-actions { justify-content: flex-end; margin-top: 14px; }
.event-timeline { padding-top: 8px; }
.event-card { padding: 12px; background: var(--card-bg); }
.event-title { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
.feedback-card { align-items: flex-start; }
@media (max-width: 760px) { .summary-grid { grid-template-columns: repeat(2, 1fr); } .run-heading, .section-head, .feedback-card { align-items: flex-start; flex-direction: column; } }
</style>
