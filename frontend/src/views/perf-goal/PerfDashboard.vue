<template>
  <div class="perf-goal-page">
    <!-- 控制条 -->
    <div class="pg-card pg-control-bar">
      <div class="pg-ctl-group">
        <label>视角</label>
        <div class="pg-seg">
          <button v-for="s in scopes" :key="s.key" :class="{ 'pg-active': scope === s.key }" @click="changeScope(s.key)">{{ s.name }}</button>
        </div>
      </div>
      <div v-if="scope === 'team'" class="pg-ctl-group">
        <label>选择战队</label>
        <el-select v-model="scopeId" class="pg-w-160" @change="reload">
          <el-option v-for="t in teamOptions" :key="t.department_id" :label="t.name" :value="t.department_id" />
        </el-select>
      </div>
      <div v-else-if="scope === 'person'" class="pg-ctl-group">
        <label>选择业务员</label>
        <el-select v-model="scopeId" filterable class="pg-w-160" @change="reload">
          <el-option v-for="p in personOptions" :key="p.user_id" :label="p.label" :value="p.user_id" />
        </el-select>
      </div>
      <div class="pg-ctl-group">
        <label>周期</label>
        <div class="pg-seg">
          <button v-for="p in periodTypes" :key="p.key" :class="{ 'pg-active': periodType === p.key }" @click="changePeriodType(p.key)">{{ p.name }}</button>
        </div>
        <el-select v-if="periodType === 'quarter'" v-model="quarter" class="pg-w-90" @change="reload">
          <el-option v-for="q in [1, 2, 3, 4]" :key="q" :label="`Q${q}`" :value="q" />
        </el-select>
        <el-select v-else-if="periodType === 'month'" v-model="month" class="pg-w-90" @change="reload">
          <el-option v-for="m in 12" :key="m" :label="`${m}月`" :value="m" />
        </el-select>
      </div>
      <div v-if="overview?.as_of" class="pg-ctl-group">
        <label>统计截止</label>
        <span class="pg-badge pg-gray">{{ overview.as_of }}</span>
      </div>
      <div v-if="overview?.time_progress != null" class="pg-ctl-group" style="margin-left:auto">
        <span class="pg-badge pg-amber"><span class="pg-dot"></span>{{ overview.period_label || '当前周期' }}时间进度 {{ overview.time_progress }}%</span>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon style="margin-bottom:16px">
      <el-button style="margin-left:8px" @click="reload">重试</el-button>
    </el-alert>

    <!-- 无 active period 引导 -->
    <div v-if="noPeriod" class="pg-card pg-empty" style="padding:60px 0">
      <p style="font-size:15px;color:var(--pg-ink-2)">尚未设置绩效目标周期</p>
      <p>请先在「目标设置」中创建并激活一个周期，看板数据即可生成。</p>
      <el-button type="primary" @click="$router.push('/invoice/perf-goals/targets')">前往目标设置</el-button>
    </div>

    <template v-else>
      <div v-loading="loadingOverview">
        <MetricCards v-if="overview" :metrics="overview.metrics" :time-progress="overview.time_progress" :period-label="shortPeriodLabel" />
        <div class="pg-pace-grid">
          <div class="pg-card" style="margin-bottom:0">
            <div class="pg-card-title"><h2>时间进度匹配</h2><span class="pg-note">子弹图：深色条=实际完成 · 灰带=目标 · 橙色竖线=时间进度</span></div>
            <PaceBulletChart v-if="overview" :metrics="overview.metrics" :time-progress="overview.time_progress" />
          </div>
          <SprintWarnings :warnings="overview?.warnings || []" :time-progress="overview?.time_progress" :remain-days="remainDays" />
        </div>
      </div>

      <CumulativeTrendChart
        v-model:metric="trendMetric"
        :labels="trend.labels || []" :cumulative-actual="trend.cumulative_actual || []"
        :plan="trend.plan || []" :time-progress-line="trend.time_progress_line || []"
        :period-actual="trend.period_actual || []" :loading="loadingTrend" />

      <TeamBoard :rows="teams" :time-progress="overview?.time_progress" :highlight-team="highlightTeam" :loading="loadingTeams" />

      <RankingTable
        :rows="ranking" :loading="loadingRanking" :time-progress="overview?.time_progress"
        :period-label="overview?.period_label || ''" :scope="scope" :highlight-user-id="scope === 'person' ? scopeId : null"
        :sort="rankSort" :order="rankOrder" @sort-change="changeRankSort" />

      <MetricOrderTabs
        :key="`${scope}:${scopeId}`" :users="personOptions" :teams="teamOptions"
        :preset-user-id="scope === 'person' ? scopeId : null"
        :preset-department-id="scope === 'team' ? scopeId : null" />
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { perfGoalApi } from '@/api/perfGoal'
import { currentBeijingDate } from '@/utils/datetime'
import MetricCards from './components/MetricCards.vue'
import PaceBulletChart from './components/PaceBulletChart.vue'
import SprintWarnings from './components/SprintWarnings.vue'
import CumulativeTrendChart from './components/CumulativeTrendChart.vue'
import TeamBoard from './components/TeamBoard.vue'
import RankingTable from './components/RankingTable.vue'
import MetricOrderTabs from './components/MetricOrderTabs.vue'

