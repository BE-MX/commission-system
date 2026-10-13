<template>
  <el-dialog :model-value="modelValue" title="AI消息助手" width="760px" append-to-body :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <div class="assistant-body">
      <p class="assistant-caption">{{ account?.display_name || account?.phone_number || account?.account_uid }} · 仅分析平台已同步的消息，历史缺口会单独标明。</p>
      <el-form label-position="top" class="assistant-form">
        <el-form-item label="时间区间（北京时间 UTC+8，包含起止时间）" :error="rangeError">
          <div class="range-fields">
            <el-date-picker v-model="rangeStart" class="assistant-range" type="datetime" :show-now="false" value-format="YYYY-MM-DD HH:mm:ss" placeholder="开始时间" :disabled="submitting || isRunning || Boolean(unresolvedUid)" aria-label="北京时间开始时间" />
            <span class="range-separator">至</span>
            <el-date-picker v-model="rangeEnd" class="assistant-range" type="datetime" :show-now="false" value-format="YYYY-MM-DD HH:mm:ss" placeholder="结束时间" :disabled="submitting || isRunning || Boolean(unresolvedUid)" aria-label="北京时间结束时间" />
          </div>
        </el-form-item>
        <el-form-item label="聊天对象" class="assistant-scope">
          <el-radio-group v-model="scope" :disabled="submitting || isRunning || Boolean(unresolvedUid)" aria-label="分析范围">
            <el-radio-button value="all">整个账号</el-radio-button>
            <el-radio-button value="current" :disabled="!conversation">当前会话</el-radio-button>
          </el-radio-group>
          <span v-if="scope === 'current'" class="scope-caption">{{ unresolvedTarget || conversation?.contact_name || conversation?.contact_phone || conversation?.chat_id }}</span>
        </el-form-item>
      </el-form>
      <p v-if="options" class="assistant-caption">每次最多 {{ options.limits?.max_days || 31 }} 天、{{ options.limits?.max_messages || 2000 }} 条消息、{{ options.limits?.max_conversations || 25 }} 个聊天对象。</p>
      <el-alert v-if="options && !options.can_analyze" :title="blockedReason" type="warning" :closable="false" show-icon />
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <p v-if="unresolvedUid" class="assistant-caption">本次提交结果尚未确认，时间与聊天对象已锁定。重新提交会沿用同一请求编号与原参数。</p>
      <div class="assistant-history">
        <label for="whatsapp-assistant-history">历史报告</label>
        <el-select id="whatsapp-assistant-history" :model-value="selectedRunUid" placeholder="暂无报告，选择区间后开始分析" :disabled="submitting || Boolean(taskBusy)" aria-label="历史报告" @update:model-value="selectRun">
          <el-option v-for="item in runs" :key="item.run_uid" :value="item.run_uid" :label="`${formatTime(item.start_at)} 至 ${formatTime(item.end_at)} · ${status(item.status).label}`" />
        </el-select>
        <GlassButton v-if="selectedRunUid" variant="ghost" left-icon="Refresh" :disabled="loading || submitting || Boolean(taskBusy)" @click="refreshRun">刷新报告</GlassButton>
      </div>
      <div v-if="run" class="assistant-report" aria-live="polite">
        <div class="report-meta">
          <StatusBadge :type="status(run.status).type" effect="plain">{{ status(run.status).label }}</StatusBadge>
          <span>{{ run.message_count || 0 }} 条消息 · {{ run.conversation_count || 0 }} 个聊天对象</span>
          <span v-if="isRunning">已处理 {{ run.processed_conversations || 0 }} / {{ run.conversation_count || 0 }} · 可关闭，稍后从历史报告查看</span>
        </div>
        <p class="assistant-caption">报告区间：{{ formatTime(run.start_at) }} 至 {{ formatTime(run.end_at) }}（北京时间）</p>
        <el-alert v-if="run.status === 'stale'" :title="run.error_message || '授权、消息或知识来源已变化，此报告的结果已失效。请确认当前来源后重新分析。'" type="warning" :closable="false" show-icon />
        <el-alert v-else-if="run.status === 'failed'" :title="run.error_message || '分析失败，请检查配置与授权后重新分析。'" type="error" :closable="false" show-icon />
        <el-alert v-for="(warning, index) in run.warnings || []" :key="index" :title="warning" type="warning" :closable="false" />
        <template v-if="run.status === 'succeeded'">
          <el-empty v-if="!run.results?.length" description="该时间区间内没有可分析的已同步消息" :image-size="80" />
          <article v-for="result in run.results || []" :key="result.conversation_uid" class="conversation-result">
            <header class="result-title"><h3>{{ result.title || '未命名会话' }}</h3><StatusBadge v-if="result.is_group" effect="plain">群聊</StatusBadge><small>{{ result.message_count }} 条消息</small></header>
            <p class="coverage-caption">{{ historyLabel(result.coverage?.history_state) }}<template v-if="result.coverage?.gap_reason"> · {{ result.coverage.gap_reason }}</template></p>
            <h4>聊天摘要</h4>
            <p class="report-text">{{ result.summary }}</p>
            <template v-if="result.open_questions?.length"><h4>待确认事项</h4><ul><li v-for="(question, index) in result.open_questions" :key="index">{{ question }}</li></ul></template>
            <h4>跟进建议</h4>
            <p v-if="!result.follow_up_suggestions?.length" class="assistant-caption">暂无有依据的跟进建议</p>
            <ol v-else class="suggestion-list"><li v-for="(suggestion, index) in result.follow_up_suggestions" :key="index"><p class="report-text">{{ suggestion.text }}</p><small class="evidence-caption">{{ references(suggestion, result) }}</small></li></ol>
            <h4>待办清单 <small>仅保存在本助手报告内</small></h4>
            <p v-if="!result.tasks?.length" class="assistant-caption">暂无待办</p>
            <div v-for="task in result.tasks || []" :key="task.task_uid" class="report-task" :class="{ completed: task.completed }">
              <el-checkbox class="task-checkbox" :model-value="task.completed" :disabled="Boolean(taskBusy) || submitting" :aria-label="task.title" @update:model-value="setTaskCompleted(task, $event)"><span class="task-title">{{ task.title }}</span></el-checkbox>
              <div class="task-meta"><StatusBadge :type="priorityType(task.priority)" size="small" effect="plain">{{ task.priority }}</StatusBadge><span v-if="task.due_date">建议日期 {{ task.due_date }}</span><span v-if="taskBusy === task.task_uid">正在保存…</span></div>
              <p v-if="task.description" class="report-text">{{ task.description }}</p>
              <small class="evidence-caption">{{ references(task, result) }}</small>
            </div>
            <details v-if="result.knowledge_sources?.length" class="knowledge-sources"><summary>知识来源（{{ result.knowledge_sources.length }}）</summary><ul><li v-for="source in result.knowledge_sources" :key="source.source_id">{{ source.title }} · 版本 {{ source.version_no }}</li></ul></details>
          </article>
        </template>
      </div>
      <el-skeleton v-else-if="loading" :rows="3" animated />
      <el-empty v-else-if="!error && !unresolvedUid" description="选择时间区间，生成聊天摘要、跟进建议和清单" :image-size="80" />
    </div>
    <template #footer><div class="dialog-footer">
      <GlassButton variant="ghost" @click="emit('update:modelValue', false)">关闭</GlassButton>
      <template v-if="unresolvedUid">
        <GlassButton variant="ghost" :loading="submitting" :disabled="submitting" @click="lookupRequest">查询提交状态</GlassButton>
        <GlassButton v-if="canRetryRequest" variant="primary" :loading="submitting" :disabled="submitting || loading || !options?.can_analyze" @click="retryRequest">重新提交本次分析</GlassButton>
      </template>
      <GlassButton v-else variant="primary" :loading="submitting" :disabled="!canCreate" @click="createRun">{{ isRunning ? '正在分析' : '开始分析' }}</GlassButton>
    </div></template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { useWhatsAppAssistant, assistantStatuses } from '../composables/useWhatsAppAssistant'
