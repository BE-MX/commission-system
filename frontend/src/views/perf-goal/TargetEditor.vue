<template>
  <div class="perf-goal-page">
    <div class="pg-card pg-batch-bar">
      <div class="pg-batch-context">
        <template v-if="current">
          <strong>{{ current.name }}</strong>
          <span class="pg-tag" :class="currentIsActive ? 'pg-green' : 'pg-gray'">{{ currentIsActive ? '看板生效中' : current.status === 'archived' ? '已归档' : '草稿' }}</span>
          <span v-if="current.version" class="pg-ver">v{{ current.version }}</span>
          <span v-if="dirtyCount" class="pg-recalc-flag">{{ dirtyCount }} 项修改未保存</span>
        </template>
        <span v-else class="pg-note">{{ loadingPeriods ? '正在读取目标周期…' : periodError ? '目标周期读取失败' : '暂无目标周期' }}</span>
      </div>
      <div class="pg-batch-actions">
        <el-select :model-value="periodId" aria-label="选择目标周期" placeholder="选择周期" class="pg-w-200" :disabled="busy || loadingPeriods" @update:model-value="switchPeriod">
          <el-option v-for="p in periods" :key="p.id" :label="`${p.name}${p.is_active || p.status === 'active' ? '（生效中）' : ''}`" :value="p.id" />
        </el-select>
        <GlassButton v-permission="'perf_goal:write'" :disabled="busy || loadingPeriods" @click="createVisible = true">新建周期</GlassButton>
        <GlassButton v-if="current && !currentIsActive" v-permission="'perf_goal:write'" variant="primary" :loading="activating" :disabled="busy || !!periodError" @click="activate">设为看板生效周期</GlassButton>
      </div>
      <p v-if="current" class="pg-context-note">{{ currentIsActive ? '保存后更新当前生效周期的目标。' : current.status === 'archived' ? '归档周期只读；重新设为看板生效周期后可调整。' : '先录入并保存目标，再设为看板生效周期。' }}人员目标保存后，可检查战队目标并重算。</p>
    </div>
    <ListPageStatus v-if="periodError" :error="periodError" :has-data="false" @retry="loadPeriods(false)" />
    <ListPageStatus v-if="rosterError" :error="rosterError" :has-data="false" @retry="loadRoster" />
    <el-alert v-if="!current && !periodError && !loadingPeriods" type="info" :closable="false" show-icon
      title="先新建年度目标周期，再录入人员目标；保存后可检查战队目标并设为看板生效周期。" />
    <TargetGoalTable ref="goalTable" :period-id="periodId" :roster="roster" :readonly="pageReadonly" :before-context-change="guardPersonChanges" @saved="res => onSaved('person', res)" />
    <TeamGoalPanel ref="teamPanel" :period-id="periodId" :readonly="pageReadonly" :before-context-change="guardTeamChanges" @saved="onSaved('team')" />
    <AuditTrail ref="audits" :period-id="periodId" />

    <el-dialog v-model="createVisible" title="新建目标周期" width="480px">
      <el-form label-position="top">
        <el-form-item label="年度"><el-input-number v-model="createForm.year" :min="2020" :max="2100" class="pg-full-width" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="createForm.name" placeholder="如 2026 年度目标" /></el-form-item>
      </el-form>
      <template #footer>
        <GlassButton :disabled="creating" @click="createVisible = false">取消</GlassButton>
        <GlassButton v-permission="'perf_goal:write'" variant="primary" :loading="creating" @click="createPeriod">创建</GlassButton>
      </template>
    </el-dialog>
    <el-dialog v-model="changesVisible" title="有未保存的目标修改" width="480px" :close-on-click-modal="false" :close-on-press-escape="!savingChanges" :show-close="!savingChanges" @closed="finishChange(false)">
      <p>选择保存或放弃后继续；取消将留在当前内容。</p>
      <p v-if="changesError" class="pg-v-status pg-err" role="alert">{{ changesError }}</p>
      <template #footer>
        <GlassButton :disabled="savingChanges" @click="finishChange(false)">取消切换</GlassButton>
        <GlassButton :disabled="savingChanges" @click="discardAndContinue">放弃修改并继续</GlassButton>
        <GlassButton variant="primary" :disabled="!pendingCanSave" :loading="savingChanges" @click="saveAndContinue">保存并继续</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { confirmAction, isFeedbackCancelled, msgError, msgInfo, msgSuccessText } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import { perfGoalApi } from '@/api/perfGoal'
import { currentBeijingDate } from '@/utils/datetime'
import TargetGoalTable from './components/TargetGoalTable.vue'
import TeamGoalPanel from './components/TeamGoalPanel.vue'
import AuditTrail from './components/AuditTrail.vue'