const scopes = [{ key: 'company', name: '全员总览' }, { key: 'team', name: '按战队' }, { key: 'person', name: '按个人' }]
const periodTypes = [{ key: 'year', name: '年度' }, { key: 'quarter', name: '季度' }, { key: 'month', name: '月度' }]

const [beijingYear, beijingMonth] = currentBeijingDate().split('-').map(Number)
const scope = ref('company'), scopeId = ref(null)
const periodType = ref('year'), quarter = ref(Math.min(4, Math.floor((beijingMonth - 1) / 3) + 1)), month = ref(beijingMonth)
const year = ref(beijingYear)
const trendMetric = ref('gmv')

const period = ref(null), roster = ref({ teams: [], unassigned: [] })
const overview = ref(null), trend = ref({}), teams = ref([]), ranking = ref([])
const loadingOverview = ref(false), loadingTrend = ref(false), loadingTeams = ref(false), loadingRanking = ref(false)
const error = ref(''), noPeriod = ref(false)
const rankSort = ref('gmv_rate'), rankOrder = ref('desc')

const teamOptions = computed(() => (roster.value.teams || []).map(t => ({ department_id: t.department_id, name: t.name })))
const personOptions = computed(() => (roster.value.teams || []).flatMap(t =>
  (t.members || []).map(m => ({ user_id: m.user_id, name: m.name, label: `${m.name}${m.listed === false ? '（未设目标）' : ''}`, team_name: t.name }))))

const periodParams = computed(() => ({
  period_type: periodType.value, year: year.value,
  quarter: periodType.value === 'quarter' ? quarter.value : undefined,
  month: periodType.value === 'month' ? month.value : undefined,
}))
const scopeParams = computed(() => ({
  scope: scope.value,
  scope_id: scope.value === 'company' ? undefined : scopeId.value ?? undefined,
  ...periodParams.value,
}))

const shortPeriodLabel = computed(() => {
  if (periodType.value === 'quarter') return `Q${quarter.value}`
  if (periodType.value === 'month') return `${month.value}月`
  return '年度'
})
const remainDays = computed(() => {
  if (periodType.value !== 'year') return null
  const end = new Date(year.value, 11, 31)
  return Math.max(0, Math.ceil((end.getTime() - Date.now()) / 86400000))
})
const highlightTeam = computed(() => {
  if (scope.value === 'team') return teamOptions.value.find(t => t.department_id === scopeId.value)?.name || ''
  if (scope.value === 'person') return personOptions.value.find(p => p.user_id === scopeId.value)?.team_name || ''
  return ''
})

async function loadBase() {
  try {
    period.value = await perfGoalApi.activePeriod({ suppressToast: true })
    noPeriod.value = !period.value
  } catch {
    period.value = null
    noPeriod.value = true
  }
  if (period.value?.year) year.value = period.value.year
  try {
    roster.value = await perfGoalApi.roster({ suppressToast: true })
  } catch { /* 名单加载失败不阻塞看板 */ }
  if (!scopeId.value) {
    if (scope.value === 'team') scopeId.value = teamOptions.value[0]?.department_id ?? null
    if (scope.value === 'person') scopeId.value = personOptions.value[0]?.user_id ?? null
  }
}

async function loadOverview() {
  loadingOverview.value = true
  try {
    overview.value = await perfGoalApi.overview(scopeParams.value, { suppressToast: true })
    error.value = ''
  } catch (e) {
    overview.value = null
    error.value = e?.response?.data?.detail || '看板数据加载失败，请重试'
  } finally {
    loadingOverview.value = false
  }
}
async function loadTrend() {
  loadingTrend.value = true
  try {
    trend.value = await perfGoalApi.trend({ ...scopeParams.value, metric: trendMetric.value }, { suppressToast: true })
  } catch { trend.value = {} } finally { loadingTrend.value = false }
}
async function loadTeams() {
  loadingTeams.value = true
  try {
    const res = await perfGoalApi.teams(periodParams.value, { suppressToast: true })
    teams.value = res.rows || []
  } catch { teams.value = [] } finally { loadingTeams.value = false }
}
async function loadRanking() {
  loadingRanking.value = true
  try {
    const res = await perfGoalApi.ranking({ ...periodParams.value, sort: rankSort.value, order: rankOrder.value }, { suppressToast: true })
    ranking.value = res.rows || []
  } catch { ranking.value = [] } finally { loadingRanking.value = false }
}

function reload() {
  if (noPeriod.value) return
  loadOverview(); loadTrend(); loadTeams(); loadRanking()
}
function changeScope(key) {
  scope.value = key
  if (key === 'team' && !teamOptions.value.some(t => t.department_id === scopeId.value)) scopeId.value = teamOptions.value[0]?.department_id ?? null
  if (key === 'person' && !personOptions.value.some(p => p.user_id === scopeId.value)) scopeId.value = personOptions.value[0]?.user_id ?? null
  reload()
}
function changePeriodType(key) { periodType.value = key; reload() }
function changeRankSort({ sort, order }) { rankSort.value = sort; rankOrder.value = order; loadRanking() }

onMounted(async () => { await loadBase(); reload() })
watch(trendMetric, loadTrend)
</script>

<style src="./perf-goal.css"></style>
