<template>
  <div class="process-route-manage">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="route-manage-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="split-layout">
      <!-- 左侧：路线列表 -->
      <div class="route-list-panel">
        <div class="panel-header">
          <span class="panel-title">工序路线</span>
          <GlassButton v-permission="'production:admin'" variant="primary" size="sm" :left-icon="Plus" @click="openRouteForm()">新建</GlassButton>
        </div>
        <div class="route-list" v-loading="routeLoading">
          <div
            v-for="r in routes" :key="r.id"
            class="route-item"
            :class="{ active: selectedRoute?.id === r.id }"
            @click="selectRoute(r)"
          >
            <div class="route-item-name">{{ r.name }}</div>
            <div class="route-item-meta">
              <span>{{ r.step_count }} 道工序</span>
              <span>· {{ r.product_count }} 个产品</span>
            </div>
            <div class="route-item-actions">
              <el-button v-permission="'production:admin'" link @click.stop="openRouteForm(r)">编辑</el-button>
              <el-button v-permission="'production:admin'" link type="danger" @click.stop="deleteRoute(r)">删除</el-button>
            </div>
          </div>
          <el-empty v-if="!routeLoading && routes.length === 0" description="暂无路线" />
        </div>
      </div>

      <!-- 右侧：步骤配置 -->
      <div class="route-detail-panel">
        <template v-if="selectedRoute">
          <div class="panel-header">
            <span class="panel-title">{{ selectedRoute.name }}</span>
            <div class="header-actions">
              <GlassButton v-permission="'domestic:admin'" variant="outline" size="sm" @click="applyConfirmedTemplate">应用头套网帽模板</GlassButton>
              <GlassButton v-permission="'production:admin'" variant="secondary" size="sm" @click="addStep">添加工序</GlassButton>
              <GlassButton v-permission="'production:admin'" variant="primary" size="sm" :loading="savingSteps" :disabled="!stepsDirty" @click="saveSteps">
                {{ canEditRules ? '保存路线配置' : '保存路线步骤' }}
              </GlassButton>
              <GlassButton v-permission="'domestic:admin'" variant="primary" size="sm" :loading="savingRules" :disabled="stepsDirty || !rulesDirty" @click="saveRules">保存条件规则</GlassButton>
            </div>
          </div>
          <el-alert v-if="ruleSaveError" class="save-error" type="error" :closable="false" show-icon :title="ruleSaveError" />
          <div class="step-list">
            <draggable v-model="editableSteps" item-key="process_id" handle=".drag-handle" animation="200"
              :disabled="!canEditSteps" @end="handleStepsReordered">
              <template #item="{ element, index }">
                <div class="step-row">
                  <div class="step-main">
                    <span v-permission="'production:admin'" class="drag-handle">≡</span>
                    <span class="step-order">{{ index + 1 }}</span>
                    <span class="step-name">{{ element.process_name }}</span>
                    <el-select
                      v-permission="'domestic:admin'" v-model="element.rule_type" class="rule-type-select"
                      @change="changeRuleType(element)"
                    >
                      <el-option label="必须扫描" value="required" />
                      <el-option label="分流判定" value="decision" />
                      <el-option label="非阻塞可选" value="optional" />
                    </el-select>
                    <el-button v-permission="'production:admin'" link type="danger" @click="removeStep(index)">×</el-button>
                  </div>

                  <div v-if="element.rule_type === 'decision'" v-permission="'domestic:admin'" class="decision-editor">
                    <div v-for="(option, optionIndex) in element.options" :key="optionIndex" class="decision-option">
                      <div class="option-fields">
                        <el-input v-model="option.label" placeholder="结果名称" maxlength="64" @input="markRulesDirty" />
                        <el-input v-model="option.code" placeholder="编码，如 dandong" maxlength="32" @input="markRulesDirty" />
                        <el-button link type="danger" @click="removeDecisionOption(element, optionIndex)">删除</el-button>
                      </div>
                      <el-checkbox-group v-model="option.skip_process_ids" class="skip-targets" @change="markRulesDirty">
                        <span class="skip-label">跳过：</span>
                        <el-checkbox v-for="target in laterSteps(index)" :key="target.process_id" :value="target.process_id">
                          {{ target.process_name }}
                        </el-checkbox>
                      </el-checkbox-group>
                      <div class="path-summary">{{ option.label || '未命名结果' }} → {{ pathSummary(option) }}</div>
                    </div>
                    <el-button link type="primary" @click="addDecisionOption(element)">+添加结果</el-button>
                  </div>
                </div>
              </template>
            </draggable>
            <el-empty v-if="editableSteps.length === 0" description="请添加工序" />
          </div>
        </template>
        <el-empty v-else description="请从左侧选择一条路线" />
      </div>
    </div>

    <!-- 新建/编辑路线弹窗 -->
    <el-dialog v-model="routeFormVisible" :title="routeForm.id ? '编辑路线' : '新建路线'" width="480" destroy-on-close>
      <el-form ref="routeFormRef" :model="routeForm" :rules="routeFormRules" label-width="80px">
        <el-form-item label="路线名称" prop="name">
          <el-input v-model="routeForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="路线描述">
          <el-input v-model="routeForm.description" type="textarea" :rows="3" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="routeFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="submittingRoute" @click="handleRouteSubmit">确认</el-button>
      </template>
    </el-dialog>

    <!-- 添加工序弹窗 -->
    <el-dialog v-model="addStepVisible" title="选择工序" width="400" destroy-on-close>
      <div v-if="availableProcesses.length === 0" style="color: #909399; text-align: center;">没有可添加的工序</div>
      <el-checkbox-group v-model="selectedNewSteps">
        <div v-for="p in availableProcesses" :key="p.id" style="padding: 4px 0;">
          <el-checkbox :value="p.id">{{ p.name }}</el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="addStepVisible = false">取消</el-button>
        <el-button type="primary" :disabled="selectedNewSteps.length === 0" @click="confirmAddStep">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'
