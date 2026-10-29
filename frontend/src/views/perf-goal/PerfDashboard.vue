<template>
  <div class="perf-goal-page">
    <div class="pg-card pg-control-bar">
      <div class="pg-ctl-group">
        <label>视角</label><div class="pg-seg" role="group" aria-label="分析视角">
          <button v-for="s in scopes" :key="s.key" :class="{ 'pg-active': scope === s.key }" :aria-pressed="scope === s.key" :disabled="!ready" @click="changeScope(s.key)">{{ s.name }}</button>
        </div>
      </div>
      <div v-if="scope === 'team'" class="pg-ctl-group">
        <label>战队</label><el-select v-model="scopeId" aria-label="选择分析战队" class="pg-w-160" @change="reload"><el-option v-for="t in teamOptions" :key="t.department_id" :label="t.name" :value="t.department_id" /></el-select>
      </div>
      <div v-else-if="scope === 'person'" class="pg-ctl-group">
        <label>业务员</label><el-select v-model="scopeId" aria-label="选择分析业务员" filterable class="pg-w-160" @change="reload"><el-option v-for="p in personOptions" :key="p.user_id" :label="p.label" :value="p.user_id" /></el-select>
      </div>
      <div class="pg-ctl-group">
        <label>周期</label><div class="pg-seg" role="group" aria-label="分析周期">
          <button v-for="p in periodTypes" :key="p.key" :class="{ 'pg-active': periodType === p.key }" :aria-pressed="periodType === p.key" :disabled="!ready" @click="changePeriodType(p.key)">{{ p.name }}</button>
        </div>
        <el-select v-if="periodType === 'quarter'" v-model="quarter" aria-label="选择季度" class="pg-w-90" @change="reload"><el-option v-for="q in [1,2,3,4]" :key="q" :label="`Q${q}`" :value="q" /></el-select>
        <el-select v-else-if="periodType === 'month'" v-model="month" aria-label="选择月份" class="pg-w-90" @change="reload"><el-option v-for="m in 12" :key="m" :label="`${m}月`" :value="m" /></el-select>
      </div>
      <span v-if="overview?.time_progress != null" class="pg-note">时间进度 {{ overview.time_progress }}%</span>
      <p v-if="ready && !noPeriod" class="pg-context-note"><strong>当前分析：{{ analysisLabel }}</strong> · {{ rangeText }}</p>
    </div>
    <ListPageStatus v-if="loadingBase" :loading="true" :has-data="false" />
    <ListPageStatus v-else-if="baseError" :error="baseError" :has-data="false" @retry="initialize" />
    <div v-else-if="noPeriod" class="pg-card pg-empty">
      <p>尚未设置绩效目标周期</p><p>创建并设为看板生效周期后，可查看目标完成情况。</p>
      <GlassButton v-permission="'perf_goal:write'" variant="primary" @click="$router.push('/invoice/perf-goals/targets')">前往目标设置</GlassButton>
    </div>
    <template v-else-if="ready">
      <details class="pg-metric-guide">
        <summary>指标口径与时间进度说明</summary>
        <dl><template v-for="item in METRIC_GUIDE" :key="item.name"><dt>{{ item.name }}</dt><dd>{{ item.text }}</dd></template></dl>
      </details>
      <ListPageStatus v-if="overviewError" :error="overviewError" :has-data="false" @retry="reload" />
      <div v-else v-loading="loadingOverview">
        <MetricCards v-if="overview" :metrics="overview.metrics" :time-progress="overview.time_progress" :period-label="fullPeriodLabel" />
        <SprintWarnings v-if="overview && !loadingOverview" :warnings="overview.warnings || []" :metrics="overview.metrics" :time-progress="overview.time_progress" />
        <details v-if="overview" class="pg-card pg-optional-chart" @toggle="showPace = $event.target.open">
          <summary>查看四指标与时间进度对比</summary>
          <PaceBulletChart v-if="showPace" :metrics="overview.metrics" :time-progress="overview.time_progress" />
        </details>
      </div>
      <ListPageStatus v-if="trendError" :error="trendError" :has-data="false" @retry="loadTrend(viewVersion, { ...scopeParams })" />
      <CumulativeTrendChart v-else v-model:metric="trendMetric" :labels="trend.labels || []" :cumulative-actual="trend.cumulative_actual || []" :plan="trend.plan || []" :time-progress-line="trend.time_progress_line || []" :period-actual="trend.period_actual || []" :loading="loadingTrend" />
      <section v-if="access.compare" aria-label="当前周期对比">
        <div class="pg-comparison-heading"><h2>{{ comparisonLabel }} · {{ fullPeriodLabel }}</h2><span class="pg-note">对比范围：{{ comparisonRange }}；上方当前分析的对象以高亮标识</span></div>
        <ListPageStatus v-if="teamsError" :error="teamsError" :has-data="false" @retry="loadTeams(viewVersion, { ...periodParams })" />
        <TeamBoard v-else :rows="teams" :time-progress="overview?.time_progress" :highlight-team="highlightTeam" :loading="loadingTeams" />
        <ListPageStatus v-if="rankingError" :error="rankingError" :has-data="false" @retry="loadRanking(viewVersion, { ...periodParams })" />
        <RankingTable v-else :rows="ranking" :loading="loadingRanking" :time-progress="overview?.time_progress" :period-label="fullPeriodLabel" :total-label="access.company ? '全员有目标成员合计' : '本队有目标成员合计'" :highlight-user-id="scope === 'person' ? scopeId : null" :sort="rankSort" :order="rankOrder" @sort-change="changeRankSort" />
      </section>
      <MetricOrderTabs :users="personOptions" :teams="teamOptions" :preset-user-id="scope === 'person' ? scopeId : null" :preset-department-id="scope === 'team' ? scopeId : null" :period-range="detailPeriod.range" :period-not-started="detailPeriod.notStarted" :analysis-label="analysisLabel" :preset-listed-only="scope === 'company'" />
    </template>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { perfGoalApi } from '@/api/perfGoal'
