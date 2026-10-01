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
        <ListPageStatus :error="routeError" :loading="routeLoading" :has-data="Boolean(routes.length)" @retry="loadRoutes" />
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
          <el-empty v-if="!routeLoading && !routeError && routes.length === 0" description="暂无路线" />
        </div>
      </div>

      <!-- 右侧：步骤配置 -->
      <div class="route-detail-panel">
        <template v-if="selectedRoute">
          <div class="panel-header">
            <span class="panel-title">{{ selectedRoute.name }}</span>
            <div class="header-actions">
              <GlassButton v-permission="'domestic:admin'" variant="outline" size="sm" :disabled="!editorReady || !routeRulesLoaded" @click="applyConfirmedTemplate">应用头套网帽模板</GlassButton>
              <GlassButton v-permission="'production:admin'" variant="secondary" size="sm" :disabled="!editorReady" @click="addStep">添加工序</GlassButton>
              <GlassButton v-permission="'production:admin'" variant="primary" size="sm" :loading="savingSteps" :disabled="!editorReady || !stepsDirty" @click="saveSteps">
                {{ canEditRules ? '保存路线配置' : '保存路线步骤' }}
              </GlassButton>
              <GlassButton v-permission="'domestic:admin'" variant="primary" size="sm" :loading="savingRules" :disabled="!editorReady || !routeRulesLoaded || stepsDirty || !rulesDirty" @click="saveRules">保存条件规则</GlassButton>
            </div>
          </div>
          <ListPageStatus :paged="false" :error="detailResource.errorMessage.value" :loading="loadingRoute" :has-data="detailResource.hasLoaded.value" @retry="fetchSelectedRoute" />
          <el-alert v-if="ruleSaveError" class="save-error" type="error" :closable="false" show-icon :title="ruleSaveError" />
          <div v-if="detailResource.hasLoaded.value" class="step-list">
            <draggable v-model="editableSteps" item-key="process_id" handle=".drag-handle" animation="200"
              :disabled="!canEditSteps || !editorReady" @end="handleStepsReordered">
              <template #item="{ element, index }">
                <div class="step-row">
                  <div class="step-main">
                    <span v-permission="'production:admin'" class="drag-handle">≡</span>
                    <span class="step-order">{{ index + 1 }}</span>
                    <span class="step-name">{{ element.process_name }}</span>
                    <el-select
                      v-permission="'domestic:admin'" v-model="element.rule_type" class="rule-type-select" :disabled="!editorReady || !routeRulesLoaded"
                      @change="changeRuleType(element)"
                    >
                      <el-option label="必须扫描" value="required" />
                      <el-option label="分流判定" value="decision" />
                      <el-option label="非阻塞可选" value="optional" />
                    </el-select>
                    <el-button v-permission="'production:admin'" link type="danger" :disabled="!editorReady" @click="removeStep(index)">×</el-button>
                  </div>

                  <div v-if="element.rule_type === 'decision'" v-permission="'domestic:admin'" class="decision-editor">
                    <div v-for="(option, optionIndex) in element.options" :key="optionIndex" class="decision-option">
                      <div class="option-fields">
                        <el-input v-model="option.label" placeholder="结果名称" maxlength="64" :disabled="!editorReady" @input="markRulesDirty" />
                        <el-input v-model="option.code" placeholder="编码，如 dandong" maxlength="32" :disabled="!editorReady" @input="markRulesDirty" />
                        <el-button link type="danger" :disabled="!editorReady" @click="removeDecisionOption(element, optionIndex)">删除</el-button>
                      </div>
                      <el-checkbox-group v-model="option.skip_process_ids" class="skip-targets" :disabled="!editorReady" @change="markRulesDirty">
                        <span class="skip-label">跳过：</span>
                        <el-checkbox v-for="target in laterSteps(index)" :key="target.process_id" :value="target.process_id">
                          {{ target.process_name }}
                        </el-checkbox>
                      </el-checkbox-group>
                      <div class="path-summary">{{ option.label || '未命名结果' }} → {{ pathSummary(option) }}</div>
                    </div>
                    <el-button link type="primary" :disabled="!editorReady" @click="addDecisionOption(element)">+添加结果</el-button>
                  </div>
                </div>
              </template>
            </draggable>
            <el-empty v-if="!loadingRoute && !detailResource.error.value && editableSteps.length === 0" description="请添加工序" />
          </div>
        </template>
        <el-empty v-else description="请从左侧选择一条路线" />
      </div>
    </div>

    <!-- 新建/编辑路线弹窗 -->
    <el-dialog v-model="routeFormVisible" :title="routeForm.id ? '编辑路线' : '新建路线'" width="480px" destroy-on-close>
      <el-form label-position="top" ref="routeFormRef" :model="routeForm" :rules="routeFormRules">
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
    <el-dialog v-model="addStepVisible" title="选择工序" width="480px" destroy-on-close>
      <ListPageStatus :paged="false" :error="processesResource.errorMessage.value" :loading="processesResource.loading.value" :has-data="processesResource.hasLoaded.value" @retry="loadAllProcesses" />
      <el-empty v-if="processesResource.hasLoaded.value && !processesResource.error.value && !processesResource.loading.value && availableProcesses.length === 0" description="没有可添加的工序" />
      <el-checkbox-group v-model="selectedNewSteps" :disabled="!processesReady || !editorReady">
        <div v-for="p in availableProcesses" :key="p.id" style="padding: 4px 0;">
          <el-checkbox :value="p.id">{{ p.name }}</el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="addStepVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!processesReady || !editorReady || selectedNewSteps.length === 0" @click="confirmAddStep">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { useAsyncResource } from '@/composables/useAsyncResource'
