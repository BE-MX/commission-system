<template>
  <section>
    <div v-if="isAll" class="stats-head"><span class="stats-spacer" />
      <StatsSegments :model-value="chart" :options="chartOptions" label="图表类型" @change="$emit('update:chart', $event)" /></div>
    <div v-if="canReadAll" class="stats-chips" aria-label="业务员筛选">
      <button type="button" class="stats-chip stats-chip--all" :aria-pressed="person === 'all'" @click="$emit('update:person', 'all')">全部并排</button>
      <button v-for="user in data.roster" :key="user.id" type="button" class="stats-chip" :aria-pressed="person === user.id" @click="$emit('update:person', user.id)">
        <span class="stats-avatar">{{ user.real_name.slice(-1) }}</span>{{ user.real_name }}
      </button>
    </div>
    <div v-if="isAll" class="stats-grid stats-gauto">
      <article v-for="(item, index) in data.people" :key="item.user.id" class="stats-card lg-card is-static" :style="{ '--stats-index': index }">
        <div class="stats-chead">
          <span class="stats-avatar stats-avatar--lg">{{ item.user.real_name.slice(-1) }}</span>
          <div><h3>{{ item.user.real_name }}</h3><span class="stats-hint">负责客户 {{ item.kpis.owner_customers }} 家</span></div>
          <span class="stats-spacer" />
          <StatusBadge :type="item.today.today_count ? 'success' : 'info'">{{ item.today.today_count ? `今日 ${item.today.today_count} 条` : data.missing?.applicable ? '今日未提交' : '今日非工作日' }}</StatusBadge>
        </div>
        <div class="stats-mini"><div><b>{{ item.kpis.count }}</b>跟进次数</div><div><b>{{ item.kpis.reach }}</b>触达客户</div><div><b>{{ percent(item.kpis.effective_rate) }}</b>有效沟通</div><div><b>{{ item.kpis.overdue }}</b>应跟未跟</div></div>
        <Transition name="stats-fade" mode="out-in">
          <StatsRhythmChart :key="chart" :days="item.days" :mode="chart" :today="data.today" compact @select="day => drillDate(item, day)" />
        </Transition>
        <StatsHorizontalBars :rows="compactQuality(item)" />
        <div class="stats-chead"><span class="stats-hint">较上期 {{ deltaInfo(item.kpis.count, item.kpis.previous_count)?.text || '—' }}</span><span class="stats-spacer" /><GlassButton variant="link" @click="$emit('update:person', item.user.id)">查看详情 →</GlassButton></div>
      </article>
    </div>
    <StatsMissingStrip v-if="isAll" :missing="data.missing" />

    <template v-else-if="selected">
      <div class="stats-grid stats-g4">
        <StatsKpiCard :index="0" label="跟进次数" :value="selected.kpis.count" :icon="ChatDotRound" :current="selected.kpis.count" :previous="selected.kpis.previous_count" :team-average="average?.count" />
        <StatsKpiCard :index="1" label="触达客户数" :value="selected.kpis.reach" :icon="User" tone="info" :current="selected.kpis.reach" :previous="selected.kpis.previous_reach" :team-average="average?.reach" :footnote="`负责客户 ${selected.kpis.owner_customers} 家`" />
        <StatsKpiCard :index="2" label="有效沟通率" :value="selected.kpis.effective_rate" :icon="CircleCheck" tone="success" rate :current="selected.kpis.effective_rate" :previous="selected.kpis.previous_effective_rate" percentage-points :team-average="average?.effective_rate" footnote="未接通 / 未回复 / 拒绝不计有效" />
        <StatsKpiCard :index="3" label="应跟未跟" :value="selected.kpis.overdue" unit="家" :icon="Clock" tone="warning" :current="selected.kpis.overdue" :previous="selected.kpis.previous_overdue" inverse interactive footnote="超过等级跟进频率 · 查看名单 →" @click="overdueAll(selected)" />
      </div>
      <article class="stats-card lg-card is-static" style="margin-bottom: 16px">
        <div class="stats-chead"><h3>跟进节奏</h3><span class="stats-hint">{{ shortDate(data.period.start) }} – {{ shortDate(data.period.end) }} · 按跟进日期</span><span class="stats-spacer" />
          <StatsSegments :model-value="chart" :options="chartOptions" label="图表类型" @change="$emit('update:chart', $event)" /></div>
        <div class="stats-rhythm">
          <Transition name="stats-fade" mode="out-in">
            <StatsRhythmChart :key="chart" :days="selected.days" :mode="chart" :today="data.today" :team-average="average?.daily_count" @select="day => drillDate(selected, day)" />
          </Transition>
          <div class="stats-facts">
            <div class="stats-fact"><span>工作日日均</span><b>{{ selected.rhythm_summary.average ?? '—' }}</b></div>
            <div class="stats-fact"><span>单日最多</span><b>{{ selected.rhythm_summary.best }}</b></div>
            <div class="stats-fact"><span>断档工作日</span><b>{{ selected.rhythm_summary.gaps }}<small> 天</small></b></div>
            <div class="stats-fact"><span>未回复后再跟间隔</span><b>{{ selected.average_recontact_days ?? '—' }}<small v-if="selected.average_recontact_days !== null"> 天</small></b></div>
          </div>
        </div>
        <div v-if="!canReadAll && data.missing?.applicable" class="stats-missing" :class="{ 'stats-missing--ok': selected.today.today_count }">
          <el-icon><CircleCheck v-if="selected.today.today_count" /><Warning v-else /></el-icon>
          <span v-if="selected.today.today_count">今天已记录 <strong>{{ selected.today.today_count }}</strong> 条跟进</span><span v-else>你今天还没有记录跟进</span>
          <span class="stats-spacer" /><GlassButton v-permission="'domestic_followup:write'" v-if="!selected.today.today_count" variant="primary" @click="$emit('record', null)">记一条跟进</GlassButton>
        </div>
        <StatsMissingStrip v-else :missing="singleMissing(selected)" single />
      </article>
      <div class="stats-grid stats-g2">
        <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>客户覆盖</h3><span class="stats-hint">按等级频率跟上的客户 / 负责客户</span></div>
          <StatsHorizontalBars :rows="coverageRows(selected)" />
          <p class="stats-hint">频率取自「跟进设置」 · 未定级 {{ selected.ungraded_customers }} 家，不计超期。</p></article>
        <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>应跟未跟</h3><StatusBadge type="warning">{{ selected.kpis.overdue }} 家</StatusBadge><span class="stats-spacer" /><GlassButton variant="link" @click="overdueAll(selected)">全部 →</GlassButton></div>
          <div class="stats-rows"><div v-for="row in selected.overdue_customers" :key="row.customer_id" class="stats-row">
            <GlassButton variant="link" @click="$emit('timeline', row.customer_id)">{{ row.shop_name }}</GlassButton><StatusBadge>{{ row.level }}</StatusBadge><span class="stats-spacer" />
            <span class="stats-hint">已超期 <b>{{ row.overdue_days }}</b> 天</span><GlassButton v-permission="'domestic_followup:write'" @click="$emit('record', row)">记跟进</GlassButton>
          </div></div><el-empty v-if="!selected.overdue_customers.length" description="都按频率跟上了" :image-size="56" /></article>
      </div>
      <div class="stats-grid stats-g2">
        <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>跟进结果</h3><span class="stats-hint">点击任一项查看对应记录</span></div>
          <StatsHorizontalBars :rows="resultRows(selected)" @select="row => drillResult(selected, row)" />
          <div class="stats-legend"><span><i />计入有效沟通</span><span><i class="is-soft" />未形成有效沟通</span></div></article>
        <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>推进障碍</h3><span class="stats-hint">一条记录可多选</span></div>
          <StatsHorizontalBars :rows="obstacleRows(selected)" @select="row => drillObstacle(selected, row)" /></article>
      </div>
      <div class="stats-grid stats-g2">
        <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>跟进质量</h3><span class="stats-hint">黑色刻度 = 团队均值 · 不合成总分</span></div>
          <StatsHorizontalBars :rows="qualityRows(selected)" @select="row => drillQuality(selected, row)" /></article>
        <article class="stats-card lg-card is-static"><div class="stats-chead"><h3>待办纪律</h3></div>
          <StatsHorizontalBars :rows="disciplineRows(selected)" />
          <div class="stats-mini" style="grid-template-columns: repeat(3, minmax(0, 1fr))"><div><b>{{ selected.average_snooze }}</b>平均顺延次数</div><div><b>{{ selected.discipline.open_issues }}</b>未处理异常/意见</div><div><b>{{ selected.discipline.longest_open_days }} 天</b>最长挂起</div></div>
          <GlassButton variant="link" @click="$emit('go-tab', 'tasks')">去待办处理 →</GlassButton></article>
      </div>
    </template>
  </section>
