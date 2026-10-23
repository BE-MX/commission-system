<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>战队目标</h2>
      <span class="pg-note">战队目标 = 成员目标之和 × 加权系数（可用覆盖值）；成员目标变更后可一键重算</span>
      <div class="pg-right pg-metric-switch">
        <button v-for="m in METRICS" :key="m.key" :class="{ 'pg-active': metric === m.key }" @click="metric = m.key; load()">{{ m.name }}</button>
      </div>
    </div>
    <div class="pg-table-wrap" v-loading="loading">
      <table class="pg-tbl">
        <thead>
          <tr>
            <th>战队</th><th class="pg-c">成员数</th>
            <th class="pg-r">成员汇总（自动）</th><th class="pg-c">加权系数</th>
            <th class="pg-r">覆盖值</th><th class="pg-r">生效目标</th>
            <th>调整留痕</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.department_id">
            <td><b>{{ row.team_name }}</b> <span style="color:var(--pg-faint);font-size:12px">队长 {{ row.captain_name }}</span></td>
            <td class="pg-c">{{ row.member_count }}</td>
            <td class="pg-r">
              {{ fmtMetric(metric, row.auto_value) }}
              <span v-if="row.stale" class="pg-recalc-flag">● 待重算</span>
            </td>
            <td class="pg-c">
              <input class="pg-cell-input pg-factor-input" :value="factorDraft[row.department_id] ?? percentOf(row)" @change="e => editFactor(row, e.target.value)" /> %
            </td>
            <td class="pg-r pg-editable">
              <input class="pg-cell-input" :value="overrideDraft[row.department_id] ?? (row.override_value ?? '')" placeholder="—" @change="e => editOverride(row, e.target.value)" />
            </td>
            <td class="pg-r"><b>{{ fmtMetric(metric, row.effective_value) }}</b></td>
            <td style="color:var(--pg-muted);font-size:12px">{{ trailOf(row) }}</td>
            <td><el-button :loading="recalcLoading === row.department_id" @click="recalc(row)">重算</el-button></td>
          </tr>
          <tr v-if="!rows.length && !loading"><td colspan="8" class="pg-empty">暂无战队目标数据</td></tr>
        </tbody>
      </table>
    </div>
    <div class="pg-toolbar" style="margin-top:12px;margin-bottom:0">
      <el-button type="primary" :loading="saving" :disabled="!hasDraft" @click="save">保存系数/覆盖值</el-button>
      <span class="pg-footnote" style="margin-top:0">说明：成员目标变更后显示「待重算」，点击「重算」按最新成员目标刷新；系数/覆盖值调整会保留留痕。</span>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { msgSuccessText, msgWarning } from '@/utils/feedback'
import { perfGoalApi } from '@/api/perfGoal'
import { METRICS, fmtMetric } from '../helpers'

const props = defineProps({
  periodId: { type: [String, Number], default: null },
  granularity: { type: String, default: 'year' },
})
const emit = defineEmits(['saved'])

const metric = ref('gmv')
const rows = ref([]), loading = ref(false), saving = ref(false), recalcLoading = ref(null)
const factorDraft = reactive({}), overrideDraft = reactive({})

const percentOf = row => (row.factor != null ? Math.round(Number(row.factor) * 10000) / 100 : 100)
const trailOf = row => (row.updated_by ? `${row.updated_at || ''} ${row.updated_by} 调整`.trim() : '—')
const hasDraft = computed(() => Object.keys(factorDraft).length + Object.keys(overrideDraft).length > 0)

function editFactor(row, raw) {
  const v = Number(raw)
  if (Number.isNaN(v) || v <= 0) { msgWarning('系数需为正数'); delete factorDraft[row.department_id]; return }
  factorDraft[row.department_id] = v / 100
}
function editOverride(row, raw) {
  if (raw === '' || raw == null) { overrideDraft[row.department_id] = null; return }
  const v = Number(raw)
  if (Number.isNaN(v) || v < 0) { msgWarning('请输入非负数字'); return }
  overrideDraft[row.department_id] = v
}

async function load() {
  if (!props.periodId) { rows.value = []; return }
  loading.value = true
  try {
    const res = await perfGoalApi.teamGoals(props.periodId, { granularity: props.granularity, metric: metric.value }, { suppressToast: true })
    rows.value = res.rows || []
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}
async function save() {
  const payload = rows.value
    .filter(r => r.department_id in factorDraft || r.department_id in overrideDraft)
    .map(r => ({
      department_id: r.department_id, metric: metric.value, granularity: props.granularity,
      factor: r.department_id in factorDraft ? factorDraft[r.department_id] : r.factor,
      override_value: r.department_id in overrideDraft ? overrideDraft[r.department_id] : r.override_value,
    }))
  saving.value = true
  try {
    await perfGoalApi.saveTeamGoals(props.periodId, payload)
    Object.keys(factorDraft).forEach(k => delete factorDraft[k])
    Object.keys(overrideDraft).forEach(k => delete overrideDraft[k])
    msgSuccessText('战队目标已保存')
    await load()
    emit('saved')
  } finally {
    saving.value = false
  }
}
async function recalc(row) {
  recalcLoading.value = row.department_id
  try {
    await perfGoalApi.recalcTeamGoals(props.periodId)
    msgSuccessText(`「${row.team_name}」已按最新成员目标重算`)
    await load()
    emit('saved')
  } finally {
    recalcLoading.value = null
  }
}
watch(() => [props.periodId, props.granularity], load, { immediate: true })
defineExpose({ reload: load })
</script>