import * as api from '@/api/production'
import { getDomesticRouteRules, saveDomesticRouteConfiguration, saveDomesticRouteRules } from '@/api/domestic'
import { useAuthStore } from '@/stores/auth'
import { buildConfirmedDomesticTemplate, validateRouteRule } from '@/views/domestic/conditionalRouting'
import { saveRouteConfiguration } from './routeSaveFlow'
import { useRouteDraftGuard } from './useRouteDraftGuard'

const auth = useAuthStore()
const routeLoading = ref(false)
const routes = ref([])
const selectedRoute = ref(null)
const editableSteps = ref([])
const savingSteps = ref(false)
const savingRules = ref(false)
const stepsDirty = ref(false)
const rulesDirty = ref(false)
const loadingRoute = ref(false)
const routeRulesLoaded = ref(false)
const ruleSaveError = ref('')
const canEditSteps = computed(() => auth.hasPermission('production:admin'))
const canEditRules = computed(() => auth.hasPermission('domestic:admin'))
const hasUnsavedChanges = computed(() => stepsDirty.value || rulesDirty.value)
const confirmDraftLeave = useRouteDraftGuard(hasUnsavedChanges, () => ElMessageBox.confirm(
  '当前路线步骤或条件规则有未保存变更，是否放弃？', '提示', { type: 'warning' },
))

// 路线表单
const routeFormVisible = ref(false)
const submittingRoute = ref(false)
const routeForm = ref({ name: '', description: '' })
const routeFormRef = ref(null)
const routeFormRules = {
  name: [{ required: true, message: '请输入路线名称', trigger: 'blur' }, { min: 2, max: 100, message: '2-100字', trigger: 'blur' }],
}

// 添加工序
const addStepVisible = ref(false)
const allProcesses = ref([])
const selectedNewSteps = ref([])

const availableProcesses = computed(() => {
  const existing = new Set(editableSteps.value.map(s => s.process_id))
  return allProcesses.value.filter(p => !existing.has(p.id))
})
async function loadRoutes() {
  routeLoading.value = true
  try {
    const res = await api.getProcessRoutes({ page_size: 200 })
    routes.value = res.items || []
  } finally {
    routeLoading.value = false
  }
}

async function loadAllProcesses() {
  const res = await api.getActiveProcesses()
  allProcesses.value = res || []
}

async function selectRoute(route) {
  if (await confirmDraftLeave()) doSelectRoute(route)
}

async function doSelectRoute(route) {
  selectedRoute.value = route
  loadingRoute.value = true
  try {
    const stepRes = await api.getRouteSteps(route.id)
    let rules = []
    routeRulesLoaded.value = false
    try {
      const ruleRes = await getDomesticRouteRules(route.id)
      rules = ruleRes.data || []
      routeRulesLoaded.value = true
    } catch { /* 生产路线查看者可能没有内贸规则权限，保留原步骤编辑能力 */ }
    const ruleMap = new Map(rules.map(rule => [rule.process_id, rule]))
    editableSteps.value = (stepRes.steps || []).map(step => {
      const rule = ruleMap.get(step.process_id)
      return {
        process_id: step.process_id,
        process_name: step.process_name,
        rule_type: rule?.rule_type || 'required',
        options: (rule?.config?.options || []).map(option => ({ ...option, skip_process_ids: [...option.skip_process_ids] })),
      }
    })
    await nextTick()
    stepsDirty.value = false
    rulesDirty.value = false
    ruleSaveError.value = ''
  } finally {
    loadingRoute.value = false
  }
}

