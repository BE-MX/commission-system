<template>
  <DetailDrawer
    :model-value="modelValue"
    title="AI 优化"
    width="760px"
    :close-on-click-modal="!busy"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="handleClosed"
  >
    <div class="optimization-body">
      <el-alert
        title="AI 只生成优化提案；应用后会形成新草稿，仍需提交审批才能发布。"
        type="info"
        :closable="false"
        show-icon
      />

      <p class="history-bound">从最近 30 条优化记录中恢复当前任务</p>
      <ListPageStatus :paged="false" :error="historyResource.errorMessage.value && `任务历史：${historyResource.errorMessage.value}`" :loading="historyResource.loading.value" :has-data="historyResource.hasData.value" @retry="restoreLatestJob" />
      <ListPageStatus :paged="false" :error="jobResource.errorMessage.value" :loading="jobResource.loading.value" :has-data="!!job" @retry="poll" />
      <section v-if="!job" class="start-panel">
        <el-radio-group v-model="mode">
          <el-radio-button value="format">智能排版</el-radio-button>
          <el-radio-button value="enhance">知识增强</el-radio-button>
        </el-radio-group>
        <p class="mode-description">
          {{ mode === 'format'
            ? '只调整标题、层级、列表和序号，后端会校验原文字符和受保护结构完全不变。'
            : '结合获准知识库总结、补充和优化，并生成知识库、Skill、Agent 与工作流建议。' }}
        </p>
        <el-form label-position="top">
          <el-form-item label="优化方案" required>
            <ListPageStatus :paged="false" :error="profilesResource.errorMessage.value" :loading="loadingProfiles" :has-data="profilesResource.hasData.value" @retry="loadProfiles" />
            <el-select :loading="loadingProfiles" v-model="profileId" placeholder="选择适用于当前知识库的方案">
              <el-option
                v-for="profile in profiles"
                :key="profile.id"
                :label="`${profile.name} · v${profile.config_version}`"
                :value="profile.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <el-empty v-if="profilesResource.isEmpty.value" description="当前知识库暂无已启用的 AI 优化方案" />
        <GlassButton variant="primary" :disabled="!profileId || dirty || readBlocked" :loading="starting" @click="start">
          开始优化
        </GlassButton>
        <small v-if="dirty" class="warning">请先保存当前草稿，再执行 AI 优化。</small>
      </section>

      <section v-else class="job-panel">
        <div class="job-status">
          <StatusBadge :type="statusMeta.type" effect="plain">{{ statusMeta.label }}</StatusBadge>
          <span>{{ job.mode === 'format' ? '智能排版' : '知识增强' }}</span>
          <span>基于修订 #{{ job.base_revision_id }}</span>
        </div>
        <el-progress v-if="active" :percentage="50" :indeterminate="true" :show-text="false" />
        <el-alert
          v-if="job.status === 'failed'"
          :title="job.error_message || 'AI 优化失败，请检查配置后重试'"
          type="error"
          :closable="false"
          show-icon
        />

        <template v-if="job.result">
          <div class="metrics">
            <article><span>优化前字符</span><strong>{{ job.comparison?.before_text_chars ?? '-' }}</strong></article>
            <article><span>优化后字符</span><strong>{{ job.comparison?.after_text_chars ?? '-' }}</strong></article>
            <article><span>核心观点</span><strong>{{ job.comparison?.core_point_count ?? 0 }}</strong></article>
            <article><span>来源引用</span><strong>{{ job.comparison?.citation_count ?? 0 }}</strong></article>
          </div>

          <el-tabs v-model="tab">
            <el-tab-pane label="优化结果" name="result">
              <div class="comparison-preview">
                <article>
                  <strong>优化前</strong>
                  <KnowledgeDocumentPreview :content="document.content_json" />
                </article>
                <article>
                  <strong>优化后 · {{ job.result.title }}</strong>
                  <KnowledgeDocumentPreview :content="job.result.content_json" />
                </article>
              </div>
            </el-tab-pane>
            <el-tab-pane label="核心观点" name="points">
              <el-empty v-if="!job.result.core_points?.length" description="智能排版模式不改写核心观点" />
              <article v-for="(point, index) in job.result.core_points || []" :key="index" class="evidence-card">
                <strong>{{ point.point }}</strong>
                <p>原文：{{ point.original_quote }}</p>
                <p>优化：{{ point.optimized_quote }}</p>
              </article>
            </el-tab-pane>
            <el-tab-pane label="引用来源" name="sources">
              <el-empty v-if="!job.sources?.length" description="本次未使用其他知识来源" />
              <article v-for="source in job.sources || []" :key="source.revision_id" class="source-card">
                <strong>{{ source.title }}</strong>
                <span>文档 #{{ source.document_id }} · 修订 #{{ source.revision_id }}</span>
              </article>
            </el-tab-pane>
            <el-tab-pane label="应用建议" name="advice">
              <div v-for="item in adviceSections" :key="item.key" class="advice-card">
                <strong>{{ item.label }}</strong>
                <ul><li v-for="(line, index) in item.items" :key="index">{{ line }}</li></ul>
                <GlassButton variant="link" @click="copyAdvice(item)">复制</GlassButton>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>

        <div class="dialog-footer">
          <GlassButton v-if="active" variant="ghost" @click="cancel">取消任务</GlassButton>
          <GlassButton v-if="job.status === 'failed' || job.status === 'cancelled'" variant="ghost" @click="reset">重新生成</GlassButton>
          <GlassButton v-if="job.status === 'completed'" variant="primary" :loading="applying" @click="apply">应用为新草稿</GlassButton>
          <GlassButton v-if="job.status === 'applied'" variant="ghost" @click="$emit('update:modelValue', false)">完成</GlassButton>
        </div>
      </section>
    </div>
  </DetailDrawer>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import KnowledgeDocumentPreview from './KnowledgeDocumentPreview.vue'
