<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>战队目标</h2>
      <span class="pg-note">覆盖值优先；未覆盖时按成员汇总 × 系数计算</span>
      <div class="pg-right pg-metric-switch" role="group" aria-label="战队目标指标">
        <button v-for="m in METRICS" :key="m.key" :aria-pressed="metric === m.key" :class="{ 'pg-active': metric === m.key }"
          :disabled="saving || recalcLoading || loading" @click="changeMetric(m.key)">{{ m.name }}</button>
      </div>
    </div>
    <div class="pg-toolbar">
      <span>{{ metricMeta(metric).name }} · {{ metricMeta(metric).unit }} · {{ granularity === 'year' ? '年度' : granularity }}</span>
      <GlassButton v-permission="'perf_goal:write'" :disabled="!canWrite || loading || saving || recalcLoading || !periodId" :loading="recalcLoading" @click="recalc">重算本周期战队目标</GlassButton>
    </div>
    <ListPageStatus v-if="loadError" :error="loadError" :has-data="false" @retry="load" />
    <div class="pg-table-wrap pg-target-table" v-loading="loading" tabindex="0" aria-label="战队目标表，可横向滚动">
      <table class="pg-tbl">
        <thead><tr>
          <th>战队</th><th class="pg-c">成员数</th>
          <th class="pg-r">成员汇总（{{ metricMeta(metric).unit }}）</th><th class="pg-c">加权系数</th>
          <th class="pg-r">覆盖值（{{ metricMeta(metric).unit }}）</th><th class="pg-r">生效目标</th><th>调整留痕</th>
        </tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="teamGoalRowKey(row)">
            <td><b>{{ row.team_name }}</b><small class="pg-note pg-block">队长 {{ row.captain_name }}</small></td>
            <td class="pg-c">{{ row.member_count }}</td>
            <td class="pg-r">{{ fmtMetric(metric, row.auto_value) }}<span v-if="row.stale" class="pg-recalc-flag">待重算</span></td>
            <td class="pg-c">
              <input class="pg-cell-input pg-factor-input" inputmode="decimal" :aria-label="`${row.team_name} ${metricMeta(metric).name}加权系数`"
                :disabled="!canWrite || loading || saving || recalcLoading || !!loadError" :value="factorValue(row)" @input="e => factorDraft[row.department_id] = e.target.value" /> %
            </td>
            <td class="pg-r pg-editable">
              <input class="pg-cell-input" inputmode="decimal" :aria-label="`${row.team_name} ${metricMeta(metric).name}覆盖值`"
                :disabled="!canWrite || loading || saving || recalcLoading || !!loadError" :value="overrideValue(row)" placeholder="未覆盖"
                @input="e => overrideDraft[row.department_id] = e.target.value" />
            </td>
            <td class="pg-r"><b>{{ fmtMetric(metric, row.effective_value) }}</b></td>
            <td class="pg-note">{{ trailOf(row) }}</td>
          </tr>
          <tr v-if="!rows.length && !loading && !loadError"><td colspan="7" class="pg-empty">当前指标暂无战队目标</td></tr>
        </tbody>
      </table>
    </div>
    <div class="pg-toolbar pg-save-bar">
      <GlassButton v-permission="'perf_goal:write'" variant="primary" :loading="saving" :disabled="!canSave" @click="save">保存战队调整{{ dirtyCount ? `（${dirtyCount} 项修改）` : '' }}</GlassButton>
      <span v-if="invalidDraft" class="pg-v-status pg-err">系数需大于 0 且不超过 1000%，覆盖值可留空或填写非负数字</span>
      <span v-else class="pg-note">重算覆盖本周期所有战队和指标，保留系数及覆盖值；调整后留痕。</span>
    </div>
  </div>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { confirmAction, isFeedbackCancelled, msgError, msgSuccessText } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import { perfGoalApi } from '@/api/perfGoal'
import { METRICS, fmtMetric, metricMeta } from '../helpers'
import { isValidGoalInput, selectTeamGoalRows, teamGoalRowKey, teamGoalUpdate } from '../viewState'

