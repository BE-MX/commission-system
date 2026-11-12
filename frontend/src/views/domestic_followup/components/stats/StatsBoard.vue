<template>
  <div ref="root" class="stats-board" :class="{ 'stats-enter': entering }">
    <div class="stats-head">
      <div><h2>{{ heading }}</h2><p class="stats-sub">{{ subheading }}</p></div><span class="stats-spacer" />
      <template v-if="view !== 'ai'">
        <StatsSegments :model-value="range" :options="rangeOptions" label="时间范围" @change="changeRange" />
        <el-date-picker v-if="range === 'custom'" v-model="customDates" class="stats-custom-range" type="daterange" value-format="YYYY-MM-DD"
                        start-placeholder="开始日期" end-placeholder="结束日期" @change="changeCustomDates" />
      </template>
    </div>
    <el-alert v-if="currentError" class="stats-error" type="error" :title="currentError" :closable="false" show-icon>
      <template #default><GlassButton variant="link" @click="loadView()">重新加载</GlassButton></template>
    </el-alert>
    <div v-loading="currentLoading && !hasData">
      <PersonalStats v-if="view === 'personal' && personal.data" :data="personal.data" v-model:person="person" v-model:chart="chart" :can-read-all="canReadAll"
                     @drilldown="drilldown" @timeline="id => $emit('timeline', id)" @record="openRecord" @go-tab="tab => $emit('go-tab', tab)" />
      <TeamStats v-else-if="view === 'team' && team.data" :data="team.data" v-model:chart="chart"
                 @drilldown="drilldown" @collaboration="key => $emit('collaboration', key)" />
      <InsightBoard v-else-if="view === 'ai' && !currentLoading" :data="insightData" :roster="personal.data?.roster || []" :can-read-all="canReadAll"
                    v-model:ai-person="aiPerson" v-model:ai-tab="aiTab" :loading="insights.loading" :refreshing="refreshing" :error="insights.error"
                    :refresh-handler="refresh" :feedback-handler="feedback" :task-handler="createTask" :adopt-handler="adopt"
                    @ai-person-change="changeAiPerson" @record="openRecord" />
      <el-empty v-if="!hasData && currentLoading" description="正在加载看板" :image-size="72" />
    </div>
    <div ref="dock" class="stats-dock" :class="{ 'is-instant': instantDock }" role="tablist" aria-label="统计看板视图"
         :style="{ '--stats-dock-left': `${dockLeft}px` }" @keydown="dockKeydown">
      <span ref="thumb" class="stats-dock__thumb" aria-hidden="true" />
      <button v-for="option in views" :key="option.key" type="button" role="tab" :aria-selected="view === option.key" :tabindex="view === option.key ? 0 : -1"
              @click="changeView(option.key)"><el-icon><component :is="icons[option.icon]" /></el-icon>{{ option.key === 'personal' && !canReadAll ? '我的数据' : option.label }}</button>
    </div>
    <StatsDrilldownDrawer ref="drilldownRef" @record="record => $emit('record-detail', record)" @timeline="id => $emit('timeline', id)" @write="openRecord" />
  </div>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef } from 'vue'
import { MagicStick, User, UserFilled } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { useStatsBoard } from '../../composables/useStatsBoard'
import PersonalStats from './PersonalStats.vue'
import TeamStats from './TeamStats.vue'
import InsightBoard from './InsightBoard.vue'
import StatsDrilldownDrawer from './StatsDrilldownDrawer.vue'
import StatsSegments from './StatsSegments.vue'
import { availableViews, nextView } from './statsModel'