import { formatBeijingDateTime } from '@/utils/datetime'
import { historyLabel } from '@/views/system/whatsappStatus'
const props = defineProps({ modelValue: Boolean, account: Object, conversation: Object, accessKey: String })
const emit = defineEmits(['update:modelValue'])
const { options, runs, run, range, scope, selectedRunUid, loading, submitting, error, unresolvedUid, unresolvedTarget, canRetryRequest,
  taskBusy, rangeError, isRunning, canCreate, selectRun, refreshRun, lookupRequest, createRun, retryRequest, setTaskCompleted } = useWhatsAppAssistant(props, () => emit('update:modelValue', false))
const rangeStart = computed({ get: () => range.value?.[0], set: value => { range.value = [value, range.value?.[1]] } })
const rangeEnd = computed({ get: () => range.value?.[1], set: value => { range.value = [range.value?.[0], value] } })
const blockedReason = computed(() => {
  if (options.value?.reason) return options.value.reason
  if (!options.value?.ai_allowed) return '账号尚未允许 AI 分析外发，请持有人在授权范围中开启。'
  if (!options.value?.preset_available) return 'AI消息助手尚未配置可用模型，请联系管理员配置。'
  return '当前账号暂不可分析'
})
const status = value => assistantStatuses[value] || { label: value || '未知状态', type: 'info' }
const priorityType = value => ({ P0: 'danger', P1: 'warning', P2: 'info', P3: 'info' }[value] || 'info')
const formatTime = value => formatBeijingDateTime(value, { seconds: false })
function references(item, result) {
  const messages = (item.message_uids || []).map((uid, index) => `消息 ${index + 1}（${String(uid).slice(-8)}）`)
  const knowledge = (item.knowledge_source_ids || []).map(id => result.knowledge_sources?.find(source => source.source_id === id))
    .filter(Boolean).map(source => `${source.title} · 版本 ${source.version_no}`)
  return [...messages, ...knowledge].join('；') || '未提供引用'
}
</script>

