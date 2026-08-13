<template><div ref="chartEl" class="order-trend-chart" role="img" aria-label="月度复购订单数与复购金额趋势" /></template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({ rows: { type: Array, default: () => [] } })
const chartEl = ref(null)
let chart
let observer

function token(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function render() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const text = token('--text-secondary', 'gray')
  const border = token('--border-color', 'lightgray')
  const primary = token('--color-primary', 'goldenrod')
  const info = token('--color-info-text', 'steelblue')
  chart.setOption({
    animationDuration: 350,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, right: 0, textStyle: { color: text } },
    grid: { left: 12, right: 18, top: 30, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: props.rows.map(row => row.month), axisLabel: { color: text }, axisLine: { lineStyle: { color: border } } },
    yAxis: [
      { type: 'value', name: '订单数', minInterval: 1, axisLabel: { color: text }, splitLine: { lineStyle: { color: border } } },
      { type: 'value', name: '金额 USD', axisLabel: { color: text, formatter: value => `$${Number(value).toLocaleString('en-US', { notation: 'compact' })}` }, splitLine: { show: false } },
    ],
    series: [
      { name: '复购订单数', type: 'bar', yAxisIndex: 0, data: props.rows.map(row => row.repeat_orders), itemStyle: { color: info, borderRadius: [5, 5, 0, 0] } },
      { name: '复购金额 (USD)', type: 'bar', yAxisIndex: 1, data: props.rows.map(row => row.repeat_amount_usd), itemStyle: { color: primary, borderRadius: [5, 5, 0, 0] } },
    ],
  }, true)
}

watch(() => props.rows, () => nextTick(render), { deep: true })
onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(chartEl.value)
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<style scoped>.order-trend-chart { width: 100%; height: 290px; }</style>
