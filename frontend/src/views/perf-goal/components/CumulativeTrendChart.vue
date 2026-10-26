<template>
  <div>
    <div class="pg-card">
      <div class="pg-card-title">
        <h2>累积完成趋势</h2>
        <span class="pg-note">实线=实际累积 · 虚线=当前周期进行中 · 灰实线=目标计划 · 灰虚线=时间进度</span>
        <div class="pg-right pg-metric-switch">
          <button v-for="m in METRICS" :key="m.key" :class="{ 'pg-active': m.key === metric }" @click="$emit('update:metric', m.key)">{{ m.name }}</button>
        </div>
      </div>
      <div ref="trendEl" class="pg-chart" style="height:360px" role="img" aria-label="累积完成趋势" v-loading="loading"></div>
    </div>
    <div class="pg-card">
      <div class="pg-card-title">
        <h2>各期单月完成</h2>
        <span class="pg-note">单期值（非累积），当前期为截至统计日的部分值</span>
      </div>
      <div ref="monthlyEl" class="pg-chart" style="height:260px" role="img" aria-label="各期单月完成" v-loading="loading"></div>
    </div>
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
    legend: { bottom: 0, itemWidth: 14, textStyle: { fontSize: 12, color: C.muted } },
    grid: { left: 16, right: 24, top: 30, bottom: 34, containLabel: true },
    xAxis: { type: 'category', data: props.labels, boundaryGap: false, axisLine: { lineStyle: { color: C.axisline } } },
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
    xAxis: { type: 'category', data: props.labels, axisLine: { lineStyle: { color: C.axisline } } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: C.gridline } }, axisLabel: { formatter: axisFmt } },
    series: [{
      name: `${metricMeta(props.metric).name} 单期完成`, type: 'bar', barMaxWidth: 42,
      data: props.periodActual.map((v, i) => ({ value: v, itemStyle: { color: i === lastIdx ? C.amber : C.primary, borderRadius: [4, 4, 0, 0] } })),
    }],
  }, true)
}

function render() { renderTrend(); renderMonthly() }
watch(() => [props.labels, props.cumulativeActual, props.plan, props.timeProgressLine, props.periodActual, props.metric], () => nextTick(render), { deep: true })
onMounted(() => {
  render()
  observer = new ResizeObserver(() => { trendChart?.resize(); monthlyChart?.resize() })
  if (trendEl.value) observer.observe(trendEl.value)
  if (monthlyEl.value) observer.observe(monthlyEl.value)
})
onBeforeUnmount(() => { observer?.disconnect(); trendChart?.dispose(); monthlyChart?.dispose() })
</script>
