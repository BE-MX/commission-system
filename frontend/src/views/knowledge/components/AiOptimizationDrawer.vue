<template>
  <el-drawer
    :model-value="modelValue"
    title="AI 优化"
    size="min(720px, 94vw)"
    :close-on-click-modal="!busy"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="stopPolling"
  >
    <div class="optimization-body">
      <el-alert
        title="AI 只生成优化提案；应用后会形成新草稿，仍需提交审批才能发布。"
        type="info"
        :closable="false"
        show-icon
      />

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
            <el-select v-model="profileId" placeholder="选择适用于当前知识库的方案">
              <el-option
                v-for="profile in profiles"
                :key="profile.id"
                :label="`${profile.name} · v${profile.config_version}`"
                :value="profile.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <el-empty v-if="!profiles.length && !loadingProfiles" description="当前知识库暂无已启用的 AI 优化方案" />
        <GlassButton variant="primary" :disabled="!profileId || dirty" :loading="starting" @click="start">
          开始优化
        </GlassButton>
        <small v-if="dirty" class="warning">请先保存当前草稿，再执行 AI 优化。</small>
      </section>

      <section v-else class="job-panel">
        <div class="job-status">
          <el-tag :type="statusMeta.type" effect="plain">{{ statusMeta.label }}</el-tag>
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

        <div class="drawer-actions">
          <GlassButton v-if="active" variant="ghost" @click="cancel">取消任务</GlassButton>
          <GlassButton v-if="job.status === 'failed' || job.status === 'cancelled'" variant="ghost" @click="reset">重新生成</GlassButton>
          <GlassButton v-if="job.status === 'completed'" variant="primary" :loading="applying" @click="apply">应用为新草稿</GlassButton>
          <GlassButton v-if="job.status === 'applied'" variant="ghost" @click="$emit('update:modelValue', false)">完成</GlassButton>
        </div>
      </section>
    </div>
  </el-drawer>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
const mode = ref('format')
const profileId = ref(null)
const profiles = ref([])
const job = ref(null)
const tab = ref('result')
const loadingProfiles = ref(false)
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

async function loadProfiles() {
  if (!props.document?.library_id) return
  loadingProfiles.value = true
  try {
    profiles.value = (await listAiProfiles(props.document.library_id)).data
    if (!profiles.value.some(item => item.id === profileId.value)) profileId.value = profiles.value[0]?.id || null
  } finally { loadingProfiles.value = false }
}

async function restoreLatestJob() {
  if (!props.document?.id || job.value) return
  const jobs = (await listDocumentAiJobs(props.document.id)).data
  job.value = jobs.find(item => ['queued', 'running', 'completed'].includes(item.status)) || null
}

async function openDrawer() {
  await Promise.all([loadProfiles(), restoreLatestJob()])
  if (active.value) schedulePoll()
}

async function start() {
  if (props.dirty) return msgError('请先保存草稿')
  starting.value = true
  try {
    job.value = (await createDocumentAiJob(props.document.id, {
      mode: mode.value,
      profile_id: profileId.value,
      base_revision_id: props.document.revision_id,
      idempotency_key: crypto.randomUUID().replaceAll('-', ''),
    })).data
    schedulePoll()
  } finally { starting.value = false }
}

async function poll() {
  if (!job.value?.id || !active.value) return
  try {
    job.value = (await getDocumentAiJob(job.value.id)).data
  } finally {
    if (active.value) schedulePoll()
  }
}

function schedulePoll() {
  stopPolling()
  pollTimer = window.setTimeout(poll, 1800)
}

function stopPolling() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = null
}

async function cancel() {
  job.value = (await cancelDocumentAiJob(job.value.id)).data
  stopPolling()
}

async function apply() {
  applying.value = true
  try {
    const result = (await applyDocumentAiJob(job.value.id)).data
    job.value.status = 'applied'
    msgSuccess('AI 优化结果已应用为新草稿')
    emit('applied', result)
  } finally { applying.value = false }
}

function reset() {
  stopPolling()
  job.value = null
  tab.value = 'result'
}

async function copyAdvice(section) {
  try {
    await navigator.clipboard.writeText(`${section.label}\n${section.items.map(item => `- ${item}`).join('\n')}`)
    msgSuccess('已复制')
  } catch { msgError('复制失败，请手动选择文本') }
}

watch(() => props.modelValue, open => { if (open) openDrawer() })
watch(() => props.document?.id, () => { stopPolling(); job.value = null })
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.optimization-body, .start-panel, .job-panel { display: grid; gap: 16px; }
.mode-description, .warning { color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.warning { color: var(--color-warning-text); }
.job-status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 13px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.metrics article { display: grid; gap: 3px; padding: 12px; border: 1px solid var(--border-color); border-radius: 9px; background: var(--surface-subtle); }
.metrics span, .source-card span { color: var(--text-muted-blue); font-size: 12px; }
.metrics strong { color: var(--text-primary); font-size: 20px; }
.comparison-preview { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.comparison-preview article { display: grid; min-width: 0; gap: 8px; }
.evidence-card, .source-card, .advice-card { display: grid; gap: 7px; margin-bottom: 10px; padding: 12px; border: 1px solid var(--border-color); border-radius: 9px; }
.evidence-card p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.advice-card ul { margin: 0; padding-left: 20px; color: var(--text-secondary); line-height: 1.7; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 680px) { .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .comparison-preview { grid-template-columns: 1fr; } }
</style>