</template>
<script setup>
import StatusBadge from '@/components/StatusBadge.vue'
import { computed } from 'vue'
import { ChatDotRound, CircleCheck, Clock, User, Warning } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import StatsHorizontalBars from './StatsHorizontalBars.vue'
import StatsKpiCard from './StatsKpiCard.vue'
import StatsMissingStrip from './StatsMissingStrip.vue'
import StatsRhythmChart from './StatsRhythmChart.vue'
import StatsSegments from './StatsSegments.vue'
import { deltaInfo, percent, qualityDescription, recordsParams, shortDate } from './statsModel'

const props = defineProps({ data: { type: Object, required: true }, person: [String, Number], chart: String, canReadAll: Boolean })
const emit = defineEmits(['update:person', 'update:chart', 'drilldown', 'timeline', 'record', 'go-tab'])
const chartOptions = [{ value: 'heat', label: '日历热力' }, { value: 'bar', label: '曲线柱状' }]
const isAll = computed(() => props.canReadAll && props.person === 'all')
const selected = computed(() => props.canReadAll ? props.data.people.find(item => item.user.id === props.person) : props.data.people[0])
const average = computed(() => props.data.team_average)
function singleMissing(item) { return { applicable: props.data.missing?.applicable, users: item.today.today_count ? [] : [{ user: item.user, ...item.today }] } }
function drillDate(item, day) { if (day.date) emit('drilldown', { kind: 'records', user_id: item.user.id, followup_date: day.date }, `${day.date} 跟进记录`) }
function overdueAll(item) { emit('drilldown', { kind: 'overdue', user_id: item.user.id }, `${item.user.real_name} · 应跟未跟`) }
function drillResult(item, row) { emit('drilldown', { kind: 'records', user_id: item.user.id, result_code: row.name, ...recordsParams(props.data.period) }, `${row.name} · 跟进记录`) }
function drillObstacle(item, row) { emit('drilldown', { kind: 'records', user_id: item.user.id, obstacle: row.name, ...recordsParams(props.data.period) }, `障碍：${row.name}`) }
function drillQuality(item, row) {
  if (row.quality === 'commitment') return emit('drilldown', { kind: 'plans', user_id: item.user.id, ...recordsParams(props.data.period) }, `${item.user.real_name} · 周期内到期约定`)
  emit('drilldown', { kind: 'records', user_id: item.user.id, quality: row.quality, ...recordsParams(props.data.period) }, `${row.label} · 记录`)
}
function coverageRows(item) { return item.coverage.map(row => ({ key: row.level, label: `${row.level} · ${row.frequency_days} 天`, value: row.on_track, max: row.total, text: `${row.on_track}/${row.total}`, tone: row.on_track === row.total && row.total ? 'good' : '', tooltip: `${row.total - row.on_track} 家超过 ${row.frequency_days} 天未跟` })) }
function resultRows(item) { const max = Math.max(1, ...item.results.map(row => row.count)); return item.results.map(row => ({ key: row.name, name: row.name, label: row.name, value: row.count, max, text: row.count, tone: row.effective ? '' : 'soft', clickable: true })) }
function obstacleRows(item) { const max = Math.max(1, ...item.obstacles.map(row => row.count)); return item.obstacles.map(row => ({ key: row.name, name: row.name, label: row.name, value: row.count, max, text: row.count, clickable: true })) }
function qualityRows(item) { return Object.entries(item.quality).map(([key, row]) => ({ key, quality: key, label: row.label, value: row.value || 0, max: 1, tick: row.team_average, text: percent(row.value), tone: row.value !== null && row.team_average !== undefined && row.value >= row.team_average ? 'good' : '', tooltip: `${qualityDescription(key)} · 团队均值 ${percent(row.team_average)}`, clickable: true })) }
function compactQuality(item) { return ['next_step', 'commitment'].map(key => { const row = item.quality[key]; return { key, label: row.label, value: row.value || 0, max: 1, tick: row.team_average, text: percent(row.value), tone: row.value >= row.team_average ? 'good' : '' } }) }
function disciplineRows(item) { return [{ label: '回访闭环率', value: item.discipline.receipt_rate || 0, max: 1, text: percent(item.discipline.receipt_rate), tone: item.discipline.receipt_rate >= 0.85 ? 'good' : '', tooltip: '已回访 ÷（已回访 + 超时过期）' }] }
</script>
