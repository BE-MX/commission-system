<template>
  <div class="perf-goal-page">
    <!-- 周期批次条 -->
    <div class="pg-card pg-batch-bar">
      <template v-if="current">
        <span class="pg-b-name">{{ current.name }}</span>
        <span v-if="current.is_active || current.status === 'active'" class="pg-tag pg-green">已生效</span>
        <span v-else class="pg-tag pg-gray">未激活</span>
        <span class="pg-ver" v-if="current.version">v{{ current.version }}<template v-if="current.published_at"> · {{ formatBeijingDate(current.published_at) }} 发布</template></span>
      </template>
      <span v-else class="pg-ver">暂无目标周期，请新建</span>
      <div style="margin-left:auto;display:flex;gap:10px">
        <el-select :model-value="periodId" placeholder="选择周期" class="pg-w-200" @update:model-value="switchPeriod">
          <el-option v-for="p in periods" :key="p.id" :label="`${p.name}${p.is_active || p.status === 'active' ? '（生效中）' : ''}`" :value="p.id" />
        </el-select>
        <el-button @click="createVisible = true">新建周期</el-button>
        <el-button v-if="current && !(current.is_active || current.status === 'active')" type="primary" :loading="activating" @click="activate">激活当前周期</el-button>
      </div>
    </div>

    <el-alert v-if="!current" type="info" :closable="false" show-icon style="margin-bottom:16px"
      title="尚无目标周期：点击「新建周期」创建年度目标批次，设置目标后激活即可在看板查看。" />

    <TargetGoalTable ref="goalTable" :period-id="periodId" :roster="roster" @saved="onSaved" />
    <TeamGoalPanel ref="teamPanel" :period-id="periodId" @saved="onSaved" />
    <AuditTrail ref="audits" :period-id="periodId" />

    <el-dialog v-model="createVisible" title="新建目标周期" width="480px">
      <el-form label-position="top">
        <el-form-item label="年度">
          <el-input-number v-model="createForm.year" :min="2020" :max="2100" style="width:100%" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="如 2026 年度目标" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createPeriod">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { msgSuccessText } from '@/utils/feedback'
import { perfGoalApi } from '@/api/perfGoal'
import { formatBeijingDate, currentBeijingDate } from '@/utils/datetime'
import TargetGoalTable from './components/TargetGoalTable.vue'
import TeamGoalPanel from './components/TeamGoalPanel.vue'
import AuditTrail from './components/AuditTrail.vue'

const periods = ref([]), periodId = ref(null), roster = ref({ teams: [], unassigned: [] })
const goalTable = ref(null), teamPanel = ref(null), audits = ref(null)
const createVisible = ref(false), creating = ref(false), activating = ref(false)
const defaultYear = Number(currentBeijingDate().slice(0, 4))
const createForm = reactive({ year: defaultYear, name: `${defaultYear} 年度目标` })

const current = computed(() => periods.value.find(p => p.id === periodId.value) || null)

async function loadPeriods(preferActive = true) {
  try {
    const res = await perfGoalApi.periods({ suppressToast: true })
    periods.value = res.periods || res.rows || res.items || (Array.isArray(res) ? res : [])
  } catch {
    periods.value = []
  }
  if (preferActive) {
    try {
      const active = await perfGoalApi.activePeriod({ suppressToast: true })
      periodId.value = active?.id ?? periods.value[0]?.id ?? null
      return
    } catch { /* 无生效周期 */ }
  }
  if (!periods.value.some(p => p.id === periodId.value)) periodId.value = periods.value[0]?.id ?? null
}
async function loadRoster() {
  try {
    roster.value = await perfGoalApi.roster({ suppressToast: true })
  } catch { roster.value = { teams: [], unassigned: [] } }
}
function switchPeriod(id) { periodId.value = id }

async function createPeriod() {
  creating.value = true
  try {
    const res = await perfGoalApi.createPeriod({ year: createForm.year, name: createForm.name })
    msgSuccessText('周期已创建')
    createVisible.value = false
    await loadPeriods(false)
    periodId.value = res.id ?? periodId.value
  } finally {
    creating.value = false
  }
}
async function activate() {
  activating.value = true
  try {
    await perfGoalApi.activatePeriod(periodId.value)
    msgSuccessText('当前周期已激活')
    await loadPeriods(false)
  } finally {
    activating.value = false
  }
}
function onSaved() {
  teamPanel.value?.reload()
  audits.value?.reload()
}

onMounted(() => { loadPeriods(); loadRoster() })
</script>

<style src="./perf-goal.css"></style>