const props = defineProps({ api: { type: Object, required: true }, canReadAll: Boolean })
const emit = defineEmits(['timeline', 'record', 'record-detail', 'go-tab', 'collaboration'])
const board = useStatsBoard(props.api, toRef(props, 'canReadAll'))
const {
  view, range, customDates, person, chart, aiTab, aiPerson, personal, team, insights, refreshing,
  loadPersonal, loadView, changeRange, changeCustomDates, changeAiPerson,
} = board
const root = ref(null), dock = ref(null), thumb = ref(null), drilldownRef = ref(null)
const entering = ref(true), instantDock = ref(false), dockLeft = ref(0)
let observer, enterTimer, instantTimer
const icons = { User, UserFilled, MagicStick }
const rangeOptions = [{ value: 'w', label: '本周' }, { value: '30', label: '近 30 天' }, { value: 'q', label: '本季度' }, { value: 'custom', label: '自定义' }]
const views = computed(() => availableViews(props.canReadAll))
const heading = computed(() => ({ personal: props.canReadAll ? '个人数据' : '我的数据', team: '团队数据', ai: 'AI 建议' }[view.value]))
const subheading = computed(() => ({ personal: '跟进量、覆盖与行为质量，全部可以下钻', team: '合并口径与人员差异，不做绩效排名', ai: '数字来自统计，判断绑定原始记录' }[view.value]))
const currentError = computed(() => ({ personal: personal.error, team: team.error, ai: insights.error }[view.value]))
const currentLoading = computed(() => ({ personal: personal.loading, team: team.loading, ai: insights.loading && !insights.data }[view.value]))
const hasData = computed(() => Boolean({ personal: personal.data, team: team.data, ai: insights.data }[view.value]))
const insightData = computed(() => insights.data || { personal: null, company: null, refresh: { status: 'idle', remaining: 2, limit: 2 } })
function drilldown(params, title) { drilldownRef.value?.open(params, title) }
function openRecord(row) { emit('record', row) }
function reload() {
  loadPersonal()
  if (team.loaded) board.loadTeam()
  if (insights.loaded) board.loadInsights()
}
defineExpose({ reload })
async function moveThumb(instant = false) {
  await nextTick()
  if (!dock.value || !thumb.value) return
  const selected = dock.value.querySelector('[aria-selected="true"]')
  if (!selected) return
  instantDock.value = instant
  thumb.value.style.width = `${selected.offsetWidth}px`
  thumb.value.style.transform = `translateX(${selected.offsetLeft}px)`
  clearTimeout(instantTimer)
  if (instant) instantTimer = setTimeout(() => { instantDock.value = false }, 0)
}
function changeView(key, keyboard = false) {
  if (view.value === key) return
  board.setView(key)
  entering.value = !keyboard
  clearTimeout(enterTimer)
  if (!keyboard) enterTimer = setTimeout(() => { entering.value = false }, 1100)
  moveThumb(keyboard)
  root.value?.scrollIntoView({ block: 'start' })
}
function dockKeydown(event) {
  if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
  event.preventDefault()
  const key = nextView(view.value, props.canReadAll, event.key === 'ArrowRight' ? 1 : -1)
  changeView(key, true)
  nextTick(() => dock.value?.querySelector(`[aria-selected="true"]`)?.focus())
}
function updateDockPosition() {
  const rect = root.value?.getBoundingClientRect()
  if (rect?.width) dockLeft.value = rect.left + rect.width / 2
  moveThumb(true)
}
async function refresh() {
  if (await board.refreshInsights()) msgSuccessText('AI 建议已更新')
}
async function feedback(id, value) {
  try { await board.insightFeedback(id, value); msgSuccessText(value ? '反馈已记录' : '已取消反馈') }
  catch (failure) { msgError(apiError(failure, '反馈保存失败'), failure) }
}
async function createTask(id, payload) {
  try { await board.insightToTask(id, payload); msgSuccessText('已生成约定跟进') }
  catch (failure) { msgError(apiError(failure, '生成待办失败'), failure); throw failure }
}
async function adopt(id, note) {
  try { await board.adoptInsight(id, note); msgSuccessText('已标记采纳') }
  catch (failure) { msgError(apiError(failure, '采纳保存失败'), failure); throw failure }
}
loadPersonal()
onMounted(() => {
  if (view.value === 'ai') loadView('ai')
  observer = new ResizeObserver(updateDockPosition)
  if (root.value) observer.observe(root.value)
  updateDockPosition()
  document.fonts?.ready.then(updateDockPosition)
  enterTimer = setTimeout(() => { entering.value = false }, 1100)
})
onBeforeUnmount(() => { observer?.disconnect(); clearTimeout(enterTimer); clearTimeout(instantTimer) })
</script>
<style src="./stats.css"></style>