import {
  applyDocumentAiJob,
  cancelDocumentAiJob,
  createDocumentAiJob,
  getDocumentAiJob,
  listAiProfiles,
  listDocumentAiJobs,
} from '@/api/knowledge'

const props = defineProps({
  modelValue: Boolean,
  document: { type: Object, default: null },
  dirty: Boolean,
})
const emit = defineEmits(['update:modelValue', 'applied'])
const auth = useAuthStore()
const readOptions = signal => ({ signal, suppressToast: true, showLoading: false })
let scopeGeneration = 0
let jobGeneration = 0
const profilesResource = useAsyncResource(async (libraryId, { signal, isCurrent }) => {
  const items = (await listAiProfiles(libraryId, readOptions(signal))).data || []
  if (isCurrent() && !items.some(item => item.id === profileId.value)) profileId.value = items[0]?.id || null
  return items
}, { initialData: [] })
const historyResource = useAsyncResource(async ({ documentId, scope, jobVersion }, { signal, isCurrent }) => {
  const items = (await listDocumentAiJobs(documentId, readOptions(signal))).data || []
  if (isCurrent() && scope === scopeGeneration && jobVersion === jobGeneration && !job.value) {
    job.value = items.find(item => ['queued', 'running', 'completed'].includes(item.status)) || null
  }
  return items
}, { initialData: [] })
const jobResource = useAsyncResource(async ({ id, scope, jobVersion }, { signal, isCurrent }) => {
  const result = (await getDocumentAiJob(id, readOptions(signal))).data
  if (isCurrent() && scope === scopeGeneration && jobVersion === jobGeneration && job.value?.id === id) job.value = result
  return result
})
const readBlocked = computed(() => [profilesResource, historyResource].some(resource => resource.loading.value || resource.error.value || !resource.hasLoaded.value))
const mode = ref('format')
const profileId = ref(null)
const profiles = profilesResource.data
const job = ref(null)
const tab = ref('result')
const loadingProfiles = profilesResource.loading
const starting = ref(false)
const applying = ref(false)
let pollTimer = null

