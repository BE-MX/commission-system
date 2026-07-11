<template>
  <div class="script-page">
    <div class="rule-banner">品牌话术规范：禁用 便宜 / 划算 / 性价比 / 打折 / 薅羊毛（保存时后端强校验）</div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="14">
        <el-radio-group v-model="typeFilter">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="opener">开场</el-radio-button>
          <el-radio-button value="demo">演示</el-radio-button>
          <el-radio-button value="closer">逼单</el-radio-button>
          <el-radio-button value="faq">应对</el-radio-button>
        </el-radio-group>
      </el-col>
      <el-col :span="10" class="toolbar-right">
        <GlassButton v-permission="'expo:admin'" variant="ghost" left-icon="Download" :loading="seeding" @click="handleSeed">导入种子话术</GlassButton>
        <GlassButton v-permission="'expo:admin'" variant="primary" left-icon="Plus" @click="openCreate">新建话术卡</GlassButton>
      </el-col>
    </el-row>

    <div v-loading="loading" class="card-grid">
      <div v-for="card in filteredScripts" :key="card.id" class="script-card" @click="openEdit(card)">
        <div class="card-head">
          <el-tag size="small" :class="'track-' + (card.track || 'rational')">{{ trackLabel(card.track) }}</el-tag>
          <el-tag size="small" effect="plain">{{ typeLabel(card.script_type) }}</el-tag>
          <el-switch v-permission="'expo:admin'" :model-value="!!card.is_active" size="small" class="card-switch" @click.stop @change="(v) => toggleActive(card, v)" />
        </div>
        <div class="card-title">{{ card.title }}</div>
        <div class="card-content">{{ card.content }}</div>
        <div v-if="card.audience_tags?.length" class="card-tags">
          <el-tag v-for="t in card.audience_tags" :key="t" size="small" effect="plain" type="info" class="aud-tag">{{ t }}</el-tag>
        </div>
      </div>
      <el-empty v-if="!loading && !filteredScripts.length" description="暂无话术卡" class="grid-empty" />
    </div>

    <el-drawer v-model="drawerVisible" :title="isEdit ? '编辑话术卡' : '新建话术卡'" :size="560" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="话术类型" prop="script_type">
          <el-select v-model="form.script_type" style="width: 100%">
            <el-option v-for="o in TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="话术线" prop="track">
          <el-radio-group v-model="form.track">
            <el-radio-button value="emotional">情感线</el-radio-button>
            <el-radio-button value="rational">理性线</el-radio-button>
            <el-radio-button value="identity">身份线</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="标题" prop="title"><el-input v-model="form.title" placeholder="话术卡标题" /></el-form-item>
        <el-form-item label="适用人群">
          <el-select v-model="form.audience_tags" multiple filterable allow-create default-first-option placeholder="自由输入，如 白发遮盖 / 45+ " style="width: 100%" />
        </el-form-item>
        <el-form-item label="正文" prop="content">
          <el-input v-model="form.content" type="textarea" :rows="6" placeholder="话术正文（禁用词：便宜/划算/性价比/打折/薅羊毛）" />
        </el-form-item>
        <el-form-item label="证据点">
          <el-select v-model="form.evidence_points" multiple filterable allow-create default-first-option placeholder="自由输入证据点" style="width: 100%" />
        </el-form-item>
        <el-form-item label="来源版本"><el-input v-model="form.source_version" placeholder="如 v2026-06 营销文档" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="drawerVisible = false">取消</GlassButton>
        <GlassButton v-permission="'expo:admin'" variant="primary" :loading="saving" @click="submit">保存</GlassButton>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getScripts, createScript, updateScript, seedScripts } from '@/api/expo'

const TYPE_OPTIONS = [
  { value: 'opener', label: '开场' },
  { value: 'demo', label: '演示' },
  { value: 'objection', label: '异议应对' },
  { value: 'closer', label: '逼单' },
  { value: 'faq', label: 'FAQ 应对' },
]
const TRACK_LABELS = { emotional: '情感线', rational: '理性线', identity: '身份线' }