import { useAuthStore } from '@/stores/auth'
import { currentBeijingDate } from '@/utils/datetime'
import { METRIC_GUIDE } from './displayText'
import { perfViewAccess, selectedPerfRange } from './viewState'
import MetricCards from './components/MetricCards.vue'
import PaceBulletChart from './components/PaceBulletChart.vue'
import SprintWarnings from './components/SprintWarnings.vue'
import CumulativeTrendChart from './components/CumulativeTrendChart.vue'
import TeamBoard from './components/TeamBoard.vue'
import RankingTable from './components/RankingTable.vue'
import MetricOrderTabs from './components/MetricOrderTabs.vue'

const auth = useAuthStore()
const periodTypes = [{ key: 'year', name: '年度' }, { key: 'quarter', name: '季度' }, { key: 'month', name: '月度' }]
const [beijingYear, beijingMonth] = currentBeijingDate().split('-').map(Number)
const scope = ref('person'), scopeId = ref(null), periodType = ref('year'), year = ref(beijingYear)
const quarter = ref(Math.floor((beijingMonth - 1) / 3) + 1), month = ref(beijingMonth), trendMetric = ref('gmv'), showPace = ref(false)
const period = ref(null), roster = ref({ teams: [], unassigned: [] }), overview = ref(null), trend = ref({}), teams = ref([]), ranking = ref([])
const loadingBase = ref(true), ready = ref(false), baseError = ref(''), noPeriod = ref(false)
const loadingOverview = ref(false), loadingTrend = ref(false), loadingTeams = ref(false), loadingRanking = ref(false)
const overviewError = ref(''), trendError = ref(''), teamsError = ref(''), rankingError = ref('')
const rankSort = ref('gmv_rate'), rankOrder = ref('desc')
const access = computed(() => perfViewAccess(auth.user, roster.value))
const scopes = computed(() => [...(access.value.company ? [{ key: 'company', name: '全员总览' }] : []), ...(access.value.teams.length ? [{ key: 'team', name: '按战队' }] : []), { key: 'person', name: '按个人' }])
const teamOptions = computed(() => access.value.teams)
const personOptions = computed(() => access.value.people.map(person => ({ ...person, label: `${person.name}${person.listed === false ? '（未设目标）' : ''}` })))
const periodParams = computed(() => ({ period_type: periodType.value, year: year.value, quarter: periodType.value === 'quarter' ? quarter.value : undefined, month: periodType.value === 'month' ? month.value : undefined }))
const scopeParams = computed(() => ({ scope: scope.value, scope_id: scope.value === 'company' ? undefined : scopeId.value ?? undefined, ...periodParams.value }))
const fullPeriodLabel = computed(() => periodType.value === 'month' ? `${year.value}年${month.value}月` : periodType.value === 'quarter' ? `${year.value}年Q${quarter.value}` : `${year.value}年度`)
const scopeLabel = computed(() => scope.value === 'company' ? '全员（有年度目标人员）' : scope.value === 'team' ? teamOptions.value.find(item => item.department_id === scopeId.value)?.name || '请选择战队' : personOptions.value.find(item => item.user_id === scopeId.value)?.name || '请选择业务员')
const analysisLabel = computed(() => `${scopeLabel.value} · ${fullPeriodLabel.value}`)
const detailPeriod = computed(() => selectedPerfRange(periodParams.value, currentBeijingDate()))
const rangeText = computed(() => detailPeriod.value.notStarted ? '周期尚未开始' : `${detailPeriod.value.range.join(' 至 ')}（统计截止）`)
const comparisonLabel = computed(() => access.value.company ? '全员对比' : '本队对比')
const comparisonRange = computed(() => access.value.company ? '权限内全部战队和人员' : '本人战队')
const highlightTeam = computed(() => scope.value === 'team' ? scopeLabel.value : scope.value === 'person' ? personOptions.value.find(item => item.user_id === scopeId.value)?.team_name || '' : '')
let baseVersion = 0, viewVersion = 0, trendVersion = 0, rankingVersion = 0, teamsVersion = 0, overviewVersion = 0, disposed = false
function clearViews() { overview.value = null; trend.value = {}; teams.value = []; ranking.value = [] }
async function initialize() {
  const version = ++baseVersion; ++viewVersion; ++trendVersion; ++rankingVersion; ++teamsVersion; ++overviewVersion
  ready.value = false; loadingBase.value = true; baseError.value = ''; noPeriod.value = false; clearViews()
  if (!auth.user || !auth.hasPermission('perf_goal:read')) { baseError.value = '当前账号无权查看绩效看板'; loadingBase.value = false; return }
  try {
    const [active, people] = await Promise.all([perfGoalApi.activePeriod({ suppressToast: true }), perfGoalApi.roster({ suppressToast: true })])
    if (version !== baseVersion || disposed) return
    period.value = active; roster.value = people; noPeriod.value = !active
    if (active?.year) year.value = active.year
    scope.value = access.value.defaultScope; scopeId.value = access.value.defaultId
    ready.value = true; reload()
  } catch (error) { if (version === baseVersion && !disposed) baseError.value = '绩效周期或人员名单读取失败，请重试' }
  finally { if (version === baseVersion && !disposed) loadingBase.value = false }
}
async function loadOverview(version, params) {
  const seq = ++overviewVersion; loadingOverview.value = true; overviewError.value = ''
  try { const res = await perfGoalApi.overview(params, { suppressToast: true }); if (version === viewVersion && seq === overviewVersion && !disposed) { overview.value = res; overviewError.value = '' } }
  catch (error) { if (version === viewVersion && seq === overviewVersion && !disposed) { overview.value = null; overviewError.value = '指标汇总读取失败，请重试' } }
  finally { if (version === viewVersion && seq === overviewVersion && !disposed) loadingOverview.value = false }
}
async function loadTrend(version = viewVersion, params = { ...scopeParams.value }) {
  const seq = ++trendVersion; loadingTrend.value = true; trend.value = {}; trendError.value = ''
  try { const res = await perfGoalApi.trend({ ...params, metric: trendMetric.value }, { suppressToast: true }); if (version === viewVersion && seq === trendVersion && !disposed) trend.value = res }
  catch (error) { if (version === viewVersion && seq === trendVersion && !disposed) trendError.value = '完成趋势读取失败，请重试' }
  finally { if (version === viewVersion && seq === trendVersion && !disposed) loadingTrend.value = false }
}
async function loadTeams(version, params) {
  const seq = ++teamsVersion; loadingTeams.value = true; teamsError.value = ''
  try { const res = await perfGoalApi.teams(params, { suppressToast: true }); if (version === viewVersion && seq === teamsVersion && !disposed) { teams.value = res.rows || []; teamsError.value = '' } }
  catch (error) { if (version === viewVersion && seq === teamsVersion && !disposed) { teams.value = []; teamsError.value = '战队对比读取失败，请重试' } }
  finally { if (version === viewVersion && seq === teamsVersion && !disposed) loadingTeams.value = false }
}
async function loadRanking(version, params) {
  const seq = ++rankingVersion; loadingRanking.value = true; rankingError.value = ''
  try { const res = await perfGoalApi.ranking({ ...params, sort: rankSort.value, order: rankOrder.value }, { suppressToast: true }); if (version === viewVersion && seq === rankingVersion && !disposed) { ranking.value = res.rows || []; rankingError.value = '' } }
  catch (error) { if (version === viewVersion && seq === rankingVersion && !disposed) { ranking.value = []; rankingError.value = '个人排名读取失败，请重试' } }
  finally { if (version === viewVersion && seq === rankingVersion && !disposed) loadingRanking.value = false }
}
function reload() {
  const version = ++viewVersion; clearViews(); overviewError.value = ''; trendError.value = ''; teamsError.value = ''; rankingError.value = ''
  if (!ready.value || noPeriod.value) return
  if (scope.value !== 'company' && scopeId.value == null) { overviewError.value = '当前账号或所选对象不在绩效名单，请核对账号绑定'; return }
  loadOverview(version, { ...scopeParams.value }); loadTrend(version, { ...scopeParams.value })
  if (access.value.compare) { loadTeams(version, { ...periodParams.value }); loadRanking(version, { ...periodParams.value }) }
}
function changeScope(key) {
  if (scope.value === key || !scopes.value.some(item => item.key === key)) return
  scope.value = key
  scopeId.value = key === 'team' ? teamOptions.value[0]?.department_id ?? null : key === 'person' ? personOptions.value.find(person => String(person.user_id) === String(auth.user.id))?.user_id ?? personOptions.value[0]?.user_id ?? null : null
  reload()
}
function changePeriodType(key) { if (periodType.value !== key) { periodType.value = key; reload() } }
function changeRankSort({ sort, order }) { rankSort.value = sort; rankOrder.value = order; ranking.value = []; loadRanking(viewVersion, { ...periodParams.value }) }
watch(trendMetric, () => { if (ready.value && !noPeriod.value) loadTrend() })
watch(() => JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions]), initialize, { immediate: true })
onBeforeUnmount(() => { disposed = true; ++baseVersion; ++viewVersion; ++trendVersion; ++rankingVersion; ++teamsVersion; ++overviewVersion })
</script>
<style src="./perf-goal.css"></style>