const active = computed(() => ['queued', 'running'].includes(job.value?.status))
const busy = computed(() => active.value || starting.value || applying.value)
const statusMeta = computed(() => ({
  queued: { label: '排队中', type: 'warning' },
  running: { label: '优化中', type: 'warning' },
  completed: { label: '待应用', type: 'success' },
  applied: { label: '已应用', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}[job.value?.status] || { label: job.value?.status || '-', type: 'info' }))

const adviceSections = computed(() => {
  const advice = job.value?.result?.application_advice || {}
  return [
    { key: 'knowledge', label: '可并入知识库', items: advice.knowledge || [] },
    { key: 'skill', label: '可生成 Skill', items: advice.skill || [] },
    { key: 'agent', label: '可搭建 Agent', items: advice.agent || [] },
    { key: 'workflow', label: '可搭建自动化工作流', items: advice.workflow || [] },
  ]
})

function loadProfiles() { return props.modelValue && props.document?.library_id ? profilesResource.load(props.document.library_id) : false }
async function restoreLatestJob() {
  if (!props.modelValue || !props.document?.id || job.value) return false
  const scope = scopeGeneration
  const success = await historyResource.load({ documentId: props.document.id, scope, jobVersion: jobGeneration })
  if (success && scope === scopeGeneration && active.value) schedulePoll()
  return success
}
function openDrawer() { return Promise.all([loadProfiles(), restoreLatestJob()]) }

async function start() {
  if (props.dirty) return msgError('请先保存草稿')
  if (readBlocked.value || !profileId.value || starting.value) return
  const scope = scopeGeneration, documentId = props.document.id
  jobGeneration++; historyResource.cancel(); jobResource.clear(); stopPolling()
  starting.value = true
  try {
    const response = await createDocumentAiJob(documentId, {
      mode: mode.value,
      profile_id: profileId.value,
      base_revision_id: props.document.revision_id,
      idempotency_key: crypto.randomUUID().replaceAll('-', ''),
    })
    if (scope !== scopeGeneration || !props.modelValue) return
    job.value = response.data
    schedulePoll()
  } finally { if (scope === scopeGeneration) starting.value = false }
}

async function poll() {
  if (!props.modelValue || !job.value?.id || !active.value) return false
  const scope = scopeGeneration, id = job.value.id
  const success = await jobResource.load({ id, scope, jobVersion: jobGeneration })
  if (scope === scopeGeneration && job.value?.id === id && active.value) schedulePoll()
  return success
}

function schedulePoll() {
  stopPolling()
  if (props.modelValue && active.value) pollTimer = window.setTimeout(poll, 1800)
}

function stopPolling() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = null
}

async function cancel() {
  const scope = scopeGeneration, id = job.value.id
  jobGeneration++; jobResource.clear(); stopPolling()
  try {
    const response = await cancelDocumentAiJob(id)
    if (scope !== scopeGeneration || job.value?.id !== id) return
    job.value = response.data
  } finally {
    if (scope === scopeGeneration && job.value?.id === id && active.value) schedulePoll()
  }
}

async function apply() {
  const scope = scopeGeneration, id = job.value.id
  jobGeneration++; jobResource.clear(); stopPolling()
  applying.value = true
  try {
    const result = (await applyDocumentAiJob(id)).data
    if (scope !== scopeGeneration || job.value?.id !== id) return
    job.value.status = 'applied'
    msgSuccess('AI 优化结果已应用为新草稿')
    emit('applied', result)
  } finally { if (scope === scopeGeneration) applying.value = false }
}

function reset() {
  jobGeneration++; historyResource.cancel(); jobResource.clear(); stopPolling()
  job.value = null
  tab.value = 'result'
}
function clearScope() {
  scopeGeneration++; jobGeneration++; stopPolling()
  for (const resource of [profilesResource, historyResource, jobResource]) resource.clear()
  profileId.value = null; job.value = null; tab.value = 'result'
  starting.value = false; applying.value = false
}
function handleClosed() { if (!props.modelValue) clearScope() }

async function copyAdvice(section) {
  try {
    await navigator.clipboard.writeText(`${section.label}\n${section.items.map(item => `- ${item}`).join('\n')}`)
    msgSuccess('已复制')
  } catch { msgError('复制失败，请手动选择文本') }
}

watch(() => [props.modelValue, props.document?.id, props.document?.library_id, JSON.stringify([auth.user?.id, auth.roles, auth.permissions])], () => { clearScope(); if (props.modelValue) void openDrawer() })
onMounted(() => { if (props.modelValue) void openDrawer() })
onBeforeUnmount(clearScope)
</script>

<style scoped>
.optimization-body, .start-panel, .job-panel { display: grid; gap: 16px; }
.mode-description, .warning { color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.warning { color: var(--color-warning-text); }
.job-status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 13px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.metrics article { display: grid; gap: 3px; padding: 12px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--toolbar-bg); }
.metrics span, .source-card span { color: var(--text-muted-blue); font-size: 12px; }
.metrics strong { color: var(--text-primary); font-size: 20px; }
.comparison-preview { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.comparison-preview article { display: grid; min-width: 0; gap: 8px; }
.evidence-card, .source-card, .advice-card { display: grid; gap: 7px; margin-bottom: 10px; padding: 12px; border: 1px solid var(--border-color); border-radius: 9px; }
.evidence-card p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.advice-card ul { margin: 0; padding-left: 20px; color: var(--text-secondary); line-height: 1.7; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 680px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .comparison-preview { grid-template-columns: 1fr; } }
</style>
