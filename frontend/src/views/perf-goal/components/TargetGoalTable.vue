<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>人员目标编辑</h2>
      <span class="pg-note">按战队分组，修改后保存到当前周期</span>
      <div class="pg-right">
        <div class="pg-seg">
          <button v-for="g in granOptions" :key="g.key" :class="{ 'pg-active': granularity === g.key }" :disabled="loading || saving || splitLoading" :aria-pressed="granularity === g.key" @click="changeGranularity(g.key)">{{ g.name }}</button>
        </div>
      </div>
    </div>
    <div class="pg-toolbar pg-person-find">
      <el-input v-model="personQuery" clearable placeholder="查找姓名或战队" aria-label="查找目标人员" class="pg-find-input" @keydown.esc="personQuery = ''" @keydown.enter.prevent="focusFirstMatch" />
      <span v-if="personQuery.trim()" class="pg-note" role="status">显示 {{ visiblePersonCount }} / {{ personCount }} 人</span>
    </div>
    <div class="pg-toolbar">
      <GlassButton v-permission="'perf_goal:write'" :disabled="!canWrite || !periodId || !ready || loading || saving" @click="openSplit">拆分目标</GlassButton>
      <GlassButton :disabled="!periodId || loading" @click="runValidate">检查拆分合计</GlassButton>
      <span class="pg-v-status" :class="invalidCount ? 'pg-err' : issues.length ? 'pg-warn' : 'pg-ok'">{{ validateText }}</span>
      <GlassButton v-if="issues.length" variant="link" :aria-expanded="issuesExpanded" @click="issuesExpanded = !issuesExpanded">{{ issuesExpanded ? '收起差异' : '查看差异' }}</GlassButton>
    </div>
    <ul v-if="issuesExpanded && issues.length" class="pg-validation-list" aria-label="拆分差异列表">
      <li v-for="item in issues" :key="item.userId"><button @click="focusPerson(item.userId)">{{ item.name }}：{{ issueLabel }}与年度差 {{ fmtMetric(subMetric, item.diff) }}</button></li>
    </ul>
    <ListPageStatus v-if="loadError" :error="loadError" :has-data="false" @retry="load" />
    <div v-if="granularity !== 'year'" role="group" aria-label="人员目标指标" class="pg-seg" style="margin-bottom:12px">
      <button v-for="m in METRICS" :key="m.key" :aria-pressed="subMetric === m.key" :class="{ 'pg-active': subMetric === m.key }" @click="subMetric = m.key">{{ m.name }}</button>
    </div>

    <div ref="tableWrap" class="pg-table-wrap pg-target-table" v-loading="loading" tabindex="0" aria-label="人员目标表，可横向滚动">
      <!-- 年度粒度 -->
      <table v-if="granularity === 'year'" class="pg-tbl">
        <thead>
          <tr>
            <th>姓名</th>
            <th v-for="m in METRICS" :key="m.key" class="pg-r">{{ m.name }} 年度（{{ m.unit }}）</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in visibleGroups" :key="group.name">
            <tr class="pg-group-head">
              <td>{{ group.name }}（队长 {{ group.captain_name }}）</td>
              <td v-for="m in METRICS" :key="m.key" class="pg-r">全队小计 {{ fmtMetric(m.key, groupSubtotal(group, m.key)) }}</td>
            </tr>
            <tr v-for="p in group.members" :key="p.user_id ?? p.okki_user_id ?? p.name" :data-person-id="p.user_id" :class="{ 'pg-row-dim': !canEditGoalPerson(p) }">
              <td>
                <b>{{ p.name }}</b>
                <span v-if="p.is_captain" class="pg-tag pg-blue">队长</span>
                <span v-if="isUnlisted(p)" class="pg-tag pg-gray">未设目标</span>
              </td>
              <template v-if="!canEditGoalPerson(p)"><td :colspan="METRICS.length" class="pg-note">未绑定账号，暂不能设置目标</td></template>
              <template v-else>
                <td v-for="m in METRICS" :key="m.key" class="pg-r pg-editable">
                  <input class="pg-cell-input" inputmode="decimal" :aria-label="`${p.name} ${m.name}年度目标`" :disabled="!canWrite || loading || saving || !ready" :aria-invalid="invalidKey(yearKey(p, m.key))" :class="{ 'pg-unset-input': displayValue(yearKey(p, m.key)) === '' }" placeholder="输入目标" :value="displayValue(yearKey(p, m.key))" @input="e => edit(yearKey(p, m.key), e.target.value)" />
                </td>
              </template>
            </tr>
          </template>
        </tbody>
      </table>

      <!-- 季度 / 月度粒度 -->
      <table v-else class="pg-tbl">
        <thead>
          <tr>
            <th>姓名</th><th class="pg-r">年度</th>
            <th v-for="h in childHeaders" :key="h.label" class="pg-r">{{ h.label }}</th>
            <th>校验状态</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in visibleGroups" :key="group.name">
            <tr class="pg-group-head">
              <td>{{ group.name }}（队长 {{ group.captain_name }}）</td>
              <td class="pg-r">全队小计 {{ fmtMetric(subMetric, groupSubtotal(group, subMetric)) }}</td>
              <td v-for="h in childHeaders" :key="h.label" class="pg-r">全队小计 {{ fmtMetric(subMetric, groupChildSubtotal(group, h.index)) }}</td>
              <td></td>
            </tr>
            <tr v-for="p in group.members" :key="p.user_id ?? p.okki_user_id ?? p.name" :data-person-id="p.user_id" :class="{ 'pg-row-dim': !canEditGoalPerson(p) }">
              <td><b>{{ p.name }}</b><span v-if="isUnlisted(p)" class="pg-tag pg-gray"> 未设目标</span></td>
              <td class="pg-r">{{ !canEditGoalPerson(p) ? '—' : fmtMetric(subMetric, valueOf(yearKey(p, subMetric))) }}</td>
              <template v-if="!canEditGoalPerson(p)">
                <td :colspan="childHeaders.length + 1" class="pg-note">未绑定账号，暂不能设置目标</td>
              </template>
              <template v-else>
                <td v-for="h in childHeaders" :key="h.label" class="pg-r pg-editable" :class="{ 'pg-cell-warning': issueOf(p) }">
                  <input class="pg-cell-input" inputmode="decimal" :aria-label="`${p.name} ${metricMeta(subMetric).name} ${h.label}目标`" :disabled="!canWrite || loading || saving || !ready" :aria-invalid="invalidKey(childKey(p, h.index))" :class="{ 'pg-unset-input': displayValue(childKey(p, h.index)) === '' }" placeholder="输入目标" :value="displayValue(childKey(p, h.index))" @input="e => edit(childKey(p, h.index), e.target.value)" />
                </td>
                <td>
                  <span v-if="issueOf(p)" class="pg-cell-difference">{{ issueLabel }}之和 ≠ 年度，差异 {{ issueOf(p).diff > 0 ? '+' : '' }}{{ fmtMetric(subMetric, issueOf(p).diff) }}</span>
                  <span v-else class="pg-tag pg-green">通过</span>
                </td>
              </template>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-if="!visibleGroups.length && personQuery.trim()" class="pg-empty">未找到匹配的人员或战队。<GlassButton variant="link" @click="personQuery = ''">清空查找</GlassButton></div>
    </div>

    <div class="pg-toolbar pg-save-bar">
      <GlassButton v-permission="'perf_goal:write'" variant="primary" :loading="saving" :disabled="!canSave" @click="save">保存人员目标{{ dirtyCount ? `（${dirtyCount} 项修改）` : '' }}</GlassButton>
      <span v-if="personQuery.trim() && dirtyCount" class="pg-note">保存包含全部 {{ dirtyCount }} 项修改，包括查找范围外的修改。</span>
      <span class="pg-note">{{ invalidCount ? `有 ${invalidCount} 个输入无效，请填写非负数字` : granNote }}</span>
    </div>

    <!-- 一键拆分预览 -->
    <el-dialog v-model="splitVisible" title="拆分目标" width="760px" :close-on-click-modal="!applyingSplit" :close-on-press-escape="!applyingSplit" :show-close="!applyingSplit">
      <div class="pg-toolbar">
        <label class="pg-note">指标</label>
        <el-select v-model="splitForm.metric" :disabled="splitLoading" class="pg-w-130">
          <el-option v-for="m in METRICS" :key="m.key" :label="m.name" :value="m.key" />
        </el-select>
        <label class="pg-note">方向</label>
        <el-select v-model="splitDirection" :disabled="splitLoading" class="pg-w-170">
          <el-option label="年度 → 季度" value="year:quarter" />
          <el-option label="季度 → 月度" value="quarter:month" />
        </el-select>
        <el-button type="primary" :loading="splitLoading" @click="previewSplit">生成预览</el-button>
      </div>
      <div v-if="splitPreview.length" class="pg-table-wrap" style="max-height:360px;overflow-y:auto">
        <table class="pg-tbl">
          <thead>
            <tr><th>姓名</th><th v-for="h in splitEntryHeaders" :key="h" class="pg-r">{{ h }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in splitPreview" :key="row.user_id">
              <td>{{ row.user_name }}</td>
              <td v-for="(e, i) in row.entries" :key="i" class="pg-r">
                <span v-if="e && e.old_value != null && e.old_value !== e.new_value" style="color:var(--pg-faint);text-decoration:line-through;margin-right:4px">{{ fmtMetric(splitForm.metric, e.old_value) }}</span>
                <b v-if="e">{{ fmtMetric(splitForm.metric, e.new_value) }}</b><span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <el-empty v-else-if="splitLoaded" description="没有需要拆分的目标（请先设置父级目标）" :image-size="80" />
      <template #footer>
        <el-button :disabled="applyingSplit" @click="splitVisible = false">取消</el-button>
        <el-button v-permission="'perf_goal:write'" type="primary" :disabled="!splitPreview.length || !canWrite" :loading="splitLoading" @click="applySplit">确认应用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { msgError, msgSuccessText, msgWarning } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import { canEditGoalPerson, isValidGoalInput, childGoalKey, splitPreviewByPerson } from '../viewState'
import { findTargetGroups } from '../displayText'
import { perfGoalApi } from '@/api/perfGoal'
import {
  METRICS, SEASON_WEIGHTS, fmtMetric, goalKey, indexGoalRows,
  goalRowsFromEdits, validateChildSum, metricMeta,
} from '../helpers'

const props = defineProps({
  periodId: { type: [String, Number], default: null },
  roster: { type: Object, default: () => ({ teams: [], unassigned: [] }) },
  readonly: Boolean,
  beforeContextChange: Function,
})
const emit = defineEmits(['saved'])
const auth = useAuthStore()
const canWrite = computed(() => !props.readonly && auth.hasPermission('perf_goal:write'))
const ready = ref(false), loadError = ref(''), issuesExpanded = ref(false), tableWrap = ref(null)

const granOptions = [{ key: 'year', name: '年度' }, { key: 'quarter', name: '季度' }, { key: 'month', name: '月度' }]
const granularity = ref('year')
const subMetric = ref('gmv')
const loading = ref(false), saving = ref(false)
const yearMap = ref(new Map()), childMap = ref(new Map())
const edits = reactive({})
const validated = ref(false), personQuery = ref('')

const groups = computed(() => {
  const list = (props.roster.teams || []).map(t => ({
    name: t.name, captain_name: t.captain_name, members: t.members || [],
  }))
  if (props.roster.unassigned?.length) list.push({ name: '未分组', captain_name: '—', members: props.roster.unassigned })
  return list
})
const visibleGroups = computed(() => findTargetGroups(groups.value, personQuery.value))
const personCount = computed(() => groups.value.reduce((count, group) => count + group.members.length, 0))
const visiblePersonCount = computed(() => visibleGroups.value.reduce((count, group) => count + group.members.length, 0))
function focusFirstMatch() { const person = visibleGroups.value.flatMap(group => group.members).find(canEditGoalPerson); if (person) focusPerson(person.user_id, false) }
const childHeaders = computed(() =>
  granularity.value === 'quarter'
    ? [1, 2, 3, 4].map(q => ({ label: `Q${q}`, index: q }))
    : Array.from({ length: 12 }, (_, i) => ({ label: `${i + 1}月`, index: i + 1 })))
const granNote = computed(() => ({
  year: '年度目标保存后，可按需拆分至季度、月度。',
  quarter: `${metricMeta(subMetric.value).name} · ${metricMeta(subMetric.value).unit} · Q1–Q4 合计与年度对照，差异仅提示、不阻止保存。`,
  month: `${metricMeta(subMetric.value).name} · ${metricMeta(subMetric.value).unit} · 1–12 月合计与年度对照，差异仅提示、不阻止保存。`,
}[granularity.value]))
const issueLabel = computed(() => (granularity.value === 'quarter' ? 'Q列' : '月度'))

const yearKey = (p, metric) => goalKey(p.user_id, metric, 'year', null, null)
const childKey = (p, index) => childGoalKey(p.user_id, subMetric.value, granularity.value, index)

const valueOf = key => baseValue(key)
function baseValue(key) {
  const [, , gran] = key.split('|')
  const map = gran === 'year' ? yearMap.value : childMap.value
  return key in edits ? edits[key] : map.get(key)
}
function displayValue(key) {
  const v = baseValue(key)
  return v == null ? '' : v
}
function edit(key, raw) {
  const v = Number(raw)
  if (!canWrite.value || !ready.value || saving.value) return
  const [, , gran] = key.split('|')
  const original = (gran === 'year' ? yearMap.value : childMap.value).get(key)
  if (isValidGoalInput(raw) && original != null && v === Number(original)) delete edits[key]
  else edits[key] = raw
  validated.value = true
}
const dirtyCount = computed(() => Object.keys(edits).length)
const hasDraft = computed(() => dirtyCount.value > 0)
const invalidKey = key => Object.hasOwn(edits, key) && !isValidGoalInput(edits[key])
const invalidCount = computed(() => Object.keys(edits).filter(invalidKey).length)
const canSave = computed(() => canWrite.value && ready.value && hasDraft.value && !invalidCount.value && !saving.value && !loading.value && !!props.periodId)
const isMutating = computed(() => saving.value || applyingSplit.value)
const isBusy = computed(() => saving.value || loading.value || splitLoading.value)
function discardDrafts() { Object.keys(edits).forEach(key => delete edits[key]); validated.value = false }
function isUnlisted(person) { return canEditGoalPerson(person) && !METRICS.some(m => yearMap.value.has(yearKey(person, m.key)) || isValidGoalInput(edits[yearKey(person, m.key)])) }
async function focusPerson(id, reveal = true) {
  if (reveal) personQuery.value = ''
  await nextTick()
  const row = tableWrap.value?.querySelector(`[data-person-id="${Number(id)}"]`)
  row?.scrollIntoView({ block: 'nearest', inline: 'start' }); row?.querySelector('input')?.focus({ preventScroll: true })
}


function issueOf(p) {
  const parent = Number(baseValue(yearKey(p, subMetric.value))) || 0
  const children = childHeaders.value.map(h => Number(baseValue(childKey(p, h.index))) || 0)
  return validateChildSum(parent, children)
}
const issues = computed(() => {
  if (granularity.value === 'year') return []
  const out = []
  groups.value.forEach(g => g.members.forEach(p => {
    if (!canEditGoalPerson(p)) return
    const issue = issueOf(p)
    if (issue) out.push({ name: p.name, userId: p.user_id, ...issue })
  }))
  return out
})
const validateText = computed(() => {
  if (invalidCount.value) return `${invalidCount.value} 个输入无效`
  if (granularity.value === 'year') return validated.value ? '年度目标已检查；可继续设置季度或月度' : ''
  return issues.value.length ? `${issues.value.length} 人拆分合计与年度不一致` : '拆分合计与年度一致'
})
function runValidate() { validated.value = true }

function groupSubtotal(group, metric) {
  return (group.allMembers || group.members).filter(canEditGoalPerson)
    .reduce((a, p) => a + (Number(baseValue(goalKey(p.user_id, metric, 'year', null, null))) || 0), 0)
}
function groupChildSubtotal(group, index) {
  return (group.allMembers || group.members).filter(canEditGoalPerson)
    .reduce((a, p) => a + (Number(baseValue(childKey(p, index))) || 0), 0)
}

let request = 0
async function load() {
  const seq = ++request, id = props.periodId, gran = granularity.value
  if (!id) { yearMap.value = new Map(); childMap.value = new Map(); ready.value = false; loading.value = false; return }
  loading.value = true; ready.value = false; loadError.value = ''
  try {
    const [yearRes, childRes] = await Promise.all([
      perfGoalApi.goals(id, { granularity: 'year' }, { suppressToast: true }),
      gran === 'year' ? Promise.resolve({ rows: [] }) : perfGoalApi.goals(id, { granularity: gran }, { suppressToast: true }),
    ])
    if (seq !== request) return
    yearMap.value = indexGoalRows(yearRes.rows); childMap.value = indexGoalRows(childRes.rows); ready.value = true
  } catch (error) { if (seq === request) loadError.value = '人员目标读取失败，请重试；未保存修改仍保留' }
  finally { if (seq === request) loading.value = false }
}
function changeGranularity(g) { if (isBusy.value) return; granularity.value = g; issuesExpanded.value = false; load() }
async function save() {
  if (!canSave.value) return false
  const rows = goalRowsFromEdits(edits)
  saving.value = true
  try {
    const res = await perfGoalApi.saveGoals(props.periodId, rows)
    discardDrafts(); msgSuccessText(`已保存人员目标（版本 v${res.version ?? '—'}）`)
    await load(); emit('saved', res); return true
  } catch (error) { msgError('人员目标保存失败，修改已保留', error); return false }
  finally { saving.value = false }
}

/* ---------------- 一键拆分 ---------------- */
const splitVisible = ref(false), splitLoading = ref(false), splitLoaded = ref(false), applyingSplit = ref(false), previewContext = ref(null)
let previewRequest = 0
const splitPreview = ref([])
const splitForm = reactive({ metric: 'gmv' })
const splitDirection = ref('year:quarter')
const splitEntryHeaders = computed(() =>
  splitDirection.value === 'year:quarter' ? ['Q1', 'Q2', 'Q3', 'Q4'] : Array.from({ length: 12 }, (_, i) => `${i + 1}月`))

async function openSplit() {
  if (!canWrite.value || !ready.value || isBusy.value) return
  if (hasDraft.value && !(await props.beforeContextChange?.())) return
  splitPreview.value = []; splitLoaded.value = false; splitVisible.value = true
}

const splitSignature = () => JSON.stringify([props.periodId, splitForm.metric, splitDirection.value])
watch(() => [props.periodId, splitForm.metric, splitDirection.value], () => {
  ++previewRequest; previewContext.value = null; splitPreview.value = []; splitLoaded.value = false; splitLoading.value = false
})
async function previewSplit() {
  if (!canWrite.value || splitLoading.value) return
  const seq = ++previewRequest, signature = splitSignature(), id = props.periodId
  const [source, target] = splitDirection.value.split(':')
  const payload = { metric: splitForm.metric, source, target, weights: source === 'year' ? SEASON_WEIGHTS : [1, 1, 1] }
  splitLoading.value = true; splitPreview.value = []; previewContext.value = null
  try {
    const res = await perfGoalApi.splitGoals(id, { ...payload, apply: false })
    if (seq !== previewRequest || signature !== splitSignature()) return
    splitPreview.value = splitPreviewByPerson(res.preview || [], target)
    previewContext.value = { signature, periodId: id, payload }; splitLoaded.value = true
  } catch (error) { if (seq === previewRequest) { splitLoaded.value = false; msgError('拆分预览读取失败，请重试；未应用任何拆分', error) } }
  finally { if (seq === previewRequest) splitLoading.value = false }
}
async function applySplit() {
  const context = previewContext.value
  if (!canWrite.value || !splitPreview.value.length || splitLoading.value || !context || context.signature !== splitSignature()) return
  applyingSplit.value = true; splitLoading.value = true
  try {
    const res = await perfGoalApi.splitGoals(context.periodId, { ...context.payload, apply: true })
    msgSuccessText('拆分已应用'); splitVisible.value = false; await load(); emit('saved', res)
  } catch (error) { msgError('拆分应用失败，请核对后重试', error) }
  finally { applyingSplit.value = false; splitLoading.value = false }
}

watch(() => props.periodId, () => {
  discardDrafts(); yearMap.value = new Map(); childMap.value = new Map(); issuesExpanded.value = false
  load()
}, { immediate: true })
defineExpose({ reload: load, save, discardDrafts, hasDraft, dirtyCount, canSave, isBusy, isMutating })
</script>
