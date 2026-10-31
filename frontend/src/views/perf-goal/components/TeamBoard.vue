<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>战队完成情况</h2>
      <span class="pg-note">目标采用本周期生效目标，含已保存的系数与覆盖值</span>
      <div class="pg-right pg-metric-switch">
        <button v-for="m in METRICS" :key="m.key" :class="{ 'pg-active': m.key === metric }" @click="metric = m.key">{{ m.name }}</button>
      </div>
    </div>
    <div ref="chartEl" class="pg-chart" style="height:320px" role="img" aria-label="战队完成率横向条形图" v-loading="loading"></div>
    <details class="pg-team-details"><summary>查看战队与成员明细（{{ rows.length }} 个战队）</summary>
    <div class="pg-team-grid">
      <div v-for="t in rows" :key="t.department_id" class="pg-team-card" :class="{ 'pg-hl': t.team_name === highlightTeam }">
        <div class="pg-t-head">
          <b>{{ t.team_name }}</b>
          <span>队长 {{ t.captain_name }} · {{ t.member_count }}人</span>
          <span class="pg-t-rate" :style="{ color: (t.overall_rate ?? 0) >= 100 ? 'var(--pg-green)' : 'var(--pg-primary)' }">{{ fmtRate(t.overall_rate) }}</span>
        </div>
        <div class="pg-t-metrics">
          <div v-for="m in METRICS" :key="m.key" class="pg-t-metric">
            <span class="pg-tm-name">{{ m.name }}</span>
            <span class="pg-tm-bar"><i :class="barClass(t.metrics?.[m.key]?.rate)" :style="{ width: `${Math.min(t.metrics?.[m.key]?.rate ?? 0, 100)}%` }"></i></span>
            <span class="pg-tm-val">{{ fmtRate(t.metrics?.[m.key]?.rate) }}</span>
          </div>
        </div>
        <div class="pg-t-members">
          <div v-for="p in t.members || []" :key="p.user_id" class="pg-t-member">
            <span class="pg-tm-name">{{ p.name }}{{ p.listed === false ? '*' : '' }}</span>
            <span class="pg-tm-bar"><i :class="memberBarClass(p)" :style="{ width: `${Math.min(p.gmv_rate ?? 0, 100)}%` }"></i></span>
            <span class="pg-tm-val">{{ p.listed === false || p.gmv_rate == null ? '未设目标' : fmtRate(p.gmv_rate) }}</span>
          </div>
        </div>
      </div>
      <div class="pg-footnote" style="grid-column:1/-1;margin-top:0">* 未设目标成员：展示完成值、不参与个人完成率计算；战队目标以生效目标为准。</div>
    </div>
    </details>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { METRICS, metricMeta, fmtInt, fmtUsd, fmtRate, chartPalette } from '../helpers'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  timeProgress: { type: Number, default: null },
  highlightTeam: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
const metric = ref('gmv')

const sorted = computed(() =>
  [...props.rows].sort((a, b) => (b.metrics?.[metric.value]?.rate ?? 0) - (a.metrics?.[metric.value]?.rate ?? 0)))

const barClass = rate => {
  if (rate == null) return 'pg-none'
  const tp = props.timeProgress ?? 100
  return rate >= 100 ? 'pg-over' : rate >= tp ? '' : 'pg-lag'
}
const memberBarClass = p => (p.listed === false || p.gmv_rate == null ? 'pg-none' : barClass(p.gmv_rate))

const chartEl = ref(null)
let chart, observer
function render() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const C = chartPalette(chartEl.value)
  const k = metric.value
  const meta = metricMeta(k)
  const tp = props.timeProgress ?? 100
  const stats = sorted.value
  const compact = chartEl.value.clientWidth < 480
  const fmtVal = v => (v == null ? '—' : meta.money ? fmtUsd(v) : fmtInt(v))
  chart.setOption({
    animationDuration: 400,
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: ps => {
        const t = stats[ps[0].dataIndex]
        const c = t.metrics?.[k] || {}
        return `${t.team_name}（队长 ${t.captain_name}）<br/>${meta.name}：${fmtVal(c.achieved)} / ${fmtVal(c.target)} · <b>${fmtRate(c.rate)}</b>`
      },
    },
    grid: { left: 16, right: 130, top: 10, bottom: 10, containLabel: true },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: C.gridline } }, axisLabel: { show: !compact, formatter: v => (meta.money ? `$${v >= 10000 ? `${v / 10000}万` : v}` : v) } },
    yAxis: { type: 'category', inverse: true, data: stats.map(t => t.team_name), axisLine: { lineStyle: { color: C.axisline } } },
    series: [{
      type: 'bar', barWidth: 18,
      data: stats.map(t => {
        const c = t.metrics?.[k] || {}
        const rate = c.rate ?? null
        return { value: c.achieved ?? 0, itemStyle: { color: rate == null ? C.target : rate >= 100 ? C.green : rate >= tp ? C.primary : C.orange, borderRadius: [0, 4, 4, 0] } }
      }),
      label: {
        show: true, position: 'right', fontSize: 11.5, color: C.ink2,
        formatter: p => {
          const c = stats[p.dataIndex].metrics?.[k] || {}
          return `${fmtRate(c.rate)}  ${fmtVal(c.achieved)} / ${fmtVal(c.target)}`
        },
      },
    }],
  }, true)
}
watch([sorted, metric], () => nextTick(render))
onMounted(() => {
  render()
  observer = new ResizeObserver(() => { chart?.resize(); render() })
  if (chartEl.value) observer.observe(chartEl.value)
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>