function typeLabel(v) {
  return TYPE_OPTIONS.find((o) => o.value === v)?.label || v
}
function trackLabel(v) {
  return TRACK_LABELS[v] || v || '理性线'
}

const scripts = ref([])
const loading = ref(false)
const seeding = ref(false)
const typeFilter = ref('')
const filteredScripts = computed(() =>
  typeFilter.value ? scripts.value.filter((s) => s.script_type === typeFilter.value) : scripts.value
)

const drawerVisible = ref(false)
const isEdit = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()

function emptyForm() {
  return { script_type: 'opener', track: 'emotional', title: '', audience_tags: [], content: '', evidence_points: [], source_version: '', is_active: true }
}
const form = ref(emptyForm())
const rules = {
  script_type: [{ required: true, message: '请选择话术类型', trigger: 'change' }],
  track: [{ required: true, message: '请选择话术线', trigger: 'change' }],
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, message: '请输入正文', trigger: 'blur' }],
}

async function fetchScripts() {
  loading.value = true
  try {
    const res = await getScripts()
    scripts.value = res.data || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  editId.value = null
  form.value = emptyForm()
  drawerVisible.value = true
}

function openEdit(card) {
  isEdit.value = true
  editId.value = card.id
  form.value = {
    script_type: card.script_type, track: card.track, title: card.title,
    audience_tags: card.audience_tags || [], content: card.content,
    evidence_points: card.evidence_points || [], source_version: card.source_version || '',
    is_active: !!card.is_active,
  }
  drawerVisible.value = true
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (isEdit.value) {
      await updateScript(editId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await createScript(form.value)
      ElMessage.success('创建成功')
    }
    drawerVisible.value = false
    fetchScripts()
  } catch { /* 禁用词等错误由拦截器提示 */ } finally {
    saving.value = false
  }
}

async function toggleActive(card, value) {
  try {
    await updateScript(card.id, {
      script_type: card.script_type, track: card.track, title: card.title,
      audience_tags: card.audience_tags || [], content: card.content,
      evidence_points: card.evidence_points || [], source_version: card.source_version || '',
      is_active: value,
    })
    card.is_active = value
    ElMessage.success(value ? '已启用' : '已停用')
  } catch { /* 拦截器已提示 */ }
}

async function handleSeed() {
  seeding.value = true
  try {
    const res = await seedScripts()
    ElMessage.success(`导入完成，新增 ${res.data?.created ?? 0} 条话术卡`)
    fetchScripts()
  } catch { /* 拦截器已提示 */ } finally {
    seeding.value = false
  }
}

onMounted(fetchScripts)
</script>

<style scoped>
.rule-banner {
  margin-bottom: 16px; padding: 10px 16px; border-radius: 8px;
  background: var(--color-warning-bg); color: var(--color-warning-text);
  border: 1px solid var(--color-gold-soft); font-size: 13px; font-weight: 600;
}
.toolbar { margin-bottom: 16px; }
.toolbar-right { display: flex; justify-content: flex-end; gap: 8px; }
.card-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px; min-height: 120px; position: relative;
}
.grid-empty { grid-column: 1 / -1; }
.script-card {
  background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: var(--card-radius); box-shadow: var(--card-shadow);
  padding: 14px 16px; cursor: pointer; transition: box-shadow 0.2s, border-color 0.2s;
}
.script-card:hover { box-shadow: var(--card-shadow-hover); border-color: var(--border-hover); }
.card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.card-switch { margin-left: auto; }
.card-title { font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.card-content {
  color: var(--text-secondary); font-size: 13px; line-height: 1.6;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
}
.card-tags { margin-top: 10px; }
.aud-tag { margin: 2px 4px 2px 0; }
.track-emotional { background: var(--color-warning-bg); border-color: var(--color-gold-muted); color: var(--color-gold-muted, #b8860b); }
.track-rational { background: var(--color-info-bg); border-color: var(--color-info-text); color: var(--color-info-text); }
.track-identity { background: rgba(124, 111, 158, 0.1); border-color: #7c6f9e; color: #7c6f9e; }
</style>
