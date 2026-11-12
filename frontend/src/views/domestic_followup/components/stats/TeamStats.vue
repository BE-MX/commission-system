<template>
  <section>
    <div class="stats-grid stats-g5">
      <StatsKpiCard :index="0" label="跟进总次数" :value="data.kpis.count" :icon="ChatDotRound" :current="data.kpis.count" :previous="data.kpis.previous_count" />
      <StatsKpiCard :index="1" label="触达客户数" :value="data.kpis.reach" :icon="User" tone="info" :current="data.kpis.reach" :previous="data.kpis.previous_reach" footnote="按客户去重" />
      <StatsKpiCard :index="2" label="有效沟通率" :value="data.kpis.effective_rate" :icon="CircleCheck" tone="success" rate :current="data.kpis.effective_rate" :previous="data.kpis.previous_effective_rate" percentage-points footnote="按记录合计" />
      <StatsKpiCard :index="3" label="应跟未跟" :value="data.kpis.overdue" unit="家" :icon="Clock" tone="warning" :current="data.kpis.overdue" :previous="data.kpis.previous_overdue" inverse interactive footnote="查看完整名单 →" @click="$emit('drilldown', { kind: 'overdue' }, '团队应跟未跟')" />
      <StatsKpiCard :index="4" label="今日已提交" :value="data.kpis.today_submitted" :unit="`/ ${data.kpis.roster_count} 人`" :icon="UserFilled" tone="violet" :footnote="`统计日 ${data.today}`" />
    </div>
    <article class="stats-card lg-card is-static" style="margin-bottom: 16px">
      <div class="stats-chead"><h3>团队跟进节奏</h3><span class="stats-hint">{{ chart === 'heat' ? '一行一位业务员，一格一天' : '团队每日合计' }}</span><span class="stats-spacer" />
        <StatsSegments :model-value="chart" :options="chartOptions" label="图表类型" @change="$emit('update:chart', $event)" /></div>
      <Transition name="stats-fade" mode="out-in"><StatsRhythmChart :key="chart" :days="data.days" :people="chart === 'heat' ? data.people : null" :mode="chart" :today="data.today" @select="drillDate" /></Transition>
      <StatsMissingStrip :missing="data.missing" />
    </article>
    <article class="stats-card lg-card is-static" style="margin-bottom: 16px">
      <div class="stats-chead"><h3>人员对比</h3><span class="stats-hint">默认按姓名，不做排名；点列头可排序</span></div>
      <div class="stats-table-wrap"><table class="stats-table" style="min-width: 1060px"><thead><tr>
        <th :aria-sort="ariaSort('name')"><TableSortHeader label="业务员" :order="ariaSort('name')" @sort="toggleSort('name')" /></th>
        <th v-for="column in columns" :key="column.key" :aria-sort="ariaSort(column.key)"><TableSortHeader :label="column.label" :order="ariaSort(column.key)" @sort="toggleSort(column.key)" /></th>
      </tr></thead><tbody><tr v-for="row in sortedRows" :key="row.user.id">
        <td><span class="stats-chip--all"><span class="stats-avatar">{{ row.user.real_name.slice(-1) }}</span> {{ row.user.real_name }}</span></td>
        <td v-for="column in columns" :key="column.key"><div class="stats-cellbar"><span class="stats-cellbar__track"><span class="stats-cellbar__fill" :style="{ width: barWidth(metric(row, column.key), column.key) }" /></span><b>{{ metricText(row, column.key) }}</b></div></td>
      </tr></tbody></table></div>
    </article>
    <div class="stats-grid stats-g2">
      <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>市场信号</h3><span class="stats-hint">客户状态变化 · 出现家数 · 与上期对比</span></div>
        <div class="stats-rows"><div v-for="row in data.signals" :key="row.name" class="stats-row"><span>{{ row.name }}</span><span class="stats-spacer" /><b>{{ row.count }} 家</b>
          <StatusBadge :type="row.count > row.previous_count ? 'warning' : 'info'">{{ row.count > row.previous_count ? '↑' : '↓' }} 上期 {{ row.previous_count }}</StatusBadge>
          <GlassButton variant="link" @click="$emit('drilldown', { kind: 'signal', state_change: row.name, ...recordsParams(data.period) }, `${row.name} · 客户名单`)">名单</GlassButton></div></div>
        <el-empty v-if="!data.signals.length" description="本周期没有变化的信号" :image-size="56" /></article>
      <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>团队推进障碍</h3><span class="stats-hint">一条记录可多选</span></div>
        <StatsHorizontalBars :rows="obstacleRows" @select="row => $emit('drilldown', { kind: 'records', obstacle: row.name, ...recordsParams(data.period) }, `团队障碍：${row.name}`)" /></article>
    </div>
    <div class="stats-grid stats-g2">
      <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>异常与意见</h3><span class="stats-hint">按分类</span></div>
        <table class="stats-table"><thead><tr><th v-for="column in issueColumns" :key="column.key" :aria-sort="issueAriaSort(column.key)"><TableSortHeader :label="column.label" :order="issueAriaSort(column.key)" @sort="issueToggleSort(column.key)" /></th></tr></thead>
          <tbody><tr v-for="row in sortedIssues" :key="row.category"><td>{{ row.category }}</td><td>{{ row.count }}</td><td>{{ row.average_resolution_days ?? '—' }}<template v-if="row.average_resolution_days !== null"> 天</template></td><td><StatusBadge v-if="row.open_count" :type="row.open_count > 2 ? 'danger' : 'warning'">{{ row.open_count }} 条</StatusBadge><span v-else>—</span></td></tr></tbody></table></article>
      <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>需协调</h3><span class="stats-hint">沿用协作管理的既有口径</span></div>
        <div class="stats-rows"><div v-for="row in data.coordination" :key="row.key" class="stats-row"><span>{{ row.label }}</span><span class="stats-spacer" /><b>{{ row.count }}</b><GlassButton v-permission="'domestic_followup:coordinate'" variant="link" @click="$emit('collaboration', row.key)">处理</GlassButton></div></div></article>
    </div>
  </section>
