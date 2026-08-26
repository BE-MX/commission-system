<template>
  <div class="ai-settings-page">
    <header class="page-header">
      <div>
        <h1>AI 优化配置</h1>
        <p>配置提示词、模型、允许访问的来源知识库及适用目标库。系统安全规则不能被业务提示词覆盖。</p>
      </div>
      <GlassButton v-permission="'knowledge_ai:admin'" variant="primary" left-icon="Plus" @click="openCreate">新建方案</GlassButton>
    </header>

    <section class="summary-grid">
      <article><span>优化方案</span><strong>{{ profiles.length }}</strong></article>
      <article><span>已启用</span><strong>{{ profiles.filter(item => item.is_enabled).length }}</strong></article>
      <article><span>可用模型</span><strong>{{ presets.length }}</strong></article>
      <article><span>知识库</span><strong>{{ libraries.length }}</strong></article>
    </section>

    <section class="table-card settings-panel">
      <el-table :data="profiles" class="list-table" border v-loading="loading">
        <el-table-column prop="name" label="方案名称" min-width="170" show-overflow-tooltip />
        <el-table-column prop="preset_name" label="AI Preset" min-width="170" show-overflow-tooltip />
        <el-table-column label="知识范围" min-width="180">
          <template #default="{ row }">来源 {{ row.source_library_ids.length }} 个 · 目标 {{ row.target_library_ids.length }} 个</template>
        </el-table-column>
        <el-table-column label="安全设置" min-width="190">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.allow_cross_library ? '允许跨库' : '仅同库' }}</el-tag>
            <el-tag size="small" effect="plain" :type="row.require_citations ? 'success' : 'info'">{{ row.require_citations ? '要求引用' : '引用可选' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="版本/状态" min-width="130">
          <template #default="{ row }">v{{ row.config_version }} · {{ row.is_enabled ? '启用' : '停用' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="240">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="Edit" @click="openEdit(row)">编辑</GlassButton>
            <GlassButton variant="link" left-icon="Search" @click="openTest(row)">测试</GlassButton>
            <GlassButton variant="link" left-icon="Tickets" @click="openLogs(row)">记录</GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="remove(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog" :title="form.id ? '编辑 AI 优化方案' : '新建 AI 优化方案'" width="min(860px, calc(100vw - 32px))">
      <el-form label-position="top" class="profile-form">
        <el-form-item label="方案名称" required><el-input v-model="form.name" maxlength="128" /></el-form-item>
        <el-form-item label="用途说明"><el-input v-model="form.description" maxlength="512" /></el-form-item>
        <el-form-item label="文本 AI Preset" required>
          <el-select v-model="form.preset_id" filterable>
            <el-option v-for="item in presets" :key="item.id" :value="item.id" :label="`${item.preset_name} · ${item.model || '-'} · ${item.provider_name}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="智能排版业务提示词">
          <el-input v-model="form.format_prompt" type="textarea" :rows="4" maxlength="10000" show-word-limit />
        </el-form-item>
        <el-form-item label="知识增强业务提示词">
          <el-input v-model="form.enhance_prompt" type="textarea" :rows="5" maxlength="10000" show-word-limit />
        </el-form-item>
        <el-form-item label="允许读取的来源知识库" required>
          <el-select v-model="form.source_library_ids" multiple filterable collapse-tags collapse-tags-tooltip>
            <el-option v-for="item in libraries" :key="item.id" :value="item.id" :label="item.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用目标知识库" required>
          <el-select v-model="form.target_library_ids" multiple filterable collapse-tags collapse-tags-tooltip>
            <el-option v-for="item in libraries" :key="item.id" :value="item.id" :label="item.name" />
          </el-select>
        </el-form-item>
        <div class="number-grid">
          <el-form-item label="检索文档数"><el-input-number v-model="form.retrieval_limit" :min="1" :max="20" /></el-form-item>
          <el-form-item label="上下文字符上限"><el-input-number v-model="form.context_char_limit" :min="1000" :max="100000" :step="1000" /></el-form-item>
          <el-form-item label="单文档字符上限"><el-input-number v-model="form.max_document_chars" :min="1000" :max="100000" :step="1000" /></el-form-item>
          <el-form-item label="每用户每日任务"><el-input-number v-model="form.daily_limit" :min="1" :max="1000" /></el-form-item>
          <el-form-item label="每用户并发任务"><el-input-number v-model="form.max_concurrent_per_user" :min="1" :max="10" /></el-form-item>
        </div>
        <div class="switch-grid">
          <label><el-switch v-model="form.allow_cross_library" />允许跨知识库综合</label>
          <label><el-switch v-model="form.require_citations" />新增事实必须有引用</label>
          <label><el-switch v-model="form.is_enabled" />启用方案</label>
        </div>
        <el-alert title="来源范围在运行时还会与执行者本人可读知识库取交集；配置本身不会给用户扩权。" type="warning" :closable="false" />
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" :disabled="saving" @click="dialog = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="save">保存</GlassButton>
      </template>
    </el-dialog>

    <el-dialog v-model="testDialog" :title="`测试 · ${testingProfile?.name || ''}`" width="min(720px, calc(100vw - 32px))">
      <el-form label-position="top">
        <el-form-item label="目标知识库" required>
          <el-select v-model="testForm.target_library_id">
            <el-option v-for="item in targetLibraries" :key="item.id" :value="item.id" :label="item.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="模拟文本" required><el-input v-model="testForm.sample_text" type="textarea" :rows="5" maxlength="4000" /></el-form-item>
      </el-form>
      <div class="test-actions">
        <GlassButton variant="secondary" :loading="testing" @click="runConnectionTest">连接测试</GlassButton>
        <GlassButton variant="primary" :loading="testing" @click="runRetrievalPreview">检索预览</GlassButton>
      </div>
      <el-alert v-if="testResult?.response" :title="testResult.response" type="success" :closable="false" />
      <div v-if="testResult?.items" class="preview-list">
        <article v-for="item in testResult.items" :key="item.revision_id"><strong>{{ item.title }}</strong><span>{{ item.excerpt }}</span></article>
        <el-empty v-if="!testResult.items.length" description="没有检索到当前账号可读的已发布来源" />
      </div>
    </el-dialog>

    <el-drawer v-model="logsDrawer" :title="`配置记录 · ${logsProfile?.name || ''}`" size="min(560px, 92vw)">
      <el-timeline>
        <el-timeline-item v-for="item in logs" :key="item.id" :timestamp="formatBeijingDateTime(item.created_at)">
          <strong>{{ { create: '创建', update: '更新', delete: '删除' }[item.action] || item.action }} · v{{ item.config_version }}</strong>
          <p>操作人 ID {{ item.actor_user_id }} · 来源 {{ item.detail?.source_library_ids?.length || 0 }} 个 · 目标 {{ item.detail?.target_library_ids?.length || 0 }} 个</p>
        </el-timeline-item>
      </el-timeline>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import {
  createAiProfile, deleteAiProfile, listAiLibraryCandidates, listAiPresetCandidates,
  listAiProfileLogs, listAiProfiles, previewAiRetrieval, testAiProfile, updateAiProfile,
} from '@/api/knowledge'
import { msgError, msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'

const profiles = ref([])
const presets = ref([])
const libraries = ref([])
const loading = ref(false)
const dialog = ref(false)
const saving = ref(false)
const testDialog = ref(false)
const testing = ref(false)
const testingProfile = ref(null)
const testResult = ref(null)
const logsDrawer = ref(false)
const logsProfile = ref(null)
const logs = ref([])

const emptyForm = () => ({
  id: null, name: '', description: '', preset_id: null, format_prompt: '', enhance_prompt: '',
  source_library_ids: [], target_library_ids: [], retrieval_limit: 5, context_char_limit: 30000,
  allow_cross_library: false, require_citations: true, max_document_chars: 30000,
  daily_limit: 20, max_concurrent_per_user: 2, is_enabled: true,
})
const form = reactive(emptyForm())
const testForm = reactive({ target_library_id: null, sample_text: '' })
const targetLibraries = computed(() => libraries.value.filter(item => testingProfile.value?.target_library_ids.includes(item.id)))

async function load() {
  loading.value = true
  try {
    const [profileResponse, presetResponse, libraryResponse] = await Promise.all([
      listAiProfiles(), listAiPresetCandidates(), listAiLibraryCandidates(),
    ])
    profiles.value = profileResponse.data
    presets.value = presetResponse.data
    libraries.value = libraryResponse.data
  } finally { loading.value = false }
}

function openCreate() { Object.assign(form, emptyForm()); dialog.value = true }
function openEdit(row) { Object.assign(form, emptyForm(), JSON.parse(JSON.stringify(row))); dialog.value = true }

async function save() {
  if (!form.name.trim() || !form.preset_id || !form.source_library_ids.length || !form.target_library_ids.length) return msgError('请填写名称、Preset、来源知识库和目标知识库')
  saving.value = true
  try {
    const payload = { ...form }
    delete payload.id
    delete payload.preset_name
    delete payload.config_version
    delete payload.created_at
    delete payload.updated_at
    if (form.id) await updateAiProfile(form.id, payload)
    else await createAiProfile(payload)
    dialog.value = false
    msgSuccess('保存')
    await load()
  } finally { saving.value = false }
}

async function remove(row) {
  try { await ElMessageBox.confirm(`删除方案“${row.name}”后，新任务不能再使用它。`, '删除 AI 优化方案', { type: 'warning' }) }
  catch { return }
  await deleteAiProfile(row.id)
  msgSuccess('删除')
  await load()
}

function openTest(row) {
  testingProfile.value = row
  testForm.target_library_id = row.target_library_ids[0] || null
  testForm.sample_text = ''
  testResult.value = null
  testDialog.value = true
}

async function runConnectionTest() {
  if (!testForm.target_library_id || !testForm.sample_text.trim()) return msgError('请选择目标库并填写模拟文本')
  testing.value = true
  try { testResult.value = (await testAiProfile(testingProfile.value.id, { ...testForm })).data }
  finally { testing.value = false }
}

async function runRetrievalPreview() {
  if (!testForm.target_library_id || !testForm.sample_text.trim()) return msgError('请选择目标库并填写模拟文本')
  testing.value = true
  try { testResult.value = { items: (await previewAiRetrieval(testingProfile.value.id, { ...testForm })).data } }
  finally { testing.value = false }
}

async function openLogs(row) {
  logsProfile.value = row
  logs.value = (await listAiProfileLogs(row.id)).data
  logsDrawer.value = true
}

onMounted(load)
</script>

<style scoped>
.ai-settings-page { display: grid; gap: 18px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 0; color: var(--text-primary); font-size: 24px; }
.page-header p { margin: 6px 0 0; color: var(--text-secondary); }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.summary-grid article { display: grid; gap: 4px; padding: 16px; border: 1px solid var(--border-color); border-radius: var(--dash-card-radius); background: var(--surface-card); }
.summary-grid span { color: var(--text-muted-blue); font-size: 12px; }
.summary-grid strong { color: var(--text-primary); font-size: 24px; }
.settings-panel { overflow: hidden; }
.profile-form :deep(.el-select), .profile-form :deep(.el-input-number), .test-actions + :deep(.el-alert) { width: 100%; }
.number-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.switch-grid { display: flex; flex-wrap: wrap; gap: 18px; margin-bottom: 16px; }
.switch-grid label { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); }
.test-actions { display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 14px; }
.preview-list { display: grid; gap: 8px; max-height: 320px; overflow: auto; }
.preview-list article { display: grid; gap: 4px; padding: 10px; border: 1px solid var(--border-color); border-radius: 8px; }
.preview-list span, :deep(.el-timeline-item p) { color: var(--text-secondary); font-size: 13px; }
@media (max-width: 900px) { .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .number-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 600px) { .page-header { flex-direction: column; } .number-grid { grid-template-columns: 1fr; } }
</style>
