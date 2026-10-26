<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>人员目标编辑</h2>
      <span class="pg-note">按战队分组；编辑暂存本地，点击「保存」后生效</span>
      <div class="pg-right">
        <div class="pg-seg">
          <button v-for="g in granOptions" :key="g.key" :class="{ 'pg-active': granularity === g.key }" @click="changeGranularity(g.key)">{{ g.name }}</button>
        </div>
      </div>
    </div>
    <div class="pg-toolbar">
      <el-button type="primary" :disabled="!periodId" @click="openSplit">一键拆分</el-button>
      <el-button :disabled="!periodId" @click="runValidate">校验：子项之和 = 父项</el-button>
      <span class="pg-v-status" :class="issues.length ? 'pg-err' : 'pg-ok'">{{ validateText }}</span>
      <span style="margin-left:auto" class="pg-note">{{ granNote }}</span>
      <el-button type="primary" :loading="saving" :disabled="!dirtyCount || !periodId" @click="save">
        保存{{ dirtyCount ? `（${dirtyCount} 项修改）` : '' }}
      </el-button>
    </div>

    <div v-if="granularity !== 'year'" class="pg-seg" style="margin-bottom:12px">
      <button v-for="m in METRICS" :key="m.key" :class="{ 'pg-active': subMetric === m.key }" @click="subMetric = m.key">{{ m.name }}</button>
    </div>

    <div class="pg-table-wrap" v-loading="loading">
      <!-- 年度粒度 -->
      <table v-if="granularity === 'year'" class="pg-tbl">
        <thead>
          <tr>
            <th>姓名</th>
            <th v-for="m in METRICS" :key="m.key" class="pg-r">{{ m.name }} 年度（{{ m.unit }}）</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in groups" :key="group.name">
            <tr class="pg-group-head">
              <td>{{ group.name }}（队长 {{ group.captain_name }}）</td>
              <td v-for="m in METRICS" :key="m.key" class="pg-r">小计 {{ fmtMetric(m.key, groupSubtotal(group, m.key)) }}</td>
            </tr>
            <tr v-for="p in group.members" :key="p.user_id" :class="{ 'pg-row-dim': p.listed === false }">
              <td>
                <b>{{ p.name }}</b>
                <span v-if="p.is_captain" class="pg-tag pg-blue">队长</span>
                <span v-if="p.listed === false" class="pg-tag pg-gray">未设目标</span>
              </td>
              <template v-if="p.listed === false"><td v-for="m in METRICS" :key="m.key" class="pg-r">—</td></template>
              <template v-else>
                <td v-for="m in METRICS" :key="m.key" class="pg-r pg-editable">
                  <input class="pg-cell-input" :value="displayValue(yearKey(p, m.key))" @change="e => edit(yearKey(p, m.key), e.target.value)" />
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
          <template v-for="group in groups" :key="group.name">
            <tr class="pg-group-head">
              <td>{{ group.name }}（队长 {{ group.captain_name }}）</td>
              <td class="pg-r">小计 {{ fmtMetric(subMetric, groupSubtotal(group, subMetric)) }}</td>
              <td v-for="h in childHeaders" :key="h.label" class="pg-r">小计 {{ fmtMetric(subMetric, groupChildSubtotal(group, h.index)) }}</td>
              <td></td>
            </tr>
            <tr v-for="p in group.members" :key="p.user_id" :class="{ 'pg-row-dim': p.listed === false }">
              <td><b>{{ p.name }}</b><span v-if="p.listed === false" class="pg-tag pg-gray"> 未设目标</span></td>
              <td class="pg-r">{{ p.listed === false ? '—' : fmtMetric(subMetric, valueOf(yearKey(p, subMetric))) }}</td>
              <template v-if="p.listed === false">
                <td v-for="h in childHeaders" :key="h.label" class="pg-r">—</td><td>—</td>
              </template>
              <template v-else>
                <td v-for="h in childHeaders" :key="h.label" class="pg-r pg-editable" :class="{ 'pg-cell-err': issueOf(p) }">
                  <input class="pg-cell-input" :value="displayValue(childKey(p, h.index))" @change="e => edit(childKey(p, h.index), e.target.value)" />
                </td>
                <td>
                  <span v-if="issueOf(p)" class="pg-cell-err-msg">{{ issueLabel }}之和 ≠ 年度，差异 {{ issueOf(p).diff > 0 ? '+' : '' }}{{ fmtMetric(subMetric, issueOf(p).diff) }}</span>
                  <span v-else class="pg-tag pg-green">通过</span>
                </td>
              </template>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- 一键拆分预览 -->
    <el-dialog v-model="splitVisible" title="一键拆分" width="760px">
      <div class="pg-toolbar">
        <label class="pg-note">指标</label>
        <el-select v-model="splitForm.metric" class="pg-w-130">
          <el-option v-for="m in METRICS" :key="m.key" :label="m.name" :value="m.key" />
        </el-select>
        <label class="pg-note">方向</label>
        <el-select v-model="splitDirection" class="pg-w-170">
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
                <span v-if="e.old_value != null && e.old_value !== e.new_value" style="color:var(--pg-faint);text-decoration:line-through;margin-right:4px">{{ fmtMetric(splitForm.metric, e.old_value) }}</span>
                <b>{{ fmtMetric(splitForm.metric, e.new_value) }}</b>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <el-empty v-else-if="splitLoaded" description="没有需要拆分的目标（请先设置父级目标）" :image-size="80" />
      <template #footer>
        <el-button @click="splitVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!splitPreview.length" :loading="splitLoading" @click="applySplit">确认应用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { msgSuccessText, msgWarning } from '@/utils/feedback'