const props = defineProps({ periodId: { type: [String, Number], default: null }, granularity: { type: String, default: 'year' }, readonly: Boolean, beforeContextChange: Function })
const emit = defineEmits(['saved'])
const auth = useAuthStore()
const metric = ref('gmv'), allRows = ref([]), loading = ref(false), saving = ref(false), recalcLoading = ref(false), loadError = ref('')
const factorDraft = reactive({}), overrideDraft = reactive({})
const canWrite = computed(() => !props.readonly && auth.hasPermission('perf_goal:write'))
const rows = computed(() => selectTeamGoalRows(allRows.value, metric.value, props.granularity))
const dirtyCount = computed(() => Object.keys(factorDraft).length + Object.keys(overrideDraft).length)
const hasDraft = computed(() => dirtyCount.value > 0)
const invalidDraft = computed(() => Object.values(factorDraft).some(value => !isValidGoalInput(value) || Number(value) <= 0 || Number(value) > 1000)
  || Object.values(overrideDraft).some(value => String(value).trim() !== '' && !isValidGoalInput(value)))
const canSave = computed(() => canWrite.value && hasDraft.value && !invalidDraft.value && !loading.value && !saving.value && !recalcLoading.value && !loadError.value && !!props.periodId)
const isMutating = computed(() => saving.value || recalcLoading.value)
const isBusy = computed(() => loading.value || saving.value || recalcLoading.value)
const factorValue = row => Object.hasOwn(factorDraft, row.department_id) ? factorDraft[row.department_id] : Math.round(Number(row.factor ?? 1) * 10000) / 100
const overrideValue = row => Object.hasOwn(overrideDraft, row.department_id) ? overrideDraft[row.department_id] : row.override_value ?? ''
const trailOf = row => row.updated_by ? `${row.updated_at || ''} ${row.updated_by} 调整` : '—'
function discardDrafts() { for (const draft of [factorDraft, overrideDraft]) Object.keys(draft).forEach(key => delete draft[key]) }
async function changeMetric(key) {
  if (key === metric.value || isBusy.value) return
  if (hasDraft.value && !(await props.beforeContextChange?.())) return
  metric.value = key
}
let request = 0
async function load() {
  const seq = ++request, id = props.periodId
  if (!id) { allRows.value = []; loading.value = false; loadError.value = ''; return }
  loading.value = true; loadError.value = ''
  try {
    const res = await perfGoalApi.teamGoals(id, { granularity: props.granularity }, { suppressToast: true })
    if (seq === request) allRows.value = res.rows || []
  } catch (error) {
    if (seq === request) { allRows.value = []; loadError.value = '战队目标读取失败，请重试' }
  } finally { if (seq === request) loading.value = false }
}
async function save() {
  if (!canSave.value) return false
  const payload = rows.value.filter(row => Object.hasOwn(factorDraft, row.department_id) || Object.hasOwn(overrideDraft, row.department_id))
    .map(row => teamGoalUpdate(row, factorDraft, overrideDraft))
  saving.value = true
  try {
    await perfGoalApi.saveTeamGoals(props.periodId, payload)
    discardDrafts(); msgSuccessText('战队目标已保存'); await load(); emit('saved'); return true
  } catch (error) { msgError('战队目标保存失败，修改已保留', error); return false }
  finally { saving.value = false }
}
async function recalc() {
  if (!canWrite.value || isBusy.value) return
  if (hasDraft.value && !(await props.beforeContextChange?.())) return
  try { await confirmAction('将按最新成员目标重算本周期所有战队和指标，保留已保存的系数及覆盖值。', '重算本周期战队目标', { confirmButtonText: '确认重算', cancelButtonText: '取消', type: 'warning' }) }
  catch (error) { if (!isFeedbackCancelled(error)) msgError('无法确认重算，请重试', error); return }
  recalcLoading.value = true
  try { await perfGoalApi.recalcTeamGoals(props.periodId); msgSuccessText('本周期战队目标已重算'); await load(); emit('saved') }
  catch (error) { msgError('重算失败，请核对后重试', error) }
  finally { recalcLoading.value = false }
}
watch(() => [props.periodId, props.granularity], () => { discardDrafts(); allRows.value = []; load() }, { immediate: true })
defineExpose({ reload: load, save, discardDrafts, hasDraft, dirtyCount, canSave, isBusy, isMutating })
</script>