</template>
<script setup>
import StatusBadge from '@/components/StatusBadge.vue'
import { computed, toRef } from 'vue'
import { ChatDotRound, CircleCheck, Clock, User, UserFilled } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import TableSortHeader from '@/components/TableSortHeader.vue'
import { useLocalTableSort } from '@/composables/useLocalTableSort'
import StatsHorizontalBars from './StatsHorizontalBars.vue'
import StatsKpiCard from './StatsKpiCard.vue'
import StatsMissingStrip from './StatsMissingStrip.vue'
import StatsRhythmChart from './StatsRhythmChart.vue'
import StatsSegments from './StatsSegments.vue'
import { percent, recordsParams } from './statsModel'

const props = defineProps({ data: { type: Object, required: true }, chart: String })
const emit = defineEmits(['update:chart', 'drilldown', 'collaboration'])
const chartOptions = [{ value: 'heat', label: '日历热力' }, { value: 'bar', label: '曲线柱状' }]
const columns = [
  { key: 'count', label: '跟进次数' }, { key: 'reach', label: '触达客户' }, { key: 'effective_rate', label: '有效沟通率' },
  { key: 'overdue', label: '应跟未跟' }, { key: 'next_step', label: '留下一步' }, { key: 'commitment', label: '约定兑现' },
  { key: 'effective_progress', label: '有效推进' },
]
const fields = { name: row => row.user.real_name }
for (const column of columns) fields[column.key] = row => metric(row, column.key)
const { sortedRows, toggleSort, ariaSort } = useLocalTableSort(computed(() => props.data.people), fields)
const issueColumns = [{ key: 'category', label: '分类' }, { key: 'count', label: '条数' }, { key: 'average_resolution_days', label: '平均解决' }, { key: 'open_count', label: '未解决' }]
const { sortedRows: sortedIssues, toggleSort: issueToggleSort, ariaSort: issueAriaSort } = useLocalTableSort(computed(() => props.data.issues), {})
function metric(row, key) { return key in row.kpis ? row.kpis[key] : row.quality[key]?.value }
function metricText(row, key) { return ['effective_rate', 'next_step', 'commitment', 'effective_progress'].includes(key) ? percent(metric(row, key)) : metric(row, key) }
function barWidth(value, key) { const values = props.data.people.map(row => Number(metric(row, key) || 0)); return `${Math.max(2, Number(value || 0) / Math.max(1, ...values) * 100)}%` }
const obstacleRows = computed(() => { const max = Math.max(1, ...props.data.obstacles.map(row => row.count)); return props.data.obstacles.map(row => ({ ...row, label: row.name, value: row.count, max, text: row.count, clickable: true })) })
function drillDate(day) { if (day.date) emit('drilldown', { kind: 'records', user_id: day.userId, followup_date: day.date }, `${day.date} · 团队跟进记录`) }
</script>
