<template>
  <div class="pg-card">
    <div class="pg-card-title">
      <h2>完成趋势</h2>
      <div class="pg-seg" role="group" aria-label="趋势显示方式">
        <button :class="{ 'pg-active': mode === 'cumulative' }" :aria-pressed="mode === 'cumulative'" @click="mode = 'cumulative'">累积</button>
        <button :class="{ 'pg-active': mode === 'period' }" :aria-pressed="mode === 'period'" @click="mode = 'period'">单期</button>
      </div>
      <div class="pg-right pg-metric-switch" role="group" aria-label="趋势指标">
        <button v-for="m in METRICS" :key="m.key" :aria-pressed="m.key === metric" :class="{ 'pg-active': m.key === metric }" @click="$emit('update:metric', m.key)">{{ m.name }}</button>
      </div>
    </div>
    <p class="pg-context-note">{{ mode === 'cumulative' ? '查看累计完成与目标计划、时间进度的差距' : '查看各时间段的单期完成值；当前期统计截至当天' }}</p>
    <div v-show="mode === 'cumulative'" ref="trendEl" class="pg-chart pg-trend-chart" role="img" aria-label="累积完成趋势" v-loading="loading"></div>
    <div v-show="mode === 'period'" ref="monthlyEl" class="pg-chart pg-trend-chart" role="img" aria-label="单期完成趋势" v-loading="loading"></div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { METRICS, metricMeta, fmtInt, fmtUsd, chartPalette } from '../helpers'

const props = defineProps({
  metric: { type: String, required: true },
  labels: { type: Array, default: () => [] },
  cumulativeActual: { type: Array, default: () => [] },
  plan: { type: Array, default: () => [] },
  timeProgressLine: { type: Array, default: () => [] },
  periodActual: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
defineEmits(['update:metric'])

const mode = ref('cumulative')
const trendEl = ref(null), monthlyEl = ref(null)
let trendChart, monthlyChart, observer

const money = () => metricMeta(props.metric).money
const fmtVal = v => (v == null ? '—' : money() ? fmtUsd(v) : `${fmtInt(v)} 个`)
const axisFmt = v => (money() ? `$${v >= 10000 ? `${v / 10000}万` : v}` : v)

/** 实际累积：最后一个非空点与前一段之间用虚线连接（当前周期进行中） */
function actualSeries(C) {
  const data = props.cumulativeActual
  const lastIdx = data.reduce((acc, v, i) => (v != null ? i : acc), -1)
  const solid = data.map((v, i) => (i < lastIdx ? v : null))
  const dashed = data.map((v, i) => (i >= lastIdx - 1 && i <= lastIdx ? v : null))
  return [
    { name: '实际累积', type: 'line', data: solid, smooth: true, symbolSize: 5, lineStyle: { width: 2.5, color: C.primary }, itemStyle: { color: C.primary }, areaStyle: { color: 'rgba(37,99,235,.07)' } },
    { name: '当前期进行中', type: 'line', data: dashed, smooth: true, symbolSize: 5, lineStyle: { width: 2.5, color: C.primary, type: 'dashed' }, itemStyle: { color: C.primary } },
  ]
}

function renderTrend() {
  if (!trendEl.value) return
  if (!trendChart) trendChart = echarts.init(trendEl.value)
  const C = chartPalette(trendEl.value)
  trendChart.setOption({
    animationDuration: 400,
    tooltip: { trigger: 'axis', valueFormatter: fmtVal },
    legend: { type: 'scroll', left: 8, right: 8, bottom: 0, itemWidth: 14, textStyle: { fontSize: 12, color: C.muted } },
    grid: { left: 16, right: 24, top: 30, bottom: 50, containLabel: true },
    xAxis: { type: 'category', axisLabel: { hideOverlap: true }, data: props.labels, boundaryGap: false, axisLine: { lineStyle: { color: C.axisline } } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: C.gridline } }, axisLabel: { formatter: axisFmt } },
    series: [
      ...actualSeries(C),
      { name: '目标计划', type: 'line', data: props.plan, symbol: 'none', lineStyle: { width: 1.5, color: C.target }, itemStyle: { color: C.target } },
      { name: '时间进度参考', type: 'line', data: props.timeProgressLine, symbol: 'none', lineStyle: { width: 1.5, color: C.grayline, type: 'dashed' }, itemStyle: { color: C.grayline } },
    ],
  }, true)
}

function renderMonthly() {
  if (!monthlyEl.value) return
  if (!monthlyChart) monthlyChart = echarts.init(monthlyEl.value)
  const C = chartPalette(monthlyEl.value)
  const lastIdx = props.periodActual.reduce((acc, v, i) => (v != null ? i : acc), -1)
  monthlyChart.setOption({
    animationDuration: 400,
    tooltip: { trigger: 'axis', valueFormatter: fmtVal },
    grid: { left: 16, right: 24, top: 30, bottom: 26, containLabel: true },
    xAxis: { type: 'category', axisLabel: { hideOverlap: true }, data: props.labels, axisLine: { lineStyle: { color: C.axisline } } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: C.gridline } }, axisLabel: { formatter: axisFmt } },
    series: [{
      name: `${metricMeta(props.metric).name} 单期完成`, type: 'bar', barMaxWidth: 42,
      data: props.periodActual.map((v, i) => ({ value: v, itemStyle: { color: i === lastIdx ? C.amber : C.primary, borderRadius: [4, 4, 0, 0] } })),
    }],
  }, true)
}

function render() { if (mode.value === 'cumulative') { renderTrend(); trendChart?.resize() } else { renderMonthly(); monthlyChart?.resize() } }
watch(mode, () => nextTick(render))
watch(() => [props.labels, props.cumulativeActual, props.plan, props.timeProgressLine, props.periodActual, props.metric], () => nextTick(render), { deep: true })
onMounted(() => {
  render()
  observer = new ResizeObserver(() => { trendChart?.resize(); monthlyChart?.resize() })
  if (trendEl.value) observer.observe(trendEl.value)
  if (monthlyEl.value) observer.observe(monthlyEl.value)
})
onBeforeUnmount(() => { observer?.disconnect(); trendChart?.dispose(); monthlyChart?.dispose() })
</script>