function openRouteForm(row) {
  if (row) {
    routeForm.value = { id: row.id, name: row.name, description: row.description || '' }
  } else {
    routeForm.value = { name: '', description: '' }
  }
  routeFormVisible.value = true
}

async function handleRouteSubmit() {
  await routeFormRef.value.validate()
  submittingRoute.value = true
  try {
    if (routeForm.value.id) {
      await api.updateProcessRoute(routeForm.value.id, routeForm.value)
    } else {
      await api.createProcessRoute(routeForm.value)
    }
    ElMessage.success('已保存')
    routeFormVisible.value = false
    loadRoutes()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    submittingRoute.value = false
  }
}

async function deleteRoute(row) {
  try {
    await ElMessageBox.confirm('确认删除该路线？已绑定的产品不会被影响。', '提示', { type: 'warning' })
    await api.deleteProcessRoute(row.id)
    ElMessage.success('已删除')
    if (selectedRoute.value?.id === row.id) selectedRoute.value = null
    loadRoutes()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

function addStep() {
  if (!canEditSteps.value) return
  selectedNewSteps.value = []
  addStepVisible.value = true
}

function confirmAddStep() {
  const newSteps = selectedNewSteps.value.map(pid => {
    const proc = allProcesses.value.find(p => p.id === pid)
    return { process_id: pid, process_name: proc?.name || '', rule_type: 'required', options: [] }
  })
  editableSteps.value.push(...newSteps)
  stepsDirty.value = true
  addStepVisible.value = false
}

function removeStep(index) {
  if (!canEditSteps.value) return
  const removedId = editableSteps.value[index].process_id
  editableSteps.value.splice(index, 1)
  for (const step of editableSteps.value) {
    for (const option of step.options || []) {
      option.skip_process_ids = option.skip_process_ids.filter(id => id !== removedId)
    }
  }
  stepsDirty.value = true
  if (canEditRules.value && routeRulesLoaded.value) rulesDirty.value = true
}

function laterSteps(index) {
  return editableSteps.value.slice(index + 1)
}
function changeRuleType(step) {
  if (step.rule_type === 'decision' && step.options.length < 2) {
    step.options = [
      { code: 'result_a', label: '结果A', skip_process_ids: [] },
      { code: 'result_b', label: '结果B', skip_process_ids: [] },
    ]
  } else if (step.rule_type !== 'decision') {
    step.options = []
  }
  markRulesDirty()
}

function addDecisionOption(step) {
  step.options.push({ code: '', label: '', skip_process_ids: [] })
  markRulesDirty()
}

function removeDecisionOption(step, index) {
  step.options.splice(index, 1)
  markRulesDirty()
}
function handleStepsReordered() {
  if (!canEditSteps.value) return
  const orderById = new Map(editableSteps.value.map((step, index) => [step.process_id, index]))
  let rulesChanged = false
  for (const [index, step] of editableSteps.value.entries()) {
    for (const option of step.options || []) {
      const nextIds = option.skip_process_ids.filter(id => orderById.get(id) > index)
      if (nextIds.length !== option.skip_process_ids.length) rulesChanged = true
      option.skip_process_ids = nextIds
    }
  }
  stepsDirty.value = true
  if (rulesChanged && canEditRules.value) rulesDirty.value = true
}

function markRulesDirty() {
  if (canEditRules.value && !loadingRoute.value) rulesDirty.value = true
}
function pathSummary(option) {
  const names = option.skip_process_ids
    .map(id => editableSteps.value.find(step => step.process_id === id)?.process_name)
    .filter(Boolean)
  return names.length ? `跳过 ${names.join('、')}` : '继续后续工序'
}

async function applyConfirmedTemplate() {
  try {
    await ElMessageBox.confirm('模板会覆盖当前条件规则，但不会立即保存。', '应用头套网帽模板', { type: 'warning' })
    const templateMap = new Map(buildConfirmedDomesticTemplate(editableSteps.value).map(rule => [rule.process_id, rule]))
    editableSteps.value = editableSteps.value.map(step => {
      const rule = templateMap.get(step.process_id)
      return {
        ...step,
        rule_type: rule?.rule_type || 'required',
        options: (rule?.options || []).map(option => ({ ...option, skip_process_ids: [...option.skip_process_ids] })),
      }
    })
    markRulesDirty()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '模板应用失败')
  }
}

function buildRulePayload() {
  if (!routeRulesLoaded.value) throw new Error('条件规则尚未加载，不能保存')
  return editableSteps.value.map(step => validateRouteRule(step, editableSteps.value)).filter(Boolean)
}
async function reloadSelectedRoute() {
  const routeId = selectedRoute.value.id
  await loadRoutes()
  const refreshed = routes.value.find(route => route.id === routeId) || selectedRoute.value
  await doSelectRoute(refreshed)
}

function errorDetail(error) {
  return error.response?.data?.detail || error.message || '未知错误'
}
async function saveSteps() {
  if (!selectedRoute.value || !canEditSteps.value || !stepsDirty.value) return
  let rules = []
  if (canEditRules.value) {
    try {
      rules = buildRulePayload()
    } catch (error) {
      ElMessage.warning(error.message)
      return
    }
  }
  savingSteps.value = true
  try {
    const steps = editableSteps.value.map(s => ({ process_id: s.process_id }))
    const routeId = selectedRoute.value.id
    if (canEditRules.value) {
      await saveRouteConfiguration({
        save: () => saveDomesticRouteConfiguration(routeId, steps, rules),
        reload: reloadSelectedRoute,
      })
      ElMessage.success('路线配置已保存')
    } else {
      await api.saveRouteSteps(routeId, steps)
      await reloadSelectedRoute()
      ElMessage.success('路线步骤已保存')
    }
  } catch (e) {
    if (canEditRules.value) {
      rulesDirty.value = true
      ruleSaveError.value = `路线配置保存失败：${errorDetail(e)}`
    } else {
      ruleSaveError.value = `路线步骤保存失败：${errorDetail(e)}`
    }
  } finally {
    savingSteps.value = false
  }
}
async function saveRules() {
  if (!selectedRoute.value || !canEditRules.value || stepsDirty.value || !rulesDirty.value) return
  let rules
  try {
    rules = buildRulePayload()
  } catch (error) {
    ElMessage.warning(error.message)
    return
  }
  savingRules.value = true
  try {
    await saveDomesticRouteRules(selectedRoute.value.id, rules)
    ruleSaveError.value = ''
    await reloadSelectedRoute()
    ElMessage.success('条件规则已保存')
  } catch (error) {
    ruleSaveError.value = `条件规则保存失败：${errorDetail(error)}`
  } finally {
    savingRules.value = false
  }
}

onMounted(() => {
  loadRoutes()
  loadAllProcesses()
})
</script>

<style scoped>
.process-route-manage { padding: 20px; height: calc(100vh - 120px); position: relative; }

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.route-manage-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   el-dialog 默认就地渲染（append-to-body=false），通配会覆盖
   .el-overlay 的 position: fixed，弹窗打开后看不见 */
.process-route-manage .split-layout { position: relative; z-index: 1; }

.split-layout { display: flex; gap: 16px; height: 100%; }

/* 左右面板：同款渐变玻璃 */
.route-list-panel,
.route-detail-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}
.route-list-panel { width: 320px; flex-shrink: 0; display: flex; flex-direction: column; }
.route-detail-panel { flex: 1; display: flex; flex-direction: column; }
.panel-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #ebeef5; }
.panel-title { font-weight: 600; font-size: 15px; }
.header-actions { display: flex; gap: 8px; }
.save-error { margin: 12px 16px 0; width: auto; }
.route-list { flex: 1; overflow-y: auto; padding: 8px; }
.route-item { padding: 10px 12px; border-radius: 4px; cursor: pointer; margin-bottom: 4px; transition: background 0.2s; position: relative; }
.route-item:hover { background: #f5f7fa; }
.route-item.active { background: #ecf5ff; }
.route-item-name { font-weight: 500; font-size: 14px; }
.route-item-meta { font-size: 12px; color: #909399; margin-top: 4px; }
.route-item-actions { position: absolute; right: 8px; top: 8px; display: none; }
.route-item:hover .route-item-actions { display: flex; gap: 4px; }
.step-list { flex: 1; overflow-y: auto; padding: 12px 16px; }
.step-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.step-row { flex-direction: column; align-items: stretch; gap: 0; }
.step-main { display: flex; align-items: center; gap: 10px; }
.drag-handle { cursor: grab; color: #c0c4cc; font-size: 18px; }
.step-order { width: 24px; height: 24px; background: #409eff; color: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; }
.step-name { flex: 1; font-weight: 500; }
.rule-type-select { width: 150px; }
.decision-editor { margin: 8px 34px 4px; padding: 10px 12px; border-radius: 8px; background: var(--el-fill-color-lighter); }
.decision-option { padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.decision-option:last-of-type { border-bottom: none; }
.option-fields { display: grid; grid-template-columns: minmax(120px, 1fr) minmax(150px, 1fr) auto; gap: 8px; }
.skip-targets { display: flex; flex-wrap: wrap; gap: 2px 12px; margin-top: 8px; }
.skip-label { font-size: 13px; color: var(--el-text-color-secondary); }
.path-summary { margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