import { confirmAction, msgSuccessText, msgError, msgWarning } from '@/utils/feedback'
import { ref, computed, onMounted, watch } from 'vue'

import { Plus } from '@element-plus/icons-vue'
import draggable from 'vuedraggable'
import * as api from '@/api/production'
import { getDomesticRouteRules, saveDomesticRouteConfiguration, saveDomesticRouteRules } from '@/api/domestic'
import { useAuthStore } from '@/stores/auth'
import { buildConfirmedDomesticTemplate, validateRouteRule } from '@/views/domestic/conditionalRouting'
import { saveRouteConfiguration } from './routeSaveFlow'
import { useRouteDraftGuard } from './useRouteDraftGuard'

const auth = useAuthStore()
const routesResource = useAsyncResource(async (_, { signal }) => {
  const response = await api.getProcessRoutes({ page_size: 200 }, { signal, suppressToast: true })
  return response.items || []
})
const routeLoading = routesResource.loading
const routes = computed(() => routesResource.data.value || [])
const routeError = routesResource.errorMessage
const selectedRoute = ref(null)
let routeSelectionVersion = 0
const editableSteps = ref([])
const savingSteps = ref(false)
const savingRules = ref(false)
const stepsDirty = ref(false)
const rulesDirty = ref(false)
const ruleSaveError = ref('')
const canEditSteps = computed(() => auth.hasPermission('production:admin'))
const canEditRules = computed(() => auth.hasPermission('domestic:admin'))
const readOptions = signal => ({ signal, suppressToast: true })
const detailResource = useAsyncResource(async (id, { signal }) => {
  const stepRes = await api.getRouteSteps(id, readOptions(signal))
  let rules = [], rulesLoaded = false
  try {
    const ruleRes = await getDomesticRouteRules(id, readOptions(signal))
    rules = ruleRes.data || []; rulesLoaded = true
  } catch (error) {
    // Production-only editors may lack domestic access; transport errors remain recoverable errors.
    if (error.response?.status !== 403 || canEditRules.value) throw error
  }
  return { steps: stepRes.steps || [], rules, rulesLoaded }
})
const loadingRoute = detailResource.loading
const routeRulesLoaded = computed(() => !!detailResource.data.value?.rulesLoaded && !detailResource.error.value)
const editorReady = computed(() => !!selectedRoute.value && detailResource.hasLoaded.value && !loadingRoute.value
  && !detailResource.error.value && !savingSteps.value && !savingRules.value)