import { perfGoalApi } from '@/api/perfGoal'
import {
  METRICS, SEASON_WEIGHTS, fmtMetric, goalKey, indexGoalRows,
  goalRowsFromEdits, validateChildSum, splitYearToQuarters, splitQuarterToMonths, metricMeta,
} from '../helpers'

const props = defineProps({
  periodId: { type: [String, Number], default: null },
  roster: { type: Object, default: () => ({ teams: [], unassigned: [] }) },
})
const emit = defineEmits(['saved'])

const granOptions = [{ key: 'year', name: '年度' }, { key: 'quarter', name: '季度' }, { key: 'month', name: '月度' }]
const granularity = ref('year')
const subMetric = ref('gmv')
const loading = ref(false), saving = ref(false)
const yearMap = ref(new Map()), childMap = ref(new Map())
const edits = reactive({})
const validated = ref(false)

const groups = computed(() => {
  const list = (props.roster.teams || []).map(t => ({
    name: t.name, captain_name: t.captain_name, members: t.members || [],
  }))
  if (props.roster.unassigned?.length) list.push({ name: '未分组', captain_name: '—', members: props.roster.unassigned })
  return list
})
const childHeaders = computed(() =>
  granularity.value === 'quarter'
    ? [1, 2, 3, 4].map(q => ({ label: `Q${q}`, index: q }))
    : Array.from({ length: 12 }, (_, i) => ({ label: `${i + 1}月`, index: i + 1 })))
const granNote = computed(() => ({
  year: '年度粒度：每指标一列，可直接编辑；修改后季度/月度拆分需重新「一键拆分」',
  quarter: `季度粒度：当前指标 = ${metricMeta(subMetric.value).name}（Q1-Q4 可编辑，校验：Q列之和 = 年度）`,
  month: `月度粒度：当前指标 = ${metricMeta(subMetric.value).name}（M1-M12 可编辑，校验：月度之和 = 年度）`,
}[granularity.value]))
const issueLabel = computed(() => (granularity.value === 'quarter' ? 'Q列' : '月度'))

const yearKey = (p, metric) => goalKey(p.user_id, metric, 'year', null, null)
const childKey = (p, index) =>
  granularity.value === 'quarter'
    ? goalKey(p.user_id, subMetric.value, 'quarter', index, null)
    : goalKey(p.user_id, subMetric.value, 'month', null, index)

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
  if (raw === '' || Number.isNaN(v) || v < 0) { msgWarning('请输入非负数字'); return }
  edits[key] = v
  validated.value = true
}
const dirtyCount = computed(() => Object.keys(edits).length)

function issueOf(p) {
  const parent = Number(baseValue(yearKey(p, subMetric.value))) || 0
  const children = childHeaders.value.map(h => Number(baseValue(childKey(p, h.index))) || 0)
  return validateChildSum(parent, children)
}
const issues = computed(() => {
  if (granularity.value === 'year') return []
  const out = []
  groups.value.forEach(g => g.members.forEach(p => {
    if (p.listed === false) return
    const issue = issueOf(p)
    if (issue) out.push({ name: p.name, ...issue })
  }))
  return out
})
const validateText = computed(() => {
  if (granularity.value === 'year') return validated.value ? '✓ 年度粒度无需校验（切换到季度/月度粒度校验拆分）' : ''
  return issues.value.length
    ? `✕ ${issues.value.length} 行${issueLabel.value}之和 ≠ 年度：${issues.value.map(i => `${i.name}（差异 ${i.diff > 0 ? '+' : ''}${fmtMetric(subMetric.value, i.diff)}）`).join('、')}`
    : `✓ 校验通过：全部行 ${issueLabel.value}之和 = 年度`
})
function runValidate() { validated.value = true }