const auth = useAuthStore()
const periods = ref([]), periodId = ref(null), roster = ref({ teams: [], unassigned: [] })
const goalTable = ref(null), teamPanel = ref(null), audits = ref(null)
const loadingPeriods = ref(true), loadingRoster = ref(true), periodError = ref(''), rosterError = ref('')
const createVisible = ref(false), creating = ref(false), activating = ref(false)
const defaultYear = Number(currentBeijingDate().slice(0, 4))
const createForm = reactive({ year: defaultYear, name: `${defaultYear} 年度目标` })
const current = computed(() => periods.value.find(p => p.id === periodId.value) || null)
const currentIsActive = computed(() => current.value?.is_active || current.value?.status === 'active')
const dirtyCount = computed(() => (goalTable.value?.dirtyCount || 0) + (teamPanel.value?.dirtyCount || 0))
const mutating = computed(() => creating.value || activating.value || savingChanges.value || goalTable.value?.isMutating || teamPanel.value?.isMutating)
const busy = computed(() => creating.value || activating.value || goalTable.value?.isBusy || teamPanel.value?.isBusy || savingChanges.value)
const pageReadonly = computed(() => !auth.hasPermission('perf_goal:write') || !current.value || current.value.status === 'archived' || !!periodError.value || !!rosterError.value || loadingPeriods.value || loadingRoster.value || activating.value)

async function loadPeriods(preferActive = true) {
  loadingPeriods.value = true; periodError.value = ''
  try {
    const res = await perfGoalApi.periods({ suppressToast: true })
    periods.value = res.periods || res.rows || res.items || (Array.isArray(res) ? res : [])
    if (preferActive || !periods.value.some(p => p.id === periodId.value)) periodId.value = (preferActive ? periods.value.find(p => p.is_active || p.status === 'active')?.id : null) ?? periods.value[0]?.id ?? null
  } catch (error) { periodError.value = '目标周期读取失败，请重试' }
  finally { loadingPeriods.value = false }
}
async function loadRoster() {
  loadingRoster.value = true; rosterError.value = ''
  try { roster.value = await perfGoalApi.roster({ suppressToast: true }) }
  catch (error) { rosterError.value = '人员名单读取失败，请重试' }
  finally { loadingRoster.value = false }
}
const changesVisible = ref(false), savingChanges = ref(false), changesError = ref(''), pendingSources = ref([])
let resolveChange = null
const pendingCanSave = computed(() => pendingSources.value.every(source => !source?.hasDraft || source.canSave))
function guardChanges(sources = [goalTable.value, teamPanel.value]) {
  if (mutating.value) { msgInfo('目标正在保存或应用，请等待完成后再切换'); return Promise.resolve(false) }
  if (changesVisible.value) return Promise.resolve(false)
  const pending = sources.filter(source => source?.hasDraft)
  if (!pending.length) return Promise.resolve(true)
  pendingSources.value = pending; changesError.value = ''; changesVisible.value = true
  return new Promise(resolve => { resolveChange = resolve })
}
const guardPersonChanges = () => guardChanges([goalTable.value])
const guardTeamChanges = () => guardChanges([teamPanel.value])
function finishChange(allow) {
  const resolve = resolveChange; resolveChange = null; changesVisible.value = false
  pendingSources.value = []; resolve?.(allow)
}
function discardAndContinue() { pendingSources.value.forEach(source => source.discardDrafts()); finishChange(true) }
async function saveAndContinue() {
  if (!pendingCanSave.value || savingChanges.value) return
  savingChanges.value = true; changesError.value = ''
  try {
    for (const source of pendingSources.value) if (source.hasDraft && !(await source.save())) { changesError.value = '尚未保存成功，修改已保留。请重试或取消切换。'; return }
    finishChange(true)
  } catch (error) { changesError.value = '保存失败，修改已保留，请取消切换后重试'; msgError(changesError.value, error) }
  finally { savingChanges.value = false }
}
async function switchPeriod(id) { if (id !== periodId.value && await guardChanges()) periodId.value = id }
async function createPeriod() {
  if (!auth.hasPermission('perf_goal:write') || creating.value || !(await guardChanges())) return
  creating.value = true
  try {
    const res = await perfGoalApi.createPeriod({ year: createForm.year, name: createForm.name })
    msgSuccessText('周期已创建'); createVisible.value = false
    await loadPeriods(false); periodId.value = res.id ?? periodId.value
  } catch (error) { msgError('周期创建失败，请核对后重试', error) }
  finally { creating.value = false }
}
async function activate() {
  if (!auth.hasPermission('perf_goal:write') || !(await guardChanges())) return
  try { await confirmAction(`将「${current.value.name}」设为看板生效周期；原生效周期将归档。`, '切换看板生效周期', { confirmButtonText: '确认设为生效周期', cancelButtonText: '取消', type: 'warning' }) }
  catch (error) { if (!isFeedbackCancelled(error)) msgError('无法确认周期切换，请重试', error); return }
  activating.value = true
  try { await perfGoalApi.activatePeriod(periodId.value); msgSuccessText('看板生效周期已更新'); await loadPeriods(false) }
  catch (error) { msgError('周期激活失败，请核对后重试', error) }
  finally { activating.value = false }
}
function onSaved(source, res) {
  if (source === 'person') { if (!savingChanges.value || !teamPanel.value?.hasDraft) teamPanel.value?.reload(); if (current.value && res?.version) current.value.version = res.version }
  audits.value?.reload()
}
function beforeUnload(event) { if (dirtyCount.value || mutating.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(() => guardChanges())
onMounted(() => { loadPeriods(); loadRoster(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => { finishChange(false); window.removeEventListener('beforeunload', beforeUnload) })
</script>
<style src="./perf-goal.css"></style>
