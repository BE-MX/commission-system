<template>
  <div class="concept-editor" v-loading="loading">
    <!-- 顶部导航 -->
    <div class="editor-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="goBack">返回列表</el-button>
        <span class="concept-title">{{ concept.name_zh || '新概念' }}</span>
        <el-tag v-if="concept.status" :type="statusTagType(concept.status)" size="small">
          {{ statusLabels[concept.status] }}
        </el-tag>
      </div>
      <div class="header-right">
        <!-- 完整度指示器 -->
        <div class="completeness" v-if="concept.id">
          <span class="completeness-text">完整度 {{ completeness.percentage || 0 }}%</span>
          <el-progress :percentage="completeness.percentage || 0" :stroke-width="6"
            :status="completeness.is_submittable ? 'success' : ''" style="width: 120px" />
          <span class="completeness-detail">
            必填 {{ completeness.required_filled || 0 }}/{{ completeness.required_total || 0 }}
          </span>
        </div>

        <!-- 操作按钮 -->
        <template v-if="canEdit">
          <el-button @click="handleSave" :loading="saving">保存草稿</el-button>
        </template>
        <el-button v-if="concept.status === 'pending' && canEdit" type="success" @click="handleClaim">
          认领补充
        </el-button>
        <el-button v-if="canSubmit" type="primary" @click="handleSubmit"
          :disabled="!completeness.is_submittable">
          提交审批
          <el-tooltip v-if="!completeness.is_submittable && concept.id"
            :content="'未填: ' + (completeness.missing_required || []).join(', ')"
            placement="bottom">
            <el-icon style="margin-left: 4px"><Warning /></el-icon>
          </el-tooltip>
        </el-button>
        <el-button v-if="canApprove" type="success" @click="handleApprove">审批通过</el-button>
        <el-button v-if="canApprove" type="warning" @click="handleReject">驳回修改</el-button>
        <el-button v-if="canDeprecate" type="danger" @click="handleDeprecate">废弃概念</el-button>
      </div>
    </div>

    <!-- 左侧分区导航 + 右侧内容 -->
    <div class="editor-body" v-if="concept.id || isCreating">
      <div class="section-nav">
        <div v-for="sec in sections" :key="sec.key"
          :class="['section-nav-item', { active: activeSection === sec.key }]"
          @click="scrollToSection(sec.key)">
          <span class="section-icon">{{ sec.icon }}</span>
          <span class="section-label">{{ sec.label }}</span>
        </div>
      </div>

      <div class="section-content">
        <!-- 1. 基本信息 -->
        <section id="sec-basic" class="form-section">
          <h3>📋 基本信息</h3>
          <el-form :model="form" label-width="100px" :disabled="!canEdit">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="概念 ID" required>
                  <el-input v-model="form.id" :disabled="!isCreating" placeholder="snake_case" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="所属层级" required>
                  <el-select v-model="form.layer" style="width: 100%">
                    <el-option v-for="(l, k) in layerLabels" :key="k" :label="l" :value="k" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="中文名" required>
                  <el-input v-model="form.name_zh" maxlength="50" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="英文名" required>
                  <el-input v-model="form.name_en" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="优先级">
                  <el-select v-model="form.priority" clearable style="width: 100%">
                    <el-option label="P1" value="P1" />
                    <el-option label="P2" value="P2" />
                    <el-option label="P3" value="P3" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </section>

        <!-- 2. 定义 -->
        <section id="sec-definition" class="form-section">
          <h3>📖 定义</h3>
          <el-form :model="form" label-width="100px" :disabled="!canEdit">
            <el-form-item label="一句话定义" required>
              <el-input v-model="form.one_liner" maxlength="60" show-word-limit placeholder="≤30字" />
            </el-form-item>
            <el-form-item label="完整定义" required>
              <el-input v-model="form.full_definition" type="textarea" :rows="6" placeholder="支持 Markdown" />
            </el-form-item>
          </el-form>
        </section>

        <!-- 3. 边界 -->
        <section id="sec-boundary" class="form-section">
          <h3>🔲 边界</h3>
          <el-form :model="form" label-width="100px" :disabled="!canEdit">
            <el-form-item label="包含范围" required>
              <div class="tag-input-area">
                <el-tag v-for="(tag, i) in (form.boundary_includes || [])" :key="i" closable
                  :disable-transitions="false" @close="removeTag('boundary_includes', i)" style="margin: 2px 4px">
                  {{ tag }}
                </el-tag>
                <el-input v-model="tagInput.includes" size="small" style="width: 200px"
                  placeholder="按 Enter 添加" @keyup.enter="addTag('boundary_includes', 'includes')" />
              </div>
            </el-form-item>
            <el-form-item label="排除范围" required>
              <div class="tag-input-area">
                <el-tag v-for="(tag, i) in (form.boundary_excludes || [])" :key="i" closable type="danger"
                  :disable-transitions="false" @close="removeTag('boundary_excludes', i)" style="margin: 2px 4px">
                  {{ tag }}
                </el-tag>
                <el-input v-model="tagInput.excludes" size="small" style="width: 200px"
                  placeholder="按 Enter 添加" @keyup.enter="addTag('boundary_excludes', 'excludes')" />
              </div>
            </el-form-item>
          </el-form>
        </section>

        <!-- 4. 计算 -->
        <section id="sec-calculation" class="form-section">
          <h3>🧮 计算</h3>
          <el-form :model="form" label-width="100px" :disabled="!canEdit">
            <el-form-item label="计算公式">
              <el-input v-model="form.formula" type="textarea" :rows="3" />
            </el-form-item>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="分子">
                  <el-input v-model="form.numerator" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="分母">
                  <el-input v-model="form.denominator" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="单位" required>
              <el-input v-model="form.unit" style="width: 200px" />
            </el-form-item>
          </el-form>
        </section>

        <!-- 5. 数据源 -->
        <section id="sec-datasource" class="form-section">
          <h3>🗄 数据源</h3>
          <el-form :model="form" label-width="100px" :disabled="!canEdit">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="主表" required>
                  <el-input v-model="form.primary_table" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="主字段" required>
                  <el-input v-model="form.primary_field" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="过滤条件">
              <div class="tag-input-area">
                <el-tag v-for="(tag, i) in (form.filter_conditions || [])" :key="i" closable
                  @close="removeTag('filter_conditions', i)" style="margin: 2px 4px">
                  {{ tag }}
                </el-tag>
                <el-input v-model="tagInput.filters" size="small" style="width: 300px"
                  placeholder="按 Enter 添加" @keyup.enter="addTag('filter_conditions', 'filters')" />
              </div>
            </el-form-item>
            <el-form-item label="关联表">
              <div class="tag-input-area">
                <el-tag v-for="(tag, i) in (form.related_tables || [])" :key="i" closable type="info"
                  @close="removeTag('related_tables', i)" style="margin: 2px 4px">
                  {{ tag }}
                </el-tag>
                <el-input v-model="tagInput.related" size="small" style="width: 300px"
                  placeholder="按 Enter 添加" @keyup.enter="addTag('related_tables', 'related')" />
              </div>
            </el-form-item>
          </el-form>
        </section>

        <!-- 6. 维度 -->
        <section id="sec-dimension" class="form-section">
          <h3>📐 维度</h3>
          <el-form :model="form" label-width="100px" :disabled="!canEdit">
            <el-form-item label="时间粒度" required>
              <el-checkbox-group v-model="form.time_granularity">
                <el-checkbox label="日" value="day" />
                <el-checkbox label="周" value="week" />
                <el-checkbox label="月" value="month" />
                <el-checkbox label="季" value="quarter" />
                <el-checkbox label="年" value="year" />
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="实体粒度" required>
              <el-input v-model="form.entity_granularity" placeholder="如：订单级 / 客户级 / 产品级" />
            </el-form-item>
            <el-form-item label="可切分维度">
              <div class="tag-input-area">
                <el-tag v-for="(tag, i) in (form.segments || [])" :key="i" closable type="info"
                  @close="removeTag('segments', i)" style="margin: 2px 4px">
                  {{ tag }}
                </el-tag>
                <el-input v-model="tagInput.segments" size="small" style="width: 300px"
                  placeholder='按 Enter 添加，格式："按 XX（字段名）"' @keyup.enter="addTag('segments', 'segments')" />
              </div>
            </el-form-item>
          </el-form>
        </section>

        <!-- 7. 关联（Phase 2 完整实现，Phase 1 只读展示） -->
        <section id="sec-relationships" class="form-section">
          <h3>🔗 关联关系</h3>
          <el-table :data="relationships" stripe style="width: 100%">
            <el-table-column prop="relation_type" label="关系类型" width="150">
              <template #default="{ row }">
                <el-tag size="small" :color="relTypeColor(row.relation_type)" effect="dark" style="border: none">
                  {{ row.relation_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="方向" width="80">
              <template #default="{ row }">
                {{ row.direction === 'forward' ? '→' : '←' }}
              </template>
            </el-table-column>
            <el-table-column label="目标概念" min-width="180">
              <template #default="{ row }">
                {{ row.direction === 'forward' ? row.target_name_zh : row.source_name_zh }}
                ({{ row.direction === 'forward' ? row.target_concept_id : row.source_concept_id }})
              </template>
            </el-table-column>
            <el-table-column prop="description" label="备注" min-width="200" show-overflow-tooltip />
          </el-table>
          <div v-if="canEdit" style="margin-top: 12px">
            <el-button :icon="Plus" size="small" @click="addRelDrawerVisible = true">添加关联</el-button>
          </div>
        </section>

        <!-- 8. 元数据 -->
        <section id="sec-metadata" class="form-section">
          <h3>ℹ️ 元数据</h3>
          <el-form :model="form" label-width="100px" :disabled="!canEdit">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="负责人" required>
                  <el-input v-model="form.owner" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="置信度" required>
                  <el-select v-model="form.confidence" style="width: 100%">
                    <el-option label="高" value="high" />
                    <el-option label="中" value="medium" />
                    <el-option label="低" value="low" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="失效触发条件" required>
              <el-input v-model="form.staleness_trigger" type="textarea" :rows="2"
                placeholder="什么变化会导致此定义需要更新" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.notes" type="textarea" :rows="3" />
            </el-form-item>
          </el-form>
        </section>
      </div>
    </div>

    <!-- 添加关联抽屉 -->
    <el-drawer v-model="addRelDrawerVisible" title="添加关联关系" size="400px">
      <el-form label-width="90px">
        <el-form-item label="关系类型">
          <el-select v-model="newRel.relation_type" style="width: 100%">
            <el-option v-for="rt in relTypes" :key="rt.value" :label="rt.label" :value="rt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="方向">
          <el-radio-group v-model="newRel.direction">
            <el-radio value="forward">本概念 → 目标</el-radio>
            <el-radio value="reverse">目标 → 本概念</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目标概念">
          <el-select v-model="newRel.target_concept_id" filterable remote
            :remote-method="searchConcepts" :loading="searchLoading" style="width: 100%"
            placeholder="搜索概念名称">
            <el-option v-for="c in conceptOptions" :key="c.id" :label="`${c.name_zh} (${c.id})`" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注说明">
          <el-input v-model="newRel.description" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addRelDrawerVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAddRel">确认添加</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus, Warning } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  getConcept, createConcept, updateConcept, transitionStatus,
  listRelationships, createRelationship, listConcepts,
} from '@/api/governance'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// ── 常量 ─────────────────────────────────────────────────
const layerLabels = {
  financial: '财务', customer: '客户', product: '产品',
  production: '生产', sales_process: '销售过程', logistics: '物流',
}
const statusLabels = {
  draft: '草稿', pending: '待补充', in_progress: '填写中',
  review: '待审批', active: '已完成', deprecated: '已废弃',
}
const statusTagType = (s) => ({
  draft: 'info', pending: 'warning', in_progress: '',
  review: 'warning', active: 'success', deprecated: 'danger',
}[s] || 'info')

const sections = [
  { key: 'basic', icon: '📋', label: '基本信息' },
  { key: 'definition', icon: '📖', label: '定义' },
  { key: 'boundary', icon: '🔲', label: '边界' },
  { key: 'calculation', icon: '🧮', label: '计算' },
  { key: 'datasource', icon: '🗄', label: '数据源' },
  { key: 'dimension', icon: '📐', label: '维度' },
  { key: 'relationships', icon: '🔗', label: '关联' },
  { key: 'metadata', icon: 'ℹ️', label: '元数据' },
]

const relTypes = [
  { value: 'parent_of', label: '⬆ 父子层级' },
  { value: 'composed_of', label: '🔵 组成' },
  { value: 'derived_from', label: '🟢 衍生' },
  { value: 'influences', label: '🟠 影响' },
  { value: 'conflicts_with', label: '🔴 易混淆' },
  { value: 'requires', label: '🟣 前置依赖' },
  { value: 'leads', label: '🔹 时间序列(leads)' },
  { value: 'lags', label: '🔹 时间序列(lags)' },
]

const relTypeColor = (t) => ({
  parent_of: '#606266', composed_of: '#409EFF', derived_from: '#67C23A',
  influences: '#E6A23C', conflicts_with: '#F56C6C', requires: '#9B59B6',
  leads: '#00BCD4', lags: '#00BCD4',
}[t] || '#909399')

// ── 状态 ─────────────────────────────────────────────────
const loading = ref(false)
const saving = ref(false)
const concept = ref({})
const completeness = ref({})
const relationships = ref([])
const activeSection = ref('basic')
const conceptId = computed(() => route.params.conceptId)
const isCreating = computed(() => conceptId.value === 'new')

// ── 表单 ─────────────────────────────────────────────────
const form = reactive({
  id: '', name_zh: '', name_en: '', layer: 'financial',
  priority: '', one_liner: '', full_definition: '',
  boundary_includes: [], boundary_excludes: [],
  formula: '', numerator: '', denominator: '', unit: '',
  primary_table: '', primary_field: '',
  filter_conditions: [], related_tables: [],
  time_granularity: [], entity_granularity: '',
  segments: [], owner: '', staleness_trigger: '',
  confidence: '', notes: '',
})

const tagInput = reactive({
  includes: '', excludes: '', filters: '', related: '', segments: '',
})

// ── 关联抽屉 ─────────────────────────────────────────────
const addRelDrawerVisible = ref(false)
const newRel = reactive({
  target_concept_id: '', relation_type: 'influences', direction: 'forward', description: '',
})
const conceptOptions = ref([])
const searchLoading = ref(false)

// ── 权限计算 ─────────────────────────────────────────────
const isAdmin = computed(() => authStore.hasAnyPermission(['governance:admin']))
const canEdit = computed(() => {
  if (!concept.value.id) return true
  const s = concept.value.status
  return authStore.hasAnyPermission(['governance:write', 'governance:admin'])
    && (s === 'draft' || s === 'in_progress')
})
const canSubmit = computed(() =>
  concept.value.status === 'in_progress' || concept.value.status === 'draft')
const canApprove = computed(() =>
  isAdmin.value && concept.value.status === 'review')
const canDeprecate = computed(() =>
  isAdmin.value && concept.value.status === 'active')

// ── 数据加载 ─────────────────────────────────────────────
async function loadConcept() {
  if (isCreating.value) return
  loading.value = true
  try {
    const { data: res } = await getConcept(conceptId.value)
    const data = res.data ?? res
    concept.value = data
    completeness.value = data.completeness || {}

    // 填充表单
    Object.keys(form).forEach(k => {
      if (data[k] !== undefined) form[k] = data[k]
    })
    // 确保 JSON 数组字段不为 null
    for (const f of ['boundary_includes', 'boundary_excludes', 'filter_conditions',
      'related_tables', 'time_granularity', 'segments']) {
      if (!form[f]) form[f] = []
    }

    // 加载关联
    loadRelationships()
  } catch (e) {
    ElMessage.error('加载概念失败')
  } finally {
    loading.value = false
  }
}

async function loadRelationships() {
  if (isCreating.value) return
  try {
    const { data: res } = await listRelationships(conceptId.value)
    relationships.value = (res.data ?? res) || []
  } catch (e) {
    console.error('加载关联失败', e)
  }
}

// ── 操作 ─────────────────────────────────────────────────
async function handleSave() {
  saving.value = true
  try {
    if (isCreating.value) {
      const { data: res } = await createConcept({ ...form })
      const data = res.data ?? res
      router.replace(`/governance/concepts/${data.id}`)
      ElMessage.success('创建成功')
    } else {
      const { data: res } = await updateConcept(conceptId.value, { ...form })
      concept.value = (res.data ?? res)
      ElMessage.success('保存成功')
    }
    loadConcept()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleClaim() {
  try {
    await transitionStatus(conceptId.value, { action: 'claim' })
    ElMessage.success('已认领')
    loadConcept()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '认领失败')
  }
}

async function handleSubmit() {
  try {
    await ElMessageBox.confirm('确认提交审批？提交后不可修改直到审批完成。', '提交审批')
    await transitionStatus(conceptId.value, { action: 'submit' })
    ElMessage.success('已提交审批')
    loadConcept()
  } catch { /* cancel */ }
}

async function handleApprove() {
  try {
    await ElMessageBox.confirm('确认审批通过？', '审批通过')
    await transitionStatus(conceptId.value, { action: 'approve' })
    ElMessage.success('审批通过')
    loadConcept()
  } catch { /* cancel */ }
}

async function handleReject() {
  try {
    const { value } = await ElMessageBox.prompt('请输入驳回原因', '驳回修改', {
      inputPlaceholder: '驳回原因',
    })
    await transitionStatus(conceptId.value, { action: 'reject', comment: value })
    ElMessage.success('已驳回')
    loadConcept()
  } catch { /* cancel */ }
}

async function handleDeprecate() {
  try {
    const { value } = await ElMessageBox.prompt('请输入废弃原因', '废弃概念', {
      inputPlaceholder: '废弃原因',
    })
    await transitionStatus(conceptId.value, { action: 'deprecate', comment: value })
    ElMessage.success('已废弃')
    loadConcept()
  } catch { /* cancel */ }
}

// ── 标签输入 ─────────────────────────────────────────────
function addTag(field, inputKey) {
  const val = tagInput[inputKey]?.trim()
  if (!val) return
  if (!form[field]) form[field] = []
  form[field].push(val)
  tagInput[inputKey] = ''
}

function removeTag(field, index) {
  form[field].splice(index, 1)
}

// ── 关联 ─────────────────────────────────────────────────
async function searchConcepts(query) {
  if (!query) return
  searchLoading.value = true
  try {
    const { data: res } = await listConcepts({ keyword: query, page_size: 20 })
    const payload = res.data ?? res
    conceptOptions.value = (payload.items || []).filter(c => c.id !== conceptId.value)
  } finally {
    searchLoading.value = false
  }
}

async function submitAddRel() {
  if (!newRel.target_concept_id) {
    ElMessage.warning('请选择目标概念')
    return
  }
  try {
    await createRelationship(conceptId.value, { ...newRel })
    ElMessage.success('关联已添加')
    addRelDrawerVisible.value = false
    newRel.target_concept_id = ''
    newRel.description = ''
    loadRelationships()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '添加失败')
  }
}

// ── 导航 ─────────────────────────────────────────────────
function scrollToSection(key) {
  activeSection.value = key
  const el = document.getElementById(`sec-${key}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function goBack() {
  router.push('/governance/concepts')
}

// ── 初始化 ───────────────────────────────────────────────
onMounted(() => {
  loadConcept()
})
</script>

<style scoped>
.concept-editor {
  padding: 20px;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.concept-title {
  font-size: 18px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.completeness {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.editor-body {
  display: flex;
  gap: 24px;
}

.section-nav {
  width: 160px;
  flex-shrink: 0;
  position: sticky;
  top: 20px;
  align-self: flex-start;
}

.section-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: var(--el-text-color-regular);
  transition: all 0.2s;
}

.section-nav-item:hover {
  background: var(--el-fill-color-light);
}

.section-nav-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 500;
}

.section-icon {
  font-size: 16px;
}

.section-content {
  flex: 1;
  min-width: 0;
}

.form-section {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 20px 24px;
  margin-bottom: 16px;
}

.form-section h3 {
  margin: 0 0 16px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.tag-input-area {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  min-height: 32px;
}
</style>