function groupSubtotal(group, metric) {
  return group.members.filter(p => p.listed !== false)
    .reduce((a, p) => a + (Number(baseValue(goalKey(p.user_id, metric, 'year', null, null))) || 0), 0)
}
function groupChildSubtotal(group, index) {
  return group.members.filter(p => p.listed !== false)
    .reduce((a, p) => a + (Number(baseValue(childKey(p, index))) || 0), 0)
}

async function load() {
  if (!props.periodId) { yearMap.value = new Map(); childMap.value = new Map(); return }
  loading.value = true
  try {
    const yearRes = await perfGoalApi.goals(props.periodId, { granularity: 'year' }, { suppressToast: true })
    yearMap.value = indexGoalRows(yearRes.rows)
    if (granularity.value !== 'year') {
      const childRes = await perfGoalApi.goals(props.periodId, { granularity: granularity.value }, { suppressToast: true })
      childMap.value = indexGoalRows(childRes.rows)
    } else {
      childMap.value = new Map()
    }
  } finally {
    loading.value = false
  }
}
function changeGranularity(g) { granularity.value = g; load() }

async function save() {
  const rows = goalRowsFromEdits(edits)
  if (!rows.length) return
  saving.value = true
  try {
    const res = await perfGoalApi.saveGoals(props.periodId, rows)
    Object.keys(edits).forEach(k => delete edits[k])
    msgSuccessText(`已保存（版本 v${res.version ?? '—'} · 留痕 ${res.audit_count ?? rows.length} 条）`)
    await load()
    emit('saved')
  } finally {
    saving.value = false
  }
}

/* ---------------- 一键拆分 ---------------- */
const splitVisible = ref(false), splitLoading = ref(false), splitLoaded = ref(false)
const splitPreview = ref([])
const splitForm = reactive({ metric: 'gmv' })
const splitDirection = ref('year:quarter')
const splitEntryHeaders = computed(() =>
  splitDirection.value === 'year:quarter' ? ['Q1', 'Q2', 'Q3', 'Q4'] : Array.from({ length: 12 }, (_, i) => `${i + 1}月`))

function openSplit() { splitPreview.value = []; splitLoaded.value = false; splitVisible.value = true }

/** 本地按权重计算预览（与后端 split apply=false 同规则），再交后端确认 */
function localPreview() {
  const [source, target] = splitDirection.value.split(':')
  const integer = !metricMeta(splitForm.metric).money
  const rows = []
  groups.value.forEach(g => g.members.forEach(p => {
    if (p.listed === false) return
    if (source === 'year') {
      const parent = Number(baseValue(goalKey(p.user_id, splitForm.metric, 'year', null, null)))
      if (!parent) return
      const values = splitYearToQuarters(parent, { integer, weights: SEASON_WEIGHTS })
      rows.push({
        user_id: p.user_id, user_name: p.name,
        entries: values.map((v, i) => ({
          quarter: i + 1,
          old_value: childMap.value.get(goalKey(p.user_id, splitForm.metric, 'quarter', i + 1, null)) ?? null,
          new_value: v,
        })),
      })
    } else {
      const quarters = [1, 2, 3, 4].map(q => Number(baseValue(goalKey(p.user_id, splitForm.metric, 'quarter', q, null))) || 0)
      if (!quarters.some(v => v)) return
      const months = quarters.flatMap(qv => splitQuarterToMonths(qv, { integer }))
      rows.push({
        user_id: p.user_id, user_name: p.name,
        entries: months.map((v, i) => ({
          month: i + 1,
          old_value: childMap.value.get(goalKey(p.user_id, splitForm.metric, 'month', null, i + 1)) ?? null,
          new_value: v,
        })),
      })
    }
  }))
  return rows
}

async function previewSplit() {
  splitLoading.value = true
  try {
    const [source, target] = splitDirection.value.split(':')
    const weights = source === 'year' ? SEASON_WEIGHTS : [1, 1, 1]
    const res = await perfGoalApi.splitGoals(props.periodId, {
      metric: splitForm.metric, source, target, weights, apply: false,
    })
    splitPreview.value = res.preview?.length ? res.preview : localPreview()
    splitLoaded.value = true
  } catch {
    splitPreview.value = localPreview()
    splitLoaded.value = true
  } finally {
    splitLoading.value = false
  }
}
async function applySplit() {
  splitLoading.value = true
  try {
    const [source, target] = splitDirection.value.split(':')
    const weights = source === 'year' ? SEASON_WEIGHTS : [1, 1, 1]
    await perfGoalApi.splitGoals(props.periodId, {
      metric: splitForm.metric, source, target, weights, apply: true,
    })
    msgSuccessText('拆分已应用')
    splitVisible.value = false
    await load()
    emit('saved')
  } finally {
    splitLoading.value = false
  }
}

watch(() => props.periodId, () => {
  Object.keys(edits).forEach(k => delete edits[k])
  load()
}, { immediate: true })
defineExpose({ reload: load })
</script>