const hasUnsavedChanges = computed(() => stepsDirty.value || rulesDirty.value)
const confirmDraftLeave = useRouteDraftGuard(hasUnsavedChanges, () => confirmAction(
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
const processesResource = useAsyncResource(async (_, { signal }) => (await api.getActiveProcesses(readOptions(signal))) || [], { initialData: [] })
const allProcesses = processesResource.data
const processesReady = computed(() => processesResource.hasLoaded.value && !processesResource.error.value && !processesResource.loading.value)
const selectedNewSteps = ref([])

const availableProcesses = computed(() => {
  const existing = new Set(editableSteps.value.map(s => s.process_id))
  return allProcesses.value.filter(p => !existing.has(p.id))
})
const loadRoutes = () => routesResource.load()

const loadAllProcesses = () => processesResource.load()

async function selectRoute(route) {
  if (await confirmDraftLeave()) return doSelectRoute(route)
  return false
}

function clearSelectedRoute() {
  routeSelectionVersion += 1
  detailResource.clear(); selectedRoute.value = null; editableSteps.value = []
  stepsDirty.value = false; rulesDirty.value = false; ruleSaveError.value = ''
  addStepVisible.value = false; selectedNewSteps.value = []
}

function doSelectRoute(route) {
  if (selectedRoute.value?.id !== route.id) clearSelectedRoute()
  selectedRoute.value = route
  return fetchSelectedRoute()
}

async function fetchSelectedRoute() {
  const routeId = selectedRoute.value?.id
  if (!routeId) return false
  const success = await detailResource.load(routeId)
  if (!success || selectedRoute.value?.id !== routeId) return false
  // Retrying a failed same-route read must not discard an unsaved editor.
  if (!hasUnsavedChanges.value) {
    const { steps, rules } = detailResource.data.value
    const ruleMap = new Map(rules.map(rule => [rule.process_id, rule]))
    editableSteps.value = steps.map(step => {
      const rule = ruleMap.get(step.process_id)
      return {
        process_id: step.process_id,
        process_name: step.process_name,
        rule_type: rule?.rule_type || 'required',
        options: (rule?.config?.options || []).map(option => ({ ...option, skip_process_ids: [...option.skip_process_ids] })),
      }
    })
    ruleSaveError.value = ''
  }
  return true
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
    msgSuccessText('已保存')
    routeFormVisible.value = false
    loadRoutes()
  } catch (e) {
    msgError(e.response?.data?.detail || '操作失败', e)
  } finally {
    submittingRoute.value = false
  }
}

async function deleteRoute(row) {
  try {
    await confirmAction('仅未被产品、订单、生产进度或内贸规则引用的路线可以删除。确认删除该路线及其工序配置？', '删除路线', { type: 'warning' })
    await api.deleteProcessRoute(row.id)
    msgSuccessText('已删除')
    if (selectedRoute.value?.id === row.id) clearSelectedRoute()
    loadRoutes()
  } catch (e) {
    if (e !== 'cancel') msgError(e.response?.data?.detail || '删除失败', e)
  }
}

function addStep() {
  if (!canEditSteps.value || !editorReady.value) return
  selectedNewSteps.value = []
  addStepVisible.value = true
}

function confirmAddStep() {
  if (!canEditSteps.value || !editorReady.value || !processesReady.value) return
  const newSteps = selectedNewSteps.value.map(pid => {
    const proc = allProcesses.value.find(p => p.id === pid)
    return { process_id: pid, process_name: proc?.name || '', rule_type: 'required', options: [] }
  })
  editableSteps.value.push(...newSteps)
  stepsDirty.value = true
  addStepVisible.value = false
}

function removeStep(index) {
  if (!canEditSteps.value || !editorReady.value) return
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
  if (!canEditRules.value || !editorReady.value || !routeRulesLoaded.value) return
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
  if (!canEditRules.value || !editorReady.value || !routeRulesLoaded.value) return
  step.options.push({ code: '', label: '', skip_process_ids: [] })
  markRulesDirty()
}

function removeDecisionOption(step, index) {
  if (!canEditRules.value || !editorReady.value || !routeRulesLoaded.value) return
  step.options.splice(index, 1)
  markRulesDirty()
}
function handleStepsReordered() {
  if (!canEditSteps.value || !editorReady.value) return
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
  if (canEditRules.value && editorReady.value && routeRulesLoaded.value) rulesDirty.value = true
}
function pathSummary(option) {
  const names = option.skip_process_ids
    .map(id => editableSteps.value.find(step => step.process_id === id)?.process_name)
    .filter(Boolean)
  return names.length ? `跳过 ${names.join('、')}` : '继续后续工序'
}

async function applyConfirmedTemplate() {
  if (!canEditRules.value || !editorReady.value || !routeRulesLoaded.value) return
  const routeId = selectedRoute.value.id
  const selectionVersion = routeSelectionVersion
  try {
    await confirmAction('模板会覆盖当前条件规则，但不会立即保存。', '应用头套网帽模板', { type: 'warning' })
    if (!matchesRouteSelection(routeId, selectionVersion) || !editorReady.value || !routeRulesLoaded.value) return
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
    if (error !== 'cancel' && error !== 'close') msgError(error.message || '模板应用失败', error)
  }
}

function buildRulePayload() {
  if (!routeRulesLoaded.value) throw new Error('条件规则尚未加载，不能保存')
  return editableSteps.value.map(step => validateRouteRule(step, editableSteps.value)).filter(Boolean)
}
function matchesRouteSelection(routeId, selectionVersion) {
  return selectedRoute.value?.id === routeId && routeSelectionVersion === selectionVersion
}
async function reloadSelectedRoute(routeId, selectionVersion) {
  if (!matchesRouteSelection(routeId, selectionVersion)) return false
  stepsDirty.value = false; rulesDirty.value = false; ruleSaveError.value = ''
  await loadRoutes()
  if (!matchesRouteSelection(routeId, selectionVersion)) return false
  const refreshed = routes.value.find(route => route.id === routeId) || selectedRoute.value
  return doSelectRoute(refreshed)
}

function errorDetail(error) {
  return error.response?.data?.detail || error.message || '未知错误'
}
async function saveSteps() {
  if (!editorReady.value || !canEditSteps.value || !stepsDirty.value) return
  let rules = []
  if (canEditRules.value) {
    try {
      rules = buildRulePayload()
    } catch (error) {
      msgWarning(error.message)
      return
    }
  }
  const routeId = selectedRoute.value.id
  const selectionVersion = routeSelectionVersion
  const saveConfiguration = canEditRules.value
  savingSteps.value = true
  try {
    const steps = editableSteps.value.map(s => ({ process_id: s.process_id }))
    if (saveConfiguration) {
      await saveRouteConfiguration({
        save: () => saveDomesticRouteConfiguration(routeId, steps, rules),
        reload: () => reloadSelectedRoute(routeId, selectionVersion),
      })
      msgSuccessText('路线配置已保存')
    } else {
      await api.saveRouteSteps(routeId, steps)
      await reloadSelectedRoute(routeId, selectionVersion)
      msgSuccessText('路线步骤已保存')
    }
  } catch (e) {
    if (!matchesRouteSelection(routeId, selectionVersion)) return
    if (saveConfiguration) {
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
  if (!editorReady.value || !canEditRules.value || !routeRulesLoaded.value || stepsDirty.value || !rulesDirty.value) return
  let rules
  try {
    rules = buildRulePayload()
  } catch (error) {
    msgWarning(error.message)
    return
  }
  savingRules.value = true
  const routeId = selectedRoute.value.id
  const selectionVersion = routeSelectionVersion
  try {
    await saveDomesticRouteRules(routeId, rules)
    await reloadSelectedRoute(routeId, selectionVersion)
    msgSuccessText('条件规则已保存')
  } catch (error) {
    if (matchesRouteSelection(routeId, selectionVersion)) ruleSaveError.value = `条件规则保存失败：${errorDetail(error)}`
  } finally {
    savingRules.value = false
  }
}

watch(() => JSON.stringify([auth.user?.id, auth.roles, auth.permissions]), () => {
  clearSelectedRoute(); routesResource.clear(); processesResource.clear()
  loadRoutes(); loadAllProcesses()
})

onMounted(() => {
  loadRoutes()
  loadAllProcesses()
})
</script>

<style scoped src="./process-route-manage.css"></style>