<style scoped>
.assistant-body { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; min-width: 0; }
.assistant-caption, .coverage-caption, .evidence-caption, .scope-caption { color: var(--text-secondary); font-size: 12px; line-height: 1.6; margin: 0; overflow-wrap: anywhere; }
.assistant-range { width: 100%; min-width: 0; }
.range-fields { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 10px; width: 100%; }
.range-separator { color: var(--text-secondary); }
.assistant-scope { margin-bottom: 0; }
.scope-caption { margin-left: 12px; }
.assistant-history { display: flex; align-items: center; gap: 10px; }
.assistant-history label { flex: none; font-size: 12px; color: var(--text-secondary); }
.assistant-history .el-select { flex: 1; min-width: 0; }
.assistant-report { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
.report-meta, .result-title, .task-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.report-meta, .task-meta, .result-title small { font-size: 12px; color: var(--text-secondary); }
.conversation-result { border: 1px solid var(--border-color); border-radius: 12px; background: var(--card-bg); padding: 18px; min-width: 0; }
.result-title h3 { font-size: 15px; margin: 0; color: var(--text-primary); overflow-wrap: anywhere; }
.conversation-result h4 { margin: 18px 0 8px; font-size: 13px; color: var(--text-primary); }
.conversation-result h4 small { font-weight: 400; color: var(--text-secondary); }
.coverage-caption { margin-top: 6px; }
.report-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; margin: 6px 0; }
.conversation-result ul, .suggestion-list { padding-left: 20px; margin: 6px 0; line-height: 1.7; overflow-wrap: anywhere; }
.suggestion-list li + li { margin-top: 12px; }
.report-task { padding: 12px 0; border-bottom: 1px solid var(--border-color); }
.task-checkbox { height: auto; align-items: flex-start; max-width: 100%; }
.task-title { display: inline-block; white-space: normal; overflow-wrap: anywhere; line-height: 1.5; }
.report-task.completed .task-title { text-decoration: line-through; color: var(--text-secondary); }
.task-meta { margin-top: 6px; }
.knowledge-sources { margin-top: 14px; font-size: 12px; color: var(--text-secondary); }
.knowledge-sources summary { cursor: pointer; }
.dialog-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
@media (max-width: 600px) {
  .range-fields { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .range-separator { text-align: center; font-size: 12px; }
  .assistant-history { flex-wrap: wrap; }
  .assistant-history label { width: 100%; }
  .conversation-result { padding: 12px; }
  .scope-caption { display: block; margin: 8px 0 0; }
}
</style>
